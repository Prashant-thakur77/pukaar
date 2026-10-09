"""DynamoDB single-table repository (PLAN.md section 6).

Keys:
  VILLAGE#id  META | READING#iso | REPORT#iso#id | DEDUPE#window | RECIPIENT#id
              | EVENT#date | DIRECTIVE#iso#id
  ALERT#id    META | DELIVERY#recipient | TIMELINE#iso#n
  ALERTLOG    iso#alert_id            (index of every alert, newest last)
  REPORTREF#id META                   (pointer to the report item)
  TRACK#code  META                    (pointer from a tracking code to its report)
  AUDIT#date  iso#id                  (append only; no update or delete path)
  REPLAY      META
Sparse GSI gsi1: gsi1pk = "OPEN#ALERT" / "OPEN#REPORT" while work is open.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Any, Iterable, TypeVar

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError
from pydantic import BaseModel

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.store.models import (
    OPEN_ALERT_STATUSES,
    Alert,
    AuditRow,
    Delivery,
    Directive,
    PastEvent,
    Reading,
    Recipient,
    ReplayState,
    Report,
    TimelineEvent,
    Village,
)

M = TypeVar("M", bound=BaseModel)
_KEY_FIELDS = {"pk", "sk", "gsi1pk", "gsi1sk", "ttl", "kind"}


class ConflictError(Exception):
    """A conditional write lost: the item changed or already exists."""


def _to_dynamo(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_dynamo(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_to_dynamo(v) for v in value]
    return value


def _from_dynamo(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_dynamo(v) for v in value]
    return value


def _model(cls: type[M], item: dict[str, Any]) -> M:
    data = {k: v for k, v in _from_dynamo(item).items() if k not in _KEY_FIELDS}
    return cls.model_validate(data)


def table_schema(name: str) -> dict[str, Any]:
    """CreateTable arguments; used by local mode and tests (the SAM template mirrors it)."""
    return {
        "TableName": name,
        "BillingMode": "PAY_PER_REQUEST",
        "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        "AttributeDefinitions": [
            {"AttributeName": n, "AttributeType": "S"} for n in ("pk", "sk", "gsi1pk", "gsi1sk")
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "gsi1",
                "KeySchema": [
                    {"AttributeName": "gsi1pk", "KeyType": "HASH"},
                    {"AttributeName": "gsi1sk", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    }


class Repo:
    def __init__(self, table: Any) -> None:
        self.t = table

    # -- generic helpers -------------------------------------------------
    def _put(self, item: dict[str, Any], condition: Any = None) -> None:
        kwargs: dict[str, Any] = {"Item": _to_dynamo(item)}
        if condition is not None:
            kwargs["ConditionExpression"] = condition
        try:
            self.t.put_item(**kwargs)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ConflictError(str(exc)) from exc
            raise

    def _get(self, pk: str, sk: str) -> dict[str, Any] | None:
        return self.t.get_item(Key={"pk": pk, "sk": sk}).get("Item")

    def _query(self, pk: str, prefix: str = "", *, newest_first: bool = False, limit: int | None = None) -> list[dict]:
        cond = Key("pk").eq(pk)
        if prefix:
            cond = cond & Key("sk").begins_with(prefix)
        kwargs: dict[str, Any] = {"KeyConditionExpression": cond, "ScanIndexForward": not newest_first}
        items: list[dict] = []
        while True:
            if limit is not None:
                kwargs["Limit"] = limit - len(items)
            page = self.t.query(**kwargs)
            items.extend(page.get("Items", []))
            if "LastEvaluatedKey" not in page or (limit is not None and len(items) >= limit):
                return items
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def _gsi(self, gsi1pk: str) -> list[dict]:
        page = self.t.query(IndexName="gsi1", KeyConditionExpression=Key("gsi1pk").eq(gsi1pk))
        return page.get("Items", [])

    def _update(self, pk: str, sk: str, fields: dict[str, Any], *, remove: Iterable[str] = (), condition: Any = None) -> dict:
        names: dict[str, str] = {}
        values: dict[str, Any] = {}
        sets = []
        for i, (k, v) in enumerate(fields.items()):
            names[f"#u{i}"] = k
            values[f":u{i}"] = _to_dynamo(v)
            sets.append(f"#u{i} = :u{i}")
        expr = ("SET " + ", ".join(sets)) if sets else ""
        removes = list(remove)
        if removes:
            for j, k in enumerate(removes):
                names[f"#x{j}"] = k
            expr += " REMOVE " + ", ".join(f"#x{j}" for j in range(len(removes)))
        kwargs: dict[str, Any] = {
            "Key": {"pk": pk, "sk": sk},
            "UpdateExpression": expr.strip(),
            "ExpressionAttributeNames": names,
            "ReturnValues": "ALL_NEW",
        }
        if values:
            kwargs["ExpressionAttributeValues"] = values
        if condition is not None:
            kwargs["ConditionExpression"] = condition
        try:
            return self.t.update_item(**kwargs)["Attributes"]
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ConflictError(str(exc)) from exc
            raise

    # -- villages --------------------------------------------------------
    def put_village(self, v: Village) -> None:
        self._put({"pk": f"VILLAGE#{v.id}", "sk": "META", "kind": "village", **v.model_dump()})
        # A small registry partition, so listing villages is one query, not a table scan.
        self._put({"pk": "VILLAGES", "sk": v.id})

    def get_village(self, village_id: str) -> Village | None:
        item = self._get(f"VILLAGE#{village_id}", "META")
        return _model(Village, item) if item else None

    def list_villages(self) -> list[Village]:
        ids = [str(i["sk"]) for i in self._query("VILLAGES")]
        villages = [v for v in (self.get_village(i) for i in ids) if v is not None]
        return sorted(villages, key=lambda v: v.name)

    def update_village(self, village_id: str, **fields: Any) -> Village:
        remove = [k for k, v in fields.items() if v is None]
        sets = {k: (v.model_dump() if isinstance(v, BaseModel) else v) for k, v in fields.items() if v is not None}
        return _model(Village, self._update(f"VILLAGE#{village_id}", "META", sets, remove=remove))

    # -- readings --------------------------------------------------------
    def put_reading(self, r: Reading, ttl_days: int = 30) -> None:
        expires = int(clock.now().timestamp()) + ttl_days * 86400
        self._put({"pk": f"VILLAGE#{r.village_id}", "sk": f"READING#{r.at}", "ttl": expires, **r.model_dump()})

    def list_readings(self, village_id: str, limit: int = 96) -> list[Reading]:
        items = self._query(f"VILLAGE#{village_id}", "READING#", newest_first=True, limit=limit)
        return [_model(Reading, i) for i in items]

    # -- sweep dedupe ----------------------------------------------------
    def claim_sweep(self, village_id: str, window: str, ttl_seconds: int = 2 * 86400) -> bool:
        """Conditional put; False when this window was already swept."""
        try:
            self._put(
                {
                    "pk": f"VILLAGE#{village_id}",
                    "sk": f"DEDUPE#{window}",
                    "ttl": int(clock.now().timestamp()) + ttl_seconds,
                },
                condition=Attr("pk").not_exists(),
            )
            return True
        except ConflictError:
            return False

    # -- reports ---------------------------------------------------------
    def put_report(self, r: Report) -> None:
        sk = f"REPORT#{r.created_at}#{r.id}"
        item: dict[str, Any] = {"pk": f"VILLAGE#{r.village_id}", "sk": sk, **r.model_dump()}
        if r.state in {"received", "transcribing", "unverified"}:
            item.update(gsi1pk="OPEN#REPORT", gsi1sk=r.created_at)
        self._put(item)
        self._put({"pk": f"REPORTREF#{r.id}", "sk": "META", "village_id": r.village_id, "ref_sk": sk})
        if r.track_code:
            self._put({"pk": f"TRACK#{r.track_code}", "sk": "META", "report_id": r.id})

    def _report_key(self, report_id: str) -> tuple[str, str] | None:
        ref = self._get(f"REPORTREF#{report_id}", "META")
        return (f"VILLAGE#{ref['village_id']}", ref["ref_sk"]) if ref else None

    def get_report(self, report_id: str) -> Report | None:
        key = self._report_key(report_id)
        item = self._get(*key) if key else None
        return _model(Report, item) if item else None

    def update_report(self, report_id: str, **fields: Any) -> Report:
        key = self._report_key(report_id)
        if key is None:
            raise KeyError(report_id)
        remove: list[str] = []
        if "state" in fields and fields["state"] not in {"received", "transcribing", "unverified"}:
            remove = ["gsi1pk", "gsi1sk"]
        return _model(Report, self._update(*key, fields, remove=remove))

    def report_by_track(self, code: str) -> Report | None:
        ref = self._get(f"TRACK#{code}", "META")
        return self.get_report(ref["report_id"]) if ref else None

    def list_reports(self, village_id: str, limit: int = 100) -> list[Report]:
        items = self._query(f"VILLAGE#{village_id}", "REPORT#", newest_first=True, limit=limit)
        return [_model(Report, i) for i in items]

    # -- recipients ------------------------------------------------------
    def put_recipient(self, r: Recipient) -> None:
        self._put({"pk": f"VILLAGE#{r.village_id}", "sk": f"RECIPIENT#{r.id}", **r.model_dump()})

    def list_recipients(self, village_id: str) -> list[Recipient]:
        return [_model(Recipient, i) for i in self._query(f"VILLAGE#{village_id}", "RECIPIENT#")]

    def put_link_code(self, code: str, username: str, ttl_seconds: int = 900) -> None:
        self._put({"pk": f"LINKCODE#{code}", "sk": "META", "username": username,
                   "expires": int(clock.now().timestamp()) + ttl_seconds, "ttl": int(clock.now().timestamp()) + ttl_seconds})

    def consume_link_code(self, code: str) -> str | None:
        """One-time: delete the code and return its officer, or None if unknown or expired."""
        try:
            old = self.t.delete_item(Key={"pk": f"LINKCODE#{code}", "sk": "META"}, ReturnValues="ALL_OLD",
                                     ConditionExpression=Attr("pk").exists()).get("Attributes")
        except ClientError:
            return None
        if not old or int(old.get("expires", 0)) < clock.now().timestamp():
            return None
        return str(old["username"])

    def put_officer_chat(self, username: str, chat_id: str) -> None:
        self._put({"pk": f"OFFICER#{username}", "sk": "META", "chat_id": chat_id})

    def get_officer_chat(self, username: str) -> str | None:
        item = self._get(f"OFFICER#{username}", "META")
        return str(item["chat_id"]) if item else None

    # -- past events -----------------------------------------------------
    def put_past_event(self, e: PastEvent) -> None:
        self._put({"pk": f"VILLAGE#{e.village_id}", "sk": f"EVENT#{e.date}", **e.model_dump()})

    def list_past_events(self, village_id: str) -> list[PastEvent]:
        items = self._query(f"VILLAGE#{village_id}", "EVENT#", newest_first=True)
        return [_model(PastEvent, i) for i in items]

    # -- directives ------------------------------------------------------
    def put_directive(self, d: Directive) -> None:
        self._put({"pk": f"VILLAGE#{d.village_id}", "sk": f"DIRECTIVE#{d.issued_at}#{d.id}", **d.model_dump()})

    def list_directives(self, village_id: str) -> list[Directive]:
        items = self._query(f"VILLAGE#{village_id}", "DIRECTIVE#", newest_first=True)
        return [_model(Directive, i) for i in items]

    # -- alerts ----------------------------------------------------------
    def put_alert(self, a: Alert) -> None:
        item: dict[str, Any] = {"pk": f"ALERT#{a.id}", "sk": "META", **a.model_dump()}
        if a.status in OPEN_ALERT_STATUSES:
            item.update(gsi1pk="OPEN#ALERT", gsi1sk=a.created_at)
        self._put(item, condition=Attr("pk").not_exists())
        self._put({"pk": "ALERTLOG", "sk": f"{a.created_at}#{a.id}", "alert_id": a.id, "village_id": a.village_id,
                   "replay": a.replay})

    def get_alert(self, alert_id: str) -> Alert | None:
        item = self._get(f"ALERT#{alert_id}", "META")
        return _model(Alert, item) if item else None

    def update_alert(self, alert_id: str, *, condition: Any = None, **fields: Any) -> Alert:
        remove = [k for k, v in fields.items() if v is None]
        sets = {k: (v.model_dump() if isinstance(v, BaseModel) else v) for k, v in fields.items() if v is not None}
        sets["updated_at"] = clock.iso(clock.now())
        status = fields.get("status")
        if status is not None and status not in OPEN_ALERT_STATUSES:
            remove += ["gsi1pk", "gsi1sk"]
        cond = Attr("pk").exists() if condition is None else (Attr("pk").exists() & condition)
        return _model(Alert, self._update(f"ALERT#{alert_id}", "META", sets, remove=remove, condition=cond))

    def consume_task_token(self, alert_id: str, token_version: int, **fields: Any) -> Alert:
        """Single-use approval: only succeeds while the alert is pending at this token_version."""
        return self.update_alert(
            alert_id,
            condition=Attr("token_version").eq(token_version) & Attr("status").eq("pending"),
            task_token=None,
            token_version=token_version + 1,
            **fields,
        )

    def list_alerts(self, *, status: str | None = None, village_id: str | None = None, limit: int = 100) -> list[Alert]:
        filtered = bool(status or village_id)
        refs = self._query("ALERTLOG", newest_first=True, limit=500 if filtered else limit)
        if village_id:
            refs = [r for r in refs if r.get("village_id") == village_id]
        alerts = [a for a in (self.get_alert(r["alert_id"]) for r in refs) if a is not None]
        if status:
            wanted = set(status.split(","))
            alerts = [a for a in alerts if a.status in wanted]
        return alerts[:limit]

    def open_alerts(self) -> list[Alert]:
        return [_model(Alert, i) for i in self._gsi("OPEN#ALERT")]

    def alerts_on_day(self, village_id: str, day: str) -> int:
        refs = self._query("ALERTLOG", day)
        return sum(1 for r in refs if r.get("village_id") == village_id and not r.get("replay"))

    # -- deliveries ------------------------------------------------------
    def put_delivery(self, d: Delivery) -> None:
        self._put({"pk": f"ALERT#{d.alert_id}", "sk": f"DELIVERY#{d.recipient_id}", **d.model_dump()})

    def list_deliveries(self, alert_id: str) -> list[Delivery]:
        return [_model(Delivery, i) for i in self._query(f"ALERT#{alert_id}", "DELIVERY#")]

    def update_delivery(self, alert_id: str, recipient_id: str, *, condition: Any = None, **fields: Any) -> Delivery:
        cond = Attr("pk").exists() if condition is None else (Attr("pk").exists() & condition)
        return _model(Delivery, self._update(f"ALERT#{alert_id}", f"DELIVERY#{recipient_id}", fields, condition=cond))

    # -- timeline --------------------------------------------------------
    def add_timeline(self, alert_id: str, step: str, detail: str = "") -> None:
        at = clock.iso(clock.now())
        n = len(self._query(f"ALERT#{alert_id}", "TIMELINE#"))
        self._put({"pk": f"ALERT#{alert_id}", "sk": f"TIMELINE#{at}#{n:04d}", "at": at, "step": step, "detail": detail})

    def list_timeline(self, alert_id: str) -> list[TimelineEvent]:
        return [_model(TimelineEvent, i) for i in self._query(f"ALERT#{alert_id}", "TIMELINE#")]

    # -- audit (append only) --------------------------------------------
    def append_audit(self, row: AuditRow) -> None:
        self._put({"pk": f"AUDIT#{row.at[:10]}", "sk": f"{row.at}#{row.id}", **row.model_dump()})

    def list_audit(self, day: str, resource: str | None = None) -> list[AuditRow]:
        rows = [_model(AuditRow, i) for i in self._query(f"AUDIT#{day}", newest_first=True)]
        return [r for r in rows if resource is None or r.resource == resource]

    # -- replay ----------------------------------------------------------
    def get_replay(self) -> ReplayState:
        item = self._get("REPLAY", "META")
        return _model(ReplayState, item) if item else ReplayState()

    def put_replay(self, state: ReplayState) -> None:
        self._put({"pk": "REPLAY", "sk": "META", **state.model_dump()})

    # -- maintenance -----------------------------------------------------
    def delete_where(self, predicate) -> int:
        """Delete every item for which predicate(item) is true. Used by reset-demo only.

        Audit rows are never passed to delete: they are append-only by design.
        """
        deleted = 0
        kwargs: dict[str, Any] = {}
        while True:
            page = self.t.scan(**kwargs)
            with self.t.batch_writer() as batch:
                for item in page.get("Items", []):
                    if str(item["pk"]).startswith("AUDIT#"):
                        continue
                    if predicate(item):
                        batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
                        deleted += 1
            if "LastEvaluatedKey" not in page:
                return deleted
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


@lru_cache(maxsize=1)
def get_repo() -> Repo:
    s = get_settings()
    resource = boto3.resource("dynamodb", region_name=s.aws_region)
    return Repo(resource.Table(s.table_name))

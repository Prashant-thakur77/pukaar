"""DynamoDB single-table repository.

Keys:
  VILLAGE#id  META | READING#iso | SENSOR#iso#device | SENSORLAST#device | SENSORSEQ#device#boot#seq
              | REPORT#iso#id | DEDUPE#window | RECIPIENT#id
              | EVENT#date | DIRECTIVE#iso#id | CHECKLIST#item | SHELTER#place_id | ROLLCALL#iso#id (pointer, TTL 30 days)
              | STAFFGAUGE#id (virtual staff gauge: reference photo key, scale, marks)
              | ROADBLOCK#id (a blocked road on a baked route; TTL 7 days unless renewed)
  ALERT#id    META | DELIVERY#recipient (Telegram or stub) | DELIVERY#recipient#voice | TIMELINE#iso#n
              | OFFICERCALL#officer (the wake-up call to an officer) | TGFILE (Telegram file id of the audio)
  VOICEKEY#call_id  digit             (a key press already acted on; idempotency, TTL 7 days)
  ROLLCALL#id META | ASKED#recipient | RESP#recipient   (safety roll-call; TTL 30 days)
  SAFESHARE#id META                   (family link pointer; TTL 7 days)
  HELPNOTE#chat META                  (waiting for a short note after "need help"; TTL 1 hour)
  ALERTLOG    iso#alert_id            (index of every alert, newest last)
  REPORTREF#id META                   (pointer to the report item)
  TRACK#code  META                    (pointer from a tracking code to its report)
  AUDIT#date  iso#id                  (append only; no update or delete path)
  REPLAY      META | VILLAGE#id (the replay's own copy of a village: level, hysteresis, open alert)
  OFFICER#username META (Telegram chat) | PUSH#id (Web Push subscription; TTL 180 days) | PUSHTEST (rate limit)
              | PHONE (E.164, for the wake-up call; never logged, never on a route)
  MODELPROBE  META                   (last Bedrock model-access probe; at most one per 6 hours)
  ROSTER#district  date#shift        (duty roster: primary, backup, escalation officer; TTL 400 days)
  FETCHCACHE#key META                (cached external data: daily river ensemble, official feeds; TTL)
  RATE#src#hash | RATE#village#id  window   (report rate-limit counters; salted IP hash, never an IP; TTL 1 day)
Sparse GSI gsi1: gsi1pk = "OPEN#ALERT" / "OPEN#REPORT" while work is open.
"""

from __future__ import annotations

import json
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
    ChecklistItem,
    Delivery,
    E164,
    Directive,
    OfficerCall,
    delivery_key,
    PastEvent,
    PushSubscription,
    Reading,
    Recipient,
    ReplayState,
    Report,
    RoadBlock,
    RollCall,
    RollCallAsked,
    RollCallResponse,
    RosterShift,
    SensorReading,
    ShelterStatus,
    StaffGauge,
    TimelineEvent,
    Village,
)

M = TypeVar("M", bound=BaseModel)
_KEY_FIELDS = {"pk", "sk", "gsi1pk", "gsi1sk", "ttl", "kind"}
ROLLCALL_TTL_DAYS = 30
PUSH_TTL_DAYS = 180
ROSTER_TTL_DAYS = 400  # a year of duty charts, for the after-action record


def report_expiry(created_at: str, days: int | None = None) -> int | None:
    """Epoch seconds at which a villager report expires (DynamoDB TTL), or None when reports are kept
    (Settings.report_retention_days 0). The photo and voice note expire under the S3 lifecycle rule
    the template makes from the same parameter (RetentionDays)."""
    days = get_settings().report_retention_days if days is None else days
    if days <= 0:
        return None
    return int(clock.parse(created_at).timestamp()) + days * 86400


def _expiry(days: int | None = None) -> int:
    """TTL (epoch seconds) of a forecast or gauge reading written now: Settings.reading_retention_days
    unless a caller gives its own."""
    days = get_settings().reading_retention_days if days is None else days
    return int(clock.now().timestamp()) + max(1, days) * 86400


def _expired(item: dict[str, Any], now: int | None = None) -> bool:
    """DynamoDB deletes an expired item within a few days, not at once: never serve one meanwhile."""
    ttl = item.get("ttl")
    return ttl is not None and int(ttl) <= (now if now is not None else int(clock.now().timestamp()))


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

    def _count(self, pk: str, sk_from: str, sk_to: str, flt: Any = None) -> int:
        """How many items of `pk` have sk between sk_from and sk_to (inclusive), after `flt`.
        Select=COUNT: no item bodies come back, only the number."""
        kwargs: dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(sk_from, sk_to),
                                  "Select": "COUNT"}
        if flt is not None:
            kwargs["FilterExpression"] = flt
        total = 0
        while True:
            page = self.t.query(**kwargs)
            total += int(page.get("Count", 0))
            if "LastEvaluatedKey" not in page:
                return total
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def _gsi(self, gsi1pk: str) -> list[dict]:
        page = self.t.query(IndexName="gsi1", KeyConditionExpression=Key("gsi1pk").eq(gsi1pk))
        return page.get("Items", [])

    def _update(self, pk: str, sk: str, fields: dict[str, Any], *, remove: Iterable[str] = (), condition: Any = None,
                add: dict[str, int] | None = None) -> dict:
        names: dict[str, str] = {}
        values: dict[str, Any] = {}
        sets = []
        for i, (k, v) in enumerate(fields.items()):
            names[f"#u{i}"] = k
            values[f":u{i}"] = _to_dynamo(v)
            sets.append(f"#u{i} = :u{i}")
        expr = ("SET " + ", ".join(sets)) if sets else ""
        if add:
            adds = []
            for j, (k, v) in enumerate(add.items()):
                names[f"#a{j}"] = k
                values[f":a{j}"] = v
                adds.append(f"#a{j} :a{j}")
            expr += " ADD " + ", ".join(adds)
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
    def put_reading(self, r: Reading, ttl_days: int | None = None) -> None:
        """One forecast reading, kept Settings.reading_retention_days (template ReadingRetentionDays:
        30 on dev, 400 on prod, so a season's record outlives the season)."""
        expires = _expiry(ttl_days)
        self._put({"pk": f"VILLAGE#{r.village_id}", "sk": f"READING#{r.at}", "ttl": expires, **r.model_dump()})

    def list_readings(self, village_id: str, limit: int = 96) -> list[Reading]:
        items = self._query(f"VILLAGE#{village_id}", "READING#", newest_first=True, limit=limit)
        return [_model(Reading, i) for i in items]

    def count_live_readings(self, village_id: str, since: str, until: str) -> int:
        """Stored forecast readings (one per village per sweep) with since <= at <= until; replay rows excluded."""
        return self._count(f"VILLAGE#{village_id}", f"READING#{since}", f"READING#{until}",
                           Attr("replay").not_exists() | Attr("replay").eq(False))

    # -- gauge (sensor) readings -----------------------------------------
    def put_sensor_reading(self, r: SensorReading, ttl_days: int | None = None, min_interval_s: int = 60) -> bool:
        """Store one live gauge reading. False (nothing stored) when the same device already sent a
        reading less than min_interval_s before this one, or a newer one: a conditional write on a
        per-device pointer, so a replayed or too-frequent body never lands twice. A payload-v2
        reading also claims its (device, boot, seq) marker, so the same reading sent again from the
        device's buffer is a duplicate."""
        at = clock.parse(r.at)
        epoch = int(at.timestamp())
        expires = _expiry(ttl_days)
        pk = f"VILLAGE#{r.village_id}"
        try:
            self._put({"pk": pk, "sk": f"SENSORLAST#{r.device_id}", "at_epoch": epoch, "at": clock.iso(at),
                       "ttl": expires},
                      condition=Attr("pk").not_exists() | Attr("at_epoch").lte(epoch - min_interval_s))
        except ConflictError:
            return False
        if r.seq is not None and not self._claim_sensor_seq(r, expires):
            return False
        self._put({"pk": pk, "sk": f"SENSOR#{clock.iso(at)}#{r.device_id}", "ttl": expires,
                   **r.model_dump(), "at": clock.iso(at)})
        return True

    def _claim_sensor_seq(self, r: SensorReading, expires: int) -> bool:
        try:
            self._put({"pk": f"VILLAGE#{r.village_id}", "sk": f"SENSORSEQ#{r.device_id}#{r.boot or 0}#{r.seq}",
                       "at": r.at, "ttl": expires}, condition=Attr("pk").not_exists())
        except ConflictError:
            return False
        return True

    def put_sensor_backfill(self, r: SensorReading, ttl_days: int | None = None) -> bool:
        """Store one buffered (older) reading. Idempotent on (device, boot, seq) and on the
        reading's own key: False when it is already stored. It never moves the live pointer, so
        the live path's one-per-minute, never-earlier replay protection is unchanged."""
        at = clock.parse(r.at)
        expires = _expiry(ttl_days)
        if r.seq is not None and not self._claim_sensor_seq(r, expires):
            return False
        try:
            self._put({"pk": f"VILLAGE#{r.village_id}", "sk": f"SENSOR#{clock.iso(at)}#{r.device_id}", "ttl": expires,
                       **r.model_dump(), "at": clock.iso(at)}, condition=Attr("pk").not_exists())
        except ConflictError:
            return False
        return True

    def list_sensor_readings(self, village_id: str, since: str, limit: int = 2000) -> list[SensorReading]:
        """Readings at or after `since` (ISO), oldest first."""
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("pk").eq(f"VILLAGE#{village_id}")
            & Key("sk").between(f"SENSOR#{clock.iso(clock.parse(since))}", "SENSOR#~"),
            "ScanIndexForward": True,
        }
        items: list[dict] = []
        while len(items) < limit:
            page = self.t.query(**kwargs)
            items.extend(page.get("Items", []))
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        return [_model(SensorReading, i) for i in items[:limit]]

    def count_sensor_readings(self, village_id: str, since: str, until: str, *, simulated: bool | None = None) -> int:
        """Gauge readings with since <= at <= until; simulated=True/False keeps only that kind."""
        flt = None
        if simulated is True:
            flt = Attr("simulated").eq(True)
        elif simulated is False:
            flt = Attr("simulated").not_exists() | Attr("simulated").eq(False)
        # sk is SENSOR#<iso>#<device>: "~" sorts after the device id, so `until` itself is included.
        return self._count(f"VILLAGE#{village_id}", f"SENSOR#{since}", f"SENSOR#{until}#~", flt)

    def latest_sensor_reading(self, village_id: str, max_age_minutes: float | None = 30, now: Any = None, *,
                              include_backfill: bool = False) -> SensorReading | None:
        """Newest live reading (backfilled ones are skipped unless include_backfill), or None when
        there is none or it is older than max_age_minutes."""
        kwargs: dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(f"VILLAGE#{village_id}")
                                  & Key("sk").begins_with("SENSOR#"), "ScanIndexForward": False, "Limit": 50}
        found = None
        for _ in range(20):  # at most 1,000 rows: a long backfill newer than the last live reading
            page = self.t.query(**kwargs)
            for item in page.get("Items", []):
                if include_backfill or item.get("origin", "live") != "backfill":
                    found = item
                    break
            if found is not None or "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        if found is None:
            return None
        r = _model(SensorReading, found)
        if max_age_minutes is not None:
            now = now or clock.now()
            if (now - clock.parse(r.at)).total_seconds() > max_age_minutes * 60:
                return None
        return r

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
        # DPDP retention (Settings.report_retention_days): the report, its reference and its tracking code
        # expire together, counted from when the report was made, so writing it again never extends it.
        ttl = report_expiry(r.created_at)
        expiry = {"ttl": ttl} if ttl else {}
        item: dict[str, Any] = {"pk": f"VILLAGE#{r.village_id}", "sk": sk, **r.model_dump(), **expiry}
        if r.state in {"received", "transcribing", "unverified"}:
            item.update(gsi1pk="OPEN#REPORT", gsi1sk=r.created_at)
        self._put(item)
        self._put({"pk": f"REPORTREF#{r.id}", "sk": "META", "village_id": r.village_id, "ref_sk": sk, **expiry})
        if r.track_code:
            self._put({"pk": f"TRACK#{r.track_code}", "sk": "META", "report_id": r.id, **expiry})

    def _report_key(self, report_id: str) -> tuple[str, str] | None:
        ref = self._get(f"REPORTREF#{report_id}", "META")
        return (f"VILLAGE#{ref['village_id']}", ref["ref_sk"]) if ref else None

    def get_report(self, report_id: str) -> Report | None:
        key = self._report_key(report_id)
        item = self._get(*key) if key else None
        return _model(Report, item) if item and not _expired(item) else None

    def update_report(self, report_id: str, **fields: Any) -> Report:
        key = self._report_key(report_id)
        if key is None:
            raise KeyError(report_id)
        remove = [k for k, v in fields.items() if v is None]
        sets = {k: v for k, v in fields.items() if v is not None}
        if "state" in fields and fields["state"] not in {"received", "transcribing", "unverified"}:
            remove += ["gsi1pk", "gsi1sk"]
        return _model(Report, self._update(*key, sets, remove=remove))

    def report_by_track(self, code: str) -> Report | None:
        ref = self._get(f"TRACK#{code}", "META")
        return self.get_report(ref["report_id"]) if ref else None

    def list_reports(self, village_id: str, limit: int = 100) -> list[Report]:
        items = self._query(f"VILLAGE#{village_id}", "REPORT#", newest_first=True, limit=limit)
        now = int(clock.now().timestamp())
        return [_model(Report, i) for i in items if not _expired(i, now)]

    def bump_rate(self, scope: str, key: str, window: str, ttl_seconds: int = 86400) -> int:
        """Add one to a fixed-window counter and return the new count (services/report_guard.py).
        One atomic ADD per call: two Lambdas never both read the old count."""
        item = self._update(f"RATE#{scope}#{key}", window, {"ttl": int(clock.now().timestamp()) + ttl_seconds},
                            add={"n": 1})
        return int(item.get("n", 0))

    # -- recipients ------------------------------------------------------
    def put_recipient(self, r: Recipient) -> None:
        self._put({"pk": f"VILLAGE#{r.village_id}", "sk": f"RECIPIENT#{r.id}", **r.model_dump()})

    def list_recipients(self, village_id: str) -> list[Recipient]:
        return [_model(Recipient, i) for i in self._query(f"VILLAGE#{village_id}", "RECIPIENT#")]

    def list_recipients_between(self, village_id: str, first: str, last: str) -> list[Recipient]:
        """The recipients whose ids sort from first to last (inclusive): one delivery batch, read alone."""
        kwargs: dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(f"VILLAGE#{village_id}")
                                  & Key("sk").between(f"RECIPIENT#{first}", f"RECIPIENT#{last}")}
        items: list[dict] = []
        while True:
            page = self.t.query(**kwargs)
            items.extend(page.get("Items", []))
            if "LastEvaluatedKey" not in page:
                return [_model(Recipient, i) for i in items]
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def get_recipient(self, village_id: str, recipient_id: str) -> Recipient | None:
        item = self._get(f"VILLAGE#{village_id}", f"RECIPIENT#{recipient_id}")
        return _model(Recipient, item) if item else None

    def delete_recipient(self, village_id: str, recipient_id: str) -> bool:
        old = self.t.delete_item(Key={"pk": f"VILLAGE#{village_id}", "sk": f"RECIPIENT#{recipient_id}"},
                                 ReturnValues="ALL_OLD")
        return bool(old.get("Attributes"))

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

    # -- Web Push subscriptions (officers and pradhans) ----------------------
    def put_push_subscription(self, sub: PushSubscription) -> None:
        """Insert or replace; the TTL restarts, so a browser that keeps re-subscribing stays on."""
        self._put({"pk": f"OFFICER#{sub.username}", "sk": f"PUSH#{sub.id}", "kind": "push_subscription",
                   "ttl": int(clock.now().timestamp()) + PUSH_TTL_DAYS * 86400, **sub.model_dump()})

    def list_push_subscriptions(self, username: str) -> list[PushSubscription]:
        """DynamoDB removes expired rows lazily, so rows past their TTL are skipped here."""
        now = clock.now().timestamp()
        items = [i for i in self._query(f"OFFICER#{username}", "PUSH#") if int(i.get("ttl", now + 1)) > now]
        return sorted((_model(PushSubscription, i) for i in items), key=lambda s: s.created_at)

    def delete_push_subscription(self, username: str, sub_id: str) -> bool:
        try:
            self.t.delete_item(Key={"pk": f"OFFICER#{username}", "sk": f"PUSH#{sub_id}"},
                               ConditionExpression=Attr("pk").exists())
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def touch_push_subscription(self, username: str, sub_id: str, at: str) -> None:
        try:
            self._update(f"OFFICER#{username}", f"PUSH#{sub_id}", {"last_sent_at": at}, condition=Attr("pk").exists())
        except ConflictError:
            pass  # removed meanwhile

    def claim_push_test(self, username: str, min_interval_s: int = 60) -> bool:
        """Rate limit for test notifications: False if this user sent one less than min_interval_s ago."""
        now = int(clock.now().timestamp())
        try:
            self._put({"pk": f"OFFICER#{username}", "sk": "PUSHTEST", "at_epoch": now, "ttl": now + 86400},
                      condition=Attr("pk").not_exists() | Attr("at_epoch").lte(now - min_interval_s))
        except ConflictError:
            return False
        return True

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

    # -- early-action checklist -------------------------------------------
    def put_checklist_item(self, c: ChecklistItem) -> None:
        self._put({"pk": f"VILLAGE#{c.village_id}", "sk": f"CHECKLIST#{c.item}", **c.model_dump()})

    def list_checklist(self, village_id: str) -> list[ChecklistItem]:
        return [_model(ChecklistItem, i) for i in self._query(f"VILLAGE#{village_id}", "CHECKLIST#")]

    # -- shelter ledger --------------------------------------------------
    def put_shelter(self, s: ShelterStatus) -> None:
        self._put({"pk": f"VILLAGE#{s.village_id}", "sk": f"SHELTER#{s.place_id}", **s.model_dump()})

    def list_shelters(self, village_id: str) -> dict[str, ShelterStatus]:
        rows = [_model(ShelterStatus, i) for i in self._query(f"VILLAGE#{village_id}", "SHELTER#")]
        return {r.place_id: r for r in rows}

    # -- Bedrock model-access probe (one item) ----------------------------
    def get_model_probe(self) -> dict[str, Any] | None:
        item = self._get("MODELPROBE", "META")
        return {k: v for k, v in _from_dynamo(item).items() if k not in _KEY_FIELDS} if item else None

    def claim_model_probe(self, now_iso: str, not_before_iso: str) -> bool:
        """Claim the next probe: succeeds only if none has run since not_before_iso (one sweep wins a race)."""
        try:
            self._update("MODELPROBE", "META", {"checked_at": now_iso},
                         condition=Attr("pk").not_exists() | Attr("checked_at").lt(not_before_iso))
            return True
        except ConflictError:
            return False

    def put_model_probe(self, fields: dict[str, Any]) -> None:
        self._update("MODELPROBE", "META", fields)

    # -- duty roster (services/roster.py) --------------------------------
    def put_roster_shift(self, r: RosterShift, ttl_days: int = ROSTER_TTL_DAYS) -> None:
        expires = int(clock.now().timestamp()) + ttl_days * 86400
        self._put({"pk": f"ROSTER#{r.district}", "sk": f"{r.date}#{r.shift}", "kind": "roster", "ttl": expires,
                   **r.model_dump()})

    def get_roster_shift(self, district: str, date: str, shift: str) -> RosterShift | None:
        item = self._get(f"ROSTER#{district}", f"{date}#{shift}")
        return _model(RosterShift, item) if item else None

    def list_roster(self, district: str, first_date: str, last_date: str) -> list[RosterShift]:
        """Shifts with first_date <= date <= last_date, in date and shift order."""
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("pk").eq(f"ROSTER#{district}")
            & Key("sk").between(f"{first_date}#", f"{last_date}#~"),
        }
        items: list[dict] = []
        while True:
            page = self.t.query(**kwargs)
            items.extend(page.get("Items", []))
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        return [_model(RosterShift, i) for i in items]

    def delete_roster_shift(self, district: str, date: str, shift: str) -> bool:
        old = self.t.delete_item(Key={"pk": f"ROSTER#{district}", "sk": f"{date}#{shift}"}, ReturnValues="ALL_OLD")
        return bool(old.get("Attributes"))
    # -- cached external data (services/fetch_cache.py) ------------------
    def get_cache(self, key: str, now: float) -> tuple[float, dict[str, Any]] | None:
        """(expires, value) while the item has not expired; DynamoDB's own TTL deletes it later."""
        item = self._get(f"FETCHCACHE#{key}", "META")
        if not item or float(item.get("expires", 0)) <= now:
            return None
        return float(item["expires"]), json.loads(str(item["body"]))

    def put_cache(self, key: str, value: dict[str, Any], expires: float) -> None:
        # Stored as a JSON string: floats stay floats, and nested None values survive.
        self._put({"pk": f"FETCHCACHE#{key}", "sk": "META", "body": json.dumps(value, separators=(",", ":")),
                   "expires": int(expires), "ttl": int(expires) + 86400})

    # -- road blocks on evacuation routes --------------------------------
    def put_roadblock(self, b: RoadBlock) -> None:
        """Write (or renew, or clear) a road block; DynamoDB drops it 7 days after its expiry time at the latest."""
        expires = int(clock.parse(b.expires_at).timestamp())
        self._put({"pk": f"VILLAGE#{b.village_id}", "sk": f"ROADBLOCK#{b.id}", "kind": "roadblock", "ttl": expires,
                   **b.model_dump()})

    def get_roadblock(self, village_id: str, block_id: str) -> RoadBlock | None:
        item = self._get(f"VILLAGE#{village_id}", f"ROADBLOCK#{block_id}")
        return _model(RoadBlock, item) if item else None

    def list_roadblocks(self, village_id: str, *, active_only: bool = True) -> list[RoadBlock]:
        """Blocks for a village, oldest first. TTL deletion is lazy, so expiry is checked here too."""
        rows = [_model(RoadBlock, i) for i in self._query(f"VILLAGE#{village_id}", "ROADBLOCK#")]
        if active_only:
            now = clock.iso(clock.now())
            rows = [b for b in rows if b.cleared_at is None and b.expires_at > now]
        return sorted(rows, key=lambda b: b.created_at)

    # -- virtual staff gauges -------------------------------------------
    def put_staff_gauge(self, g: StaffGauge) -> None:
        self._put({"pk": f"VILLAGE#{g.village_id}", "sk": f"STAFFGAUGE#{g.id}", "kind": "staff_gauge", **g.model_dump()})

    def get_staff_gauge(self, village_id: str, gauge_id: str) -> StaffGauge | None:
        item = self._get(f"VILLAGE#{village_id}", f"STAFFGAUGE#{gauge_id}")
        return _model(StaffGauge, item) if item else None

    def list_staff_gauges(self, village_id: str) -> list[StaffGauge]:
        gauges = [_model(StaffGauge, i) for i in self._query(f"VILLAGE#{village_id}", "STAFFGAUGE#")]
        return sorted(gauges, key=lambda g: g.created_at)

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
        self._put({"pk": f"ALERT#{d.alert_id}", "sk": f"DELIVERY#{d.row_key}", **d.model_dump()})

    def list_deliveries(self, alert_id: str) -> list[Delivery]:
        return [_model(Delivery, i) for i in self._query(f"ALERT#{alert_id}", "DELIVERY#")]

    def get_delivery(self, alert_id: str, recipient_id: str, channel: str = "") -> Delivery | None:
        item = self._get(f"ALERT#{alert_id}", f"DELIVERY#{delivery_key(recipient_id, channel)}")
        return _model(Delivery, item) if item else None

    def update_delivery(self, alert_id: str, recipient_id: str, *, channel: str = "", condition: Any = None,
                        **fields: Any) -> Delivery:
        """channel "voice" names the person's voice row; anything else their Telegram or stub row."""
        cond = Attr("pk").exists() if condition is None else (Attr("pk").exists() & condition)
        return _model(Delivery, self._update(f"ALERT#{alert_id}", f"DELIVERY#{delivery_key(recipient_id, channel)}",
                                             fields, condition=cond))

    def get_deliveries(self, alert_id: str, recipient_ids: Iterable[str]) -> list[Delivery]:
        """The rows of these people only (both channels), by BatchGetItem: a batch worker reads its own
        few hundred rows, never every row of the alert."""
        pk = f"ALERT#{alert_id}"
        keys = [{"pk": pk, "sk": f"DELIVERY#{delivery_key(rid, ch)}"}
                for rid in dict.fromkeys(recipient_ids) for ch in ("", "voice")]
        client, name, items = self.t.meta.client, self.t.name, []
        for i in range(0, len(keys), 100):
            request: dict | None = {name: {"Keys": keys[i:i + 100], "ConsistentRead": True}}
            for _ in range(10):
                if not request:
                    break
                resp = client.batch_get_item(RequestItems=request)
                items.extend(resp.get("Responses", {}).get(name, []))
                request = resp.get("UnprocessedKeys") or None
        return [_model(Delivery, i) for i in items]

    def claim_delivery(self, alert_id: str, recipient_id: str, channel: str, *, name: str,
                       expected_attempts: int | None, send_round: int) -> Delivery:
        """Take one send of one row for one round, before anything is sent: a compare-and-set on attempts.

        expected_attempts None: the row must not exist yet (it is made "pending", attempt 1). Otherwise the
        row must still have that many attempts and must not have been claimed in this round already (a
        row put back unsent, deferred, may be claimed again). ConflictError: another batch worker, or an
        earlier try of this one, has it; the caller sends nothing."""
        pk, sk = f"ALERT#{alert_id}", f"DELIVERY#{delivery_key(recipient_id, channel)}"
        if expected_attempts is None:
            d = Delivery(alert_id=alert_id, recipient_id=recipient_id, name=name, channel=channel, status="pending",
                         attempts=1, send_round=send_round)
            self._put({"pk": pk, "sk": sk, **d.model_dump()}, condition=Attr("pk").not_exists())
            return d
        fresh = Attr("send_round").not_exists() | Attr("send_round").ne(send_round) | Attr("deferred").eq(True)
        cond = Attr("pk").exists() & Attr("attempts").eq(expected_attempts) & fresh
        return _model(Delivery, self._update(pk, sk, {"attempts": expected_attempts + 1, "send_round": send_round,
                                                      "deferred": False}, condition=cond))

    def release_delivery(self, alert_id: str, recipient_id: str, channel: str, *, claimed_attempts: int,
                         **fields: Any) -> Delivery | None:
        """Put a claimed row back unsent (a Telegram 429, or out of time): the attempt is not counted and
        the row is marked deferred, so the next pass claims it again. None if the row moved on meanwhile."""
        try:
            return _model(Delivery, self._update(
                f"ALERT#{alert_id}", f"DELIVERY#{delivery_key(recipient_id, channel)}",
                {"attempts": claimed_attempts - 1, "deferred": True, **fields},
                condition=Attr("pk").exists() & Attr("attempts").eq(claimed_attempts)))
        except ConflictError:
            return None

    def get_telegram_file(self, alert_id: str) -> str | None:
        item = self._get(f"ALERT#{alert_id}", "TGFILE")
        return str(item["file_id"]) if item else None

    def put_telegram_file(self, alert_id: str, file_id: str) -> str:
        """The first upload wins; returns the file id every later send uses."""
        try:
            self._put({"pk": f"ALERT#{alert_id}", "sk": "TGFILE", "file_id": file_id},
                      condition=Attr("pk").not_exists())
            return file_id
        except ConflictError:
            return self.get_telegram_file(alert_id) or file_id

    # -- the officer's wake-up call (delivery/officer_call.py) ---------------
    def put_officer_phone(self, username: str, phone: str) -> None:
        phone = phone.strip().replace(" ", "").replace("-", "")
        if not E164.match(phone):
            raise ValueError("phone must be in E.164 form, e.g. +919812345678")
        self._put({"pk": f"OFFICER#{username}", "sk": "PHONE", "phone": phone})

    def get_officer_phone(self, username: str) -> str | None:
        item = self._get(f"OFFICER#{username}", "PHONE")
        return str(item["phone"]) if item and item.get("phone") else None

    def delete_officer_phone(self, username: str) -> None:
        self.t.delete_item(Key={"pk": f"OFFICER#{username}", "sk": "PHONE"})

    def put_officer_call(self, c: OfficerCall) -> None:
        """Once per officer per alert: a retried nudge step never calls twice (ConflictError)."""
        self._put({"pk": f"ALERT#{c.alert_id}", "sk": f"OFFICERCALL#{c.officer}", **c.model_dump()},
                  condition=Attr("pk").not_exists())

    def get_officer_call(self, alert_id: str, officer: str) -> OfficerCall | None:
        item = self._get(f"ALERT#{alert_id}", f"OFFICERCALL#{officer}")
        return _model(OfficerCall, item) if item else None

    def update_officer_call(self, alert_id: str, officer: str, *, condition: Any = None,
                            **fields: Any) -> OfficerCall:
        cond = Attr("pk").exists() if condition is None else (Attr("pk").exists() & condition)
        return _model(OfficerCall, self._update(f"ALERT#{alert_id}", f"OFFICERCALL#{officer}", fields,
                                                condition=cond))

    def list_officer_calls(self, alert_id: str) -> list[OfficerCall]:
        return [_model(OfficerCall, i) for i in self._query(f"ALERT#{alert_id}", "OFFICERCALL#")]

    def claim_voice_key(self, call_id: str, digit: str, ttl_seconds: int = 7 * 86400) -> bool:
        """True the first time this key press on this call is acted on; a retried webhook gets False."""
        try:
            self._put({"pk": f"VOICEKEY#{call_id}", "sk": digit, "ttl": int(clock.now().timestamp()) + ttl_seconds},
                      condition=Attr("pk").not_exists())
            return True
        except ConflictError:
            return False

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

    # -- safety roll-calls ("Surakshit Hoon") ------------------------------
    def _rollcall_ttl(self) -> int:
        return int(clock.now().timestamp()) + ROLLCALL_TTL_DAYS * 86400

    def put_rollcall(self, rc: RollCall) -> None:
        ttl = self._rollcall_ttl()
        self._put({"pk": f"ROLLCALL#{rc.id}", "sk": "META", "ttl": ttl, **rc.model_dump()},
                  condition=Attr("pk").not_exists())
        self._put({"pk": f"VILLAGE#{rc.village_id}", "sk": f"ROLLCALL#{rc.opened_at}#{rc.id}", "rollcall_id": rc.id,
                   "ttl": ttl})

    def get_rollcall(self, rollcall_id: str) -> RollCall | None:
        item = self._get(f"ROLLCALL#{rollcall_id}", "META")
        return _model(RollCall, item) if item else None

    def update_rollcall(self, rollcall_id: str, *, condition: Any = None, **fields: Any) -> RollCall:
        cond = Attr("pk").exists() if condition is None else (Attr("pk").exists() & condition)
        return _model(RollCall, self._update(f"ROLLCALL#{rollcall_id}", "META", fields, condition=cond))

    def list_rollcalls(self, village_id: str, limit: int = 20) -> list[RollCall]:
        refs = self._query(f"VILLAGE#{village_id}", "ROLLCALL#", newest_first=True, limit=limit)
        return [rc for rc in (self.get_rollcall(str(r["rollcall_id"])) for r in refs) if rc is not None]

    def put_rollcall_asked(self, a: RollCallAsked) -> None:
        self._put({"pk": f"ROLLCALL#{a.rollcall_id}", "sk": f"ASKED#{a.recipient_id}", "ttl": self._rollcall_ttl(),
                   **a.model_dump()})

    def get_rollcall_asked(self, rollcall_id: str, recipient_id: str) -> RollCallAsked | None:
        item = self._get(f"ROLLCALL#{rollcall_id}", f"ASKED#{recipient_id}")
        return _model(RollCallAsked, item) if item else None

    def list_rollcall_asked(self, rollcall_id: str) -> list[RollCallAsked]:
        return [_model(RollCallAsked, i) for i in self._query(f"ROLLCALL#{rollcall_id}", "ASKED#")]

    def put_rollcall_response(self, r: RollCallResponse) -> bool:
        """Last answer wins; the same answer again changes nothing (False), so a repeated tap is a no-op."""
        try:
            self._put({"pk": f"ROLLCALL#{r.rollcall_id}", "sk": f"RESP#{r.recipient_id}", "ttl": self._rollcall_ttl(),
                       **r.model_dump()},
                      condition=Attr("pk").not_exists() | Attr("status").ne(r.status))
            return True
        except ConflictError:
            return False

    def get_rollcall_response(self, rollcall_id: str, recipient_id: str) -> RollCallResponse | None:
        item = self._get(f"ROLLCALL#{rollcall_id}", f"RESP#{recipient_id}")
        return _model(RollCallResponse, item) if item else None

    def list_rollcall_responses(self, rollcall_id: str) -> list[RollCallResponse]:
        return [_model(RollCallResponse, i) for i in self._query(f"ROLLCALL#{rollcall_id}", "RESP#")]

    def update_rollcall_response(self, rollcall_id: str, recipient_id: str, **fields: Any) -> RollCallResponse:
        return _model(RollCallResponse, self._update(f"ROLLCALL#{rollcall_id}", f"RESP#{recipient_id}", fields,
                                                     condition=Attr("pk").exists()))

    def put_safe_share(self, share_id: str, rollcall_id: str, recipient_id: str, ttl_seconds: int) -> None:
        """Pointer behind a family link; it expires with the link."""
        self._put({"pk": f"SAFESHARE#{share_id}", "sk": "META", "rollcall_id": rollcall_id,
                   "recipient_id": recipient_id, "ttl": int(clock.now().timestamp()) + ttl_seconds})

    def get_safe_share(self, share_id: str) -> tuple[str, str] | None:
        item = self._get(f"SAFESHARE#{share_id}", "META")
        return (str(item["rollcall_id"]), str(item["recipient_id"])) if item else None

    def put_help_note_wait(self, chat_id: str, rollcall_id: str, ttl_seconds: int = 3600) -> None:
        """After "need help", the next plain message from this chat (within an hour) is kept as the note."""
        expires = int(clock.now().timestamp()) + ttl_seconds
        self._put({"pk": f"HELPNOTE#{chat_id}", "sk": "META", "rollcall_id": rollcall_id, "expires": expires,
                   "ttl": expires})

    def consume_help_note_wait(self, chat_id: str) -> str | None:
        try:
            old = self.t.delete_item(Key={"pk": f"HELPNOTE#{chat_id}", "sk": "META"}, ReturnValues="ALL_OLD",
                                     ConditionExpression=Attr("pk").exists()).get("Attributes")
        except ClientError:
            return None
        if not old or int(old.get("expires", 0)) < clock.now().timestamp():
            return None
        return str(old["rollcall_id"])

    # -- replay ----------------------------------------------------------
    def get_replay(self) -> ReplayState:
        item = self._get("REPLAY", "META")
        return _model(ReplayState, item) if item else ReplayState()

    def put_replay(self, state: ReplayState) -> None:
        self._put({"pk": "REPLAY", "sk": "META", **state.model_dump()})

    # A replay never writes the live village record: it works on its own copy, labelled
    # replay=True, which replay.reset() removes with every other replay item.
    def put_replay_village(self, v: Village) -> None:
        self._put({"pk": "REPLAY", "sk": f"VILLAGE#{v.id}", "kind": "replay_village", **v.model_dump(),
                   "replay": True})

    def get_replay_village(self, village_id: str) -> Village | None:
        item = self._get("REPLAY", f"VILLAGE#{village_id}")
        return _model(Village, item) if item else None

    def list_replay_villages(self) -> dict[str, Village]:
        return {v.id: v for v in (_model(Village, i) for i in self._query("REPLAY", "VILLAGE#"))}

    def update_replay_village(self, village_id: str, **fields: Any) -> Village:
        remove = [k for k, v in fields.items() if v is None]
        sets = {k: (v.model_dump() if isinstance(v, BaseModel) else v) for k, v in fields.items() if v is not None}
        return _model(Village, self._update("REPLAY", f"VILLAGE#{village_id}", sets, remove=remove,
                                            condition=Attr("pk").exists()))

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

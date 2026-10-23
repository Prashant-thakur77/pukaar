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
  VILLAGE#id  ALERTREF#iso#alert_id   (the village's own alert history: a village page reads only its alerts)
  ALERT#id    PERSON#reached#recipient (phone: a real phone, not the demo stub) | PERSON#acked#recipient
              (one marker per person counted, created only if absent; only the call that created it ADDs
              to the alert's counter, so a repeated tap or a retried webhook never counts twice)
  SUMMARY     counters                (the public counters, written by the sweep: /public/overview reads one item)
  RATEBUCKET#name  window | PAUSE     (a send-rate budget shared by every Lambda: delivery/ratelimit.py; TTL)
  CHATVILLAGE#chat  village_id        (the villages a Telegram chat is registered in: /stop finds them all)
  CONSENT#chat  META                  (a /start waiting for the consent button; TTL 1 day; nothing else is kept)
  ERASURE     due_iso#recipient       (personal data still to erase after the last village link went; services/privacy.py)
  OFFICER#username SCOPE              (the districts a staff account is assigned to; services/scope.py)
  DISTRICT#name SETTINGS              (district settings a DDMA head may change: critical auto-send)
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
  VILLAGE#id  DEVICE#device           (device registry and live health; the alarm layer)
              | RAIN#iso#device | RAINSEQ#device#boot#seq   (observed rain: gauge v3 and rain nodes; TTL as readings)
  DEVICES     device                  (pointer: village_id, kind; listing every device is one query)
  DEVICE#device  EVT#iso#boot#seq (90 d) | DEVSEQ#boot#seq (14 d) | TEST#iso (400 d) | CMD#id (400 d)
              | CTR (atomic command counter) | SHADOW#name (local mode only)
  ALERT#id    SIREN#device#round      (the siren tier; never a people DELIVERY# row)
  SIRENREQ#id META                    (two-person siren request; TTL 1 day); VILLAGE#id SIRENREQ#iso#id pointer
  HANDOVER#district  date#shift       (the shift handover note and its acknowledgement; services/duty.py; TTL 400 days)
  ONCE#name   key                     (a job done once per key, e.g. the 08:00 digest per district and day; TTL)
  INBOUND#call_id META                (an inbound IVR call in progress: menu stage, caller; TTL 2 hours; delivery/inbound.py)
Sparse GSI gsi1: gsi1pk = "OPEN#ALERT" / "OPEN#REPORT" while work is open; "OPEN#ROLLCALL" (gsi1sk closes_at).
GSI gsi2 (alert META items only): gsi2pk = "ALERTS#<status>", gsi2sk = "<created_at>#<id>". The inbox reads
the pending alerts of the whole state, or of one district (a filter on the alert's district), newest first,
however many alerts exist: a status is never looked for among only the newest few hundred alerts.
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
    Device,
    E164,
    Directive,
    SirenCommand,
    SirenDelivery,
    SirenRequest,
    OfficerCall,
    delivery_key,
    PastEvent,
    PushSubscription,
    RainReading,
    Reading,
    Recipient,
    ReplayState,
    Report,
    RoadBlock,
    RollCall,
    RollCallAsked,
    RollCallResponse,
    RosterShift,
    HandoverNote,
    SensorReading,
    ShelterStatus,
    StaffGauge,
    TimelineEvent,
    Village,
)

M = TypeVar("M", bound=BaseModel)
_KEY_FIELDS = {"pk", "sk", "gsi1pk", "gsi1sk", "gsi2pk", "gsi2sk", "ttl", "kind"}
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


def _device(item: dict[str, Any]) -> Device:
    """A registry row: its "kind" is the device's kind, not the item-type marker other rows carry."""
    return Device.model_validate({**_from_dynamo({k: v for k, v in item.items() if k not in _KEY_FIELDS}),
                                  "kind": item.get("kind")})


def table_schema(name: str) -> dict[str, Any]:
    """CreateTable arguments; used by local mode and tests (the SAM template mirrors it)."""
    return {
        "TableName": name,
        "BillingMode": "PAY_PER_REQUEST",
        "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        "AttributeDefinitions": [
            {"AttributeName": n, "AttributeType": "S"} for n in ("pk", "sk", "gsi1pk", "gsi1sk", "gsi2pk", "gsi2sk")
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": name,
                "KeySchema": [
                    {"AttributeName": f"{name}pk", "KeyType": "HASH"},
                    {"AttributeName": f"{name}sk", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
            for name in ("gsi1", "gsi2")
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

    def _gsi(self, gsi1pk: str, sk_after: str | None = None) -> list[dict]:
        cond = Key("gsi1pk").eq(gsi1pk)
        if sk_after is not None:
            cond = cond & Key("gsi1sk").gt(sk_after)
        kwargs: dict[str, Any] = {"IndexName": "gsi1", "KeyConditionExpression": cond}
        items: list[dict] = []
        while True:
            page = self.t.query(**kwargs)
            items.extend(page.get("Items", []))
            if "LastEvaluatedKey" not in page:
                return items
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def _batch_get(self, keys: Iterable[tuple[str, str]], *, consistent: bool = False) -> dict[tuple[str, str], dict]:
        """Many items by key, 100 to a BatchGetItem call (DynamoDB's limit), unprocessed keys retried.
        Returns {(pk, sk): item} for the keys that exist."""
        client, name, out = self.t.meta.client, self.t.name, {}
        unique = list(dict.fromkeys(keys))
        for i in range(0, len(unique), 100):
            request: dict | None = {name: {"Keys": [{"pk": pk, "sk": sk} for pk, sk in unique[i:i + 100]],
                                           "ConsistentRead": consistent}}
            for _ in range(10):
                if not request:
                    break
                resp = client.batch_get_item(RequestItems=request)
                for item in resp.get("Responses", {}).get(name, []):
                    out[(str(item["pk"]), str(item["sk"]))] = item
                request = resp.get("UnprocessedKeys") or None
        return out

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

    def village_ids(self) -> list[str]:
        return [str(i["sk"]) for i in self._query("VILLAGES")]

    def list_villages(self) -> list[Village]:
        """Every village: one registry query, then BatchGetItem (100 keys a call), never one GetItem per
        village. 1,000 villages are 1 + 10 calls."""
        keys = [(f"VILLAGE#{i}", "META") for i in self.village_ids()]
        items = self._batch_get(keys)
        villages = [_model(Village, items[k]) for k in keys if k in items]
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

    # -- observed rain (services/rain_obs.py) -----------------------------
    def put_rain_reading(self, r: RainReading, ttl_days: int | None = None) -> bool:
        """Store one rain reading; False when this device already has one at that second, or the same
        (device, boot, seq) is already stored (a re-sent or replayed reading)."""
        expires = _expiry(ttl_days)
        pk = f"VILLAGE#{r.village_id}"
        if r.seq is not None:
            try:
                self._put({"pk": pk, "sk": f"RAINSEQ#{r.device_id}#{r.boot or 0}#{r.seq}", "ttl": expires},
                          condition=Attr("pk").not_exists())
            except ConflictError:
                return False
        try:
            self._put({"pk": pk, "sk": f"RAIN#{r.at}#{r.device_id}", "kind": "rain", "ttl": expires, **r.model_dump()},
                      condition=Attr("pk").not_exists())
        except ConflictError:
            return False
        return True

    def list_rain_readings(self, village_id: str, since: str, limit: int = 2000) -> list[RainReading]:
        """Rain readings at or after `since`, oldest first (every device of the village)."""
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("pk").eq(f"VILLAGE#{village_id}")
            & Key("sk").between(f"RAIN#{clock.iso(clock.parse(since))}", "RAIN#~"),
            "ScanIndexForward": True,
        }
        items: list[dict] = []
        while len(items) < limit:
            page = self.t.query(**kwargs)
            items.extend(page.get("Items", []))
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        return [_model(RainReading, i) for i in items[:limit]]

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

    def count_live_reports(self, village_id: str) -> int:
        """Reports of a village that are not a replay's and not yet expired; Select=COUNT, no bodies read."""
        now = int(clock.now().timestamp())
        flt = (Attr("replay").not_exists() | Attr("replay").eq(False)) & (Attr("ttl").not_exists() | Attr("ttl").gt(now))
        return self._count(f"VILLAGE#{village_id}", "REPORT#", "REPORT#~", flt)

    def redact_reports(self, village_id: str, needles: list[str], replacement: str = "[removed]") -> int:
        """Erasure (services/privacy.py): every report of the village whose words, transcript or masked copy
        holds one of `needles` (a phone number, a chat id) gets it replaced. The report itself, its state and
        its time stay: they are the authority's record. Returns how many reports changed."""
        needles = [n for n in needles if n and len(n) >= 6]
        if not needles:
            return 0
        changed = 0
        for item in self._query(f"VILLAGE#{village_id}", "REPORT#"):
            fields: dict[str, Any] = {}
            for key in ("text", "transcript", "masked_text", "summary_en", "reporter_name"):
                value = item.get(key)
                if not isinstance(value, str) or not value:
                    continue
                new = value
                for n in needles:
                    new = new.replace(n, replacement)
                if new != value:
                    fields[key] = new
            if fields:
                self._update(str(item["pk"]), str(item["sk"]), fields)
                changed += 1
        return changed

    def bump_rate(self, scope: str, key: str, window: str, ttl_seconds: int = 86400) -> int:
        """Add one to a fixed-window counter and return the new count (services/report_guard.py).
        One atomic ADD per call: two Lambdas never both read the old count."""
        item = self._update(f"RATE#{scope}#{key}", window, {"ttl": int(clock.now().timestamp()) + ttl_seconds},
                            add={"n": 1})
        return int(item.get("n", 0))

    # -- recipients ------------------------------------------------------
    def put_recipient(self, r: Recipient) -> None:
        self._put({"pk": f"VILLAGE#{r.village_id}", "sk": f"RECIPIENT#{r.id}", **r.model_dump()})
        if r.takes_telegram:
            # Where this chat is registered, so /stop (and erasure) finds every village in one query.
            self._put({"pk": f"CHATVILLAGE#{r.id}", "sk": r.village_id})

    def chat_villages(self, chat_id: str) -> list[str]:
        """The villages a Telegram chat is registered in, from its pointer rows and, for a registration made
        before the pointers existed, from the village registry (one BatchGetItem per 100 villages)."""
        found = {str(i["sk"]) for i in self._query(f"CHATVILLAGE#{chat_id}")}
        keys = [(f"VILLAGE#{v}", f"RECIPIENT#{chat_id}") for v in self.village_ids()]
        found |= {pk.removeprefix("VILLAGE#") for pk, _ in self._batch_get(keys, consistent=True)}
        return sorted(found)

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
        self.t.delete_item(Key={"pk": f"CHATVILLAGE#{recipient_id}", "sk": village_id})
        return bool(old.get("Attributes"))

    # -- consent and erasure (services/privacy.py) -------------------------
    def put_consent_wait(self, chat_id: str, village_id: str, ttl_seconds: int = 86400) -> None:
        """A /start shown the notice, waiting for the consent button. Holds the village only: the person is
        not stored until they agree, and this row expires in a day if they never do."""
        expires = int(clock.now().timestamp()) + ttl_seconds
        self._put({"pk": f"CONSENT#{chat_id}", "sk": "META", "village_id": village_id, "expires": expires,
                   "ttl": expires})

    def consume_consent_wait(self, chat_id: str, village_id: str) -> bool:
        """True once for the village the notice was shown for; the row is deleted."""
        try:
            old = self.t.delete_item(Key={"pk": f"CONSENT#{chat_id}", "sk": "META"}, ReturnValues="ALL_OLD",
                                     ConditionExpression=Attr("village_id").eq(village_id)).get("Attributes")
        except ClientError:
            return False
        return bool(old) and int(old.get("expires", 0)) >= clock.now().timestamp()

    def drop_consent_wait(self, chat_id: str) -> None:
        self.t.delete_item(Key={"pk": f"CONSENT#{chat_id}", "sk": "META"})

    def put_erasure(self, recipient_id: str, villages: list[str], due: str, reason: str,
                    needles: list[str] | None = None) -> None:
        """Schedule the erasure of what is left of a person once their last village link went (a /stop,
        a removal). `needles` are the strings to scrub from reports (the phone number, the chat id); the row
        holds them until it runs, and is deleted when it has run."""
        self._put({"pk": "ERASURE", "sk": f"{due}#{recipient_id}", "recipient_id": recipient_id,
                   "villages": sorted(set(villages)), "reason": reason, "needles": list(needles or []),
                   "due": due})

    def due_erasures(self, now_iso: str) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"KeyConditionExpression": Key("pk").eq("ERASURE") & Key("sk").lte(f"{now_iso}#~")}
        items: list[dict] = []
        while True:
            page = self.t.query(**kwargs)
            items.extend(page.get("Items", []))
            if "LastEvaluatedKey" not in page:
                return [_from_dynamo(i) for i in items]
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def list_erasures(self) -> list[dict[str, Any]]:
        return [_from_dynamo(i) for i in self._query("ERASURE")]

    def delete_erasure(self, sk: str) -> None:
        self.t.delete_item(Key={"pk": "ERASURE", "sk": sk})

    def erase_alert_person(self, alert_id: str, recipient_id: str, pseudonym: str) -> int:
        """Re-key one person's rows of one alert (both delivery channels and the counter markers) under a
        pseudonym, without their name, chat id, number or call ids. Status, channel, attempts and times stay:
        the minimal record of who-was-reached-when the authority keeps. Counters do not move. Returns rows moved."""
        pk = f"ALERT#{alert_id}"
        moved = 0
        olds = [f"DELIVERY#{delivery_key(recipient_id, ch)}" for ch in ("", "voice")] + \
            [f"PERSON#{kind}#{recipient_id}" for kind in ("reached", "acked")]
        found = self._batch_get([(pk, sk) for sk in olds], consistent=True)
        for (_, sk), item in found.items():
            new = {k: v for k, v in item.items() if k not in {"name", "call_ids", "digit", "error", "all_clear_call_id"}}
            if sk.startswith("DELIVERY#"):
                channel = str(item.get("channel") or "")
                new.update(sk=f"DELIVERY#{delivery_key(pseudonym, channel)}", recipient_id=pseudonym,
                           name="(erased)", erased=True)
            else:
                new.update(sk=sk.rsplit("#", 1)[0] + f"#{pseudonym}")
            self.t.put_item(Item=new)
            self.t.delete_item(Key={"pk": pk, "sk": sk})
            moved += 1
        return moved

    def delete_rollcall_person(self, rollcall_id: str, recipient_id: str) -> None:
        for sk in (f"ASKED#{recipient_id}", f"RESP#{recipient_id}"):
            self.t.delete_item(Key={"pk": f"ROLLCALL#{rollcall_id}", "sk": sk})

    def delete_chat_rows(self, chat_id: str) -> None:
        """Rows keyed by a chat id alone: the help-note wait, the consent wait, the village pointers."""
        for pk, sk in [(f"HELPNOTE#{chat_id}", "META"), (f"CONSENT#{chat_id}", "META")] + \
                [(f"CHATVILLAGE#{chat_id}", str(i["sk"])) for i in self._query(f"CHATVILLAGE#{chat_id}")]:
            self.t.delete_item(Key={"pk": pk, "sk": sk})

    # -- staff scope and district settings (services/scope.py) -----------
    def put_staff_scope(self, username: str, districts: list[str]) -> None:
        self._put({"pk": f"OFFICER#{username}", "sk": "SCOPE", "districts": sorted(set(districts))})

    def get_staff_scope(self, username: str) -> list[str]:
        item = self._get(f"OFFICER#{username}", "SCOPE")
        return [str(d) for d in (item or {}).get("districts", [])]

    def get_district_settings(self, district: str) -> dict[str, Any]:
        item = self._get(f"DISTRICT#{district}", "SETTINGS")
        return {k: v for k, v in _from_dynamo(item).items() if k not in _KEY_FIELDS} if item else {}

    def put_district_settings(self, district: str, fields: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in _from_dynamo(self._update(f"DISTRICT#{district}", "SETTINGS", fields)).items()
                if k not in _KEY_FIELDS}

    # -- the public counters (api/views.py), written by the sweep --------
    def put_summary(self, name: str, body: dict[str, Any], at: str) -> None:
        self._put({"pk": "SUMMARY", "sk": name, "at": at, "body": json.dumps(body, separators=(",", ":"))})

    def get_summary(self, name: str) -> tuple[str, dict[str, Any]] | None:
        item = self._get("SUMMARY", name)
        return (str(item["at"]), json.loads(str(item["body"]))) if item else None

    # -- a send-rate budget shared by every process (delivery/ratelimit.py) --
    def take_rate_slots(self, name: str, window: int, limit: int, n: int = 1, ttl_seconds: int = 120) -> bool:
        """Take n slots of a fixed window's budget: one conditional ADD, so two Lambdas never both take the
        last slot. False (nothing taken) when the window has fewer than n left."""
        try:
            self._update(f"RATEBUCKET#{name}", f"W#{window}", {"ttl": int(clock.now().timestamp()) + ttl_seconds},
                         add={"n": n}, condition=Attr("n").not_exists() | Attr("n").lte(limit - n))
            return True
        except ConflictError:
            return False

    def get_rate_pause(self, name: str) -> float:
        item = self._get(f"RATEBUCKET#{name}", "PAUSE")
        return float(item.get("until", 0)) if item else 0.0

    def set_rate_pause(self, name: str, until: float) -> None:
        """The far side said 429: every process waits until `until` (epoch seconds). Only ever extended."""
        try:
            self._update(f"RATEBUCKET#{name}", "PAUSE", {"until": Decimal(str(round(until, 3))),
                                                         "ttl": int(until) + 3600},
                         condition=Attr("until").not_exists() | Attr("until").lt(Decimal(str(round(until, 3)))))
        except ConflictError:
            pass

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
        if not a.district:
            v = self.get_village(a.village_id)
            if v is not None:
                a = a.model_copy(update={"district": v.district})
        item: dict[str, Any] = {"pk": f"ALERT#{a.id}", "sk": "META", **a.model_dump(),
                                "gsi2pk": f"ALERTS#{a.status}", "gsi2sk": f"{a.created_at}#{a.id}"}
        if a.status in OPEN_ALERT_STATUSES:
            item.update(gsi1pk="OPEN#ALERT", gsi1sk=a.created_at)
        self._put(item, condition=Attr("pk").not_exists())
        self._put({"pk": "ALERTLOG", "sk": f"{a.created_at}#{a.id}", "alert_id": a.id, "village_id": a.village_id,
                   "replay": a.replay})
        self._put({"pk": f"VILLAGE#{a.village_id}", "sk": f"ALERTREF#{a.created_at}#{a.id}", "alert_id": a.id,
                   "replay": a.replay})

    def index_alert(self, alert_id: str) -> bool:
        """Migration (scripts/seed.py): give an alert written before the status index its index keys,
        district and village pointer. Idempotent; False when it already had them or is gone."""
        item = self._get(f"ALERT#{alert_id}", "META")
        if not item or item.get("gsi2pk"):
            return False
        a = _model(Alert, item)
        district = a.district or ((self.get_village(a.village_id) or Village(id="", name="", name_hi="", district="",
                                                                              lat=0, lon=0)).district)
        self._update(f"ALERT#{a.id}", "META", {"gsi2pk": f"ALERTS#{a.status}", "gsi2sk": f"{a.created_at}#{a.id}",
                                               "district": district})
        self._put({"pk": f"VILLAGE#{a.village_id}", "sk": f"ALERTREF#{a.created_at}#{a.id}", "alert_id": a.id,
                   "replay": a.replay})
        return True

    def all_alert_ids(self) -> list[str]:
        return [str(i["alert_id"]) for i in self._query("ALERTLOG")]

    def get_alert(self, alert_id: str) -> Alert | None:
        item = self._get(f"ALERT#{alert_id}", "META")
        return _model(Alert, item) if item else None

    def update_alert(self, alert_id: str, *, condition: Any = None, **fields: Any) -> Alert:
        remove = [k for k, v in fields.items() if v is None]
        sets = {k: (v.model_dump() if isinstance(v, BaseModel) else v) for k, v in fields.items() if v is not None}
        sets["updated_at"] = clock.iso(clock.now())
        status = fields.get("status")
        if status is not None:
            sets["gsi2pk"] = f"ALERTS#{status}"  # the status index follows the status (gsi2sk never changes)
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

    def _alerts_by_id(self, ids: list[str]) -> list[Alert]:
        """The alerts, in the order of ids, by BatchGetItem (never one GetItem per alert)."""
        items = self._batch_get([(f"ALERT#{i}", "META") for i in ids])
        return [_model(Alert, items[(f"ALERT#{i}", "META")]) for i in ids if (f"ALERT#{i}", "META") in items]

    def _alerts_with_status(self, status: str, district: str | None, limit: int) -> list[Alert]:
        """Newest first from the status index (gsi2): every alert with that status, however old."""
        kwargs: dict[str, Any] = {"IndexName": "gsi2", "KeyConditionExpression": Key("gsi2pk").eq(f"ALERTS#{status}"),
                                  "ScanIndexForward": False}
        if district:
            kwargs["FilterExpression"] = Attr("district").eq(district)
        out: list[Alert] = []
        while len(out) < limit:
            page = self.t.query(**kwargs)
            out += [_model(Alert, i) for i in page.get("Items", [])]
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        return out[:limit]

    def list_alerts(self, *, status: str | None = None, village_id: str | None = None, district: str | None = None,
                    limit: int = 100) -> list[Alert]:
        """Newest first. village_id: that village's own history (VILLAGE#id ALERTREF#). status (one, or several
        comma separated) with or without district: the status index, so an old pending alert is never missed.
        Neither: the newest `limit` of the alert log."""
        wanted = [s for s in (status or "").split(",") if s]
        if village_id:
            alerts: list[Alert] = []
            kwargs: dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(f"VILLAGE#{village_id}")
                                      & Key("sk").begins_with("ALERTREF#"), "ScanIndexForward": False}
            while len(alerts) < limit:
                page = self.t.query(**kwargs, Limit=max(limit, 25))
                batch = self._alerts_by_id([str(r["alert_id"]) for r in page.get("Items", [])])
                alerts += [a for a in batch if (not wanted or a.status in wanted)
                           and (not district or a.district == district)]
                if "LastEvaluatedKey" not in page:
                    break
                kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
            return alerts[:limit]
        if wanted:
            merged = [a for s in wanted for a in self._alerts_with_status(s, district, limit)]
            return sorted(merged, key=lambda a: (a.created_at, a.id), reverse=True)[:limit]
        if district:
            out: list[Alert] = []
            kwargs = {"KeyConditionExpression": Key("pk").eq("ALERTLOG"), "ScanIndexForward": False}
            while len(out) < limit:
                page = self.t.query(**kwargs, Limit=max(limit, 100))
                out += [a for a in self._alerts_by_id([str(r["alert_id"]) for r in page.get("Items", [])])
                        if a.district == district]
                if "LastEvaluatedKey" not in page:
                    break
                kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
            return out[:limit]
        refs = self._query("ALERTLOG", newest_first=True, limit=limit)
        return self._alerts_by_id([str(r["alert_id"]) for r in refs])

    # -- counters in people (delivery/dispatch.py) ------------------------
    # The counters, and which person marker each counts: delivered_count every PERSON#reached# marker,
    # phones_reached_count those of them reached on a real phone (phone=True), acknowledged_count PERSON#acked#.
    COUNTER_FIELDS = {"reached": "delivered_count", "acked": "acknowledged_count", "phone": "phones_reached_count"}

    def mark_person(self, alert_id: str, recipient_id: str, kind: str, *, phone: bool = False) -> bool:
        """Count one person once. First the marker PERSON#<kind>#<recipient>, created only if absent (one
        conditional put: of any number of concurrent taps, retried webhooks or workers, exactly one wins);
        then, for the winner only, one atomic ADD on the alert's counter(s): kind "reached" adds to
        delivered_count, and to phones_reached_count too when phone (a real phone, not the demo stub).
        Two table writes per person, whatever the size of the alert. The markers are the truth and the
        counters their running totals: a crash between the two leaves a counter one short until
        dispatch.repair_counts sets it to the number of markers. True when this call counted the person."""
        try:
            self._put({"pk": f"ALERT#{alert_id}", "sk": f"PERSON#{kind}#{recipient_id}",
                       "at": clock.iso(clock.now()), "phone": bool(phone)}, condition=Attr("pk").not_exists())
        except ConflictError:
            return False
        add = {self.COUNTER_FIELDS[kind]: 1}
        if kind == "reached" and phone:
            add["phones_reached_count"] = 1
        try:
            self._update(f"ALERT#{alert_id}", "META", {}, add=add, condition=Attr("pk").exists())
        except ConflictError:
            return False  # no such alert: the stray marker counts nothing
        return True

    def list_markers(self, alert_id: str, kind: str) -> set[str]:
        """Recipients with a marker of this kind; "phone": the reached markers made for a real phone."""
        prefix = "reached" if kind == "phone" else kind
        return {str(i["sk"]).split("#", 2)[2] for i in self._query(f"ALERT#{alert_id}", f"PERSON#{prefix}#")
                if kind != "phone" or i.get("phone")}

    def put_marker(self, alert_id: str, recipient_id: str, kind: str, *, phone: bool = False) -> bool:
        """Repair only (dispatch.repair_counts): the marker without the counter. A reached marker made for a
        stub that the rows now show reached a phone is set to phone. False when nothing changed."""
        sk = f"PERSON#{'reached' if kind == 'phone' else kind}#{recipient_id}"
        try:
            self._put({"pk": f"ALERT#{alert_id}", "sk": sk, "at": clock.iso(clock.now()), "repaired": True,
                       "phone": bool(phone or kind == "phone")}, condition=Attr("pk").not_exists())
            return True
        except ConflictError:
            if kind != "phone":
                return False
        try:
            self._update(f"ALERT#{alert_id}", sk, {"phone": True}, condition=Attr("phone").ne(True))
            return True
        except ConflictError:
            return False

    def set_counts_if_unchanged(self, alert_id: str, seen: dict[str, int], new: dict[str, int]) -> Alert | None:
        """Set the counters to `new` only if they still hold `seen`: a repair never overwrites an ADD that
        landed after it read them. None when one moved (the caller reads again)."""
        cond = Attr("pk").exists()
        for field_name, value in seen.items():
            same = Attr(field_name).eq(value) if value else (Attr(field_name).not_exists() | Attr(field_name).eq(0))
            cond = cond & same
        try:
            return _model(Alert, self._update(f"ALERT#{alert_id}", "META", dict(new), condition=cond))
        except ConflictError:
            return None

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
        # gsi1 OPEN#ROLLCALL by closing time: the overview finds every open roll-call in one query.
        self._put({"pk": f"ROLLCALL#{rc.id}", "sk": "META", "ttl": ttl, **rc.model_dump(),
                   "gsi1pk": "OPEN#ROLLCALL", "gsi1sk": rc.closes_at},
                  condition=Attr("pk").not_exists())
        self._put({"pk": f"VILLAGE#{rc.village_id}", "sk": f"ROLLCALL#{rc.opened_at}#{rc.id}", "rollcall_id": rc.id,
                   "ttl": ttl})

    def get_rollcall(self, rollcall_id: str) -> RollCall | None:
        item = self._get(f"ROLLCALL#{rollcall_id}", "META")
        return _model(RollCall, item) if item else None

    def update_rollcall(self, rollcall_id: str, *, condition: Any = None, **fields: Any) -> RollCall:
        cond = Attr("pk").exists() if condition is None else (Attr("pk").exists() & condition)
        return _model(RollCall, self._update(f"ROLLCALL#{rollcall_id}", "META", fields, condition=cond))

    def open_rollcalls(self, now_iso: str) -> list[RollCall]:
        """Roll-calls that close after now, every village, one index query."""
        return [_model(RollCall, i) for i in self._gsi("OPEN#ROLLCALL", sk_after=now_iso)]

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

    # -- devices: the alarm layer (services/devices, services/sirens.py) --
    def put_device(self, d: Device) -> None:
        # The item's "kind" is the device kind (siren, box ...): Device has a field of that name.
        self._put({"pk": f"VILLAGE#{d.village_id}", "sk": f"DEVICE#{d.device_id}", **d.model_dump()})
        # A small registry partition, so listing every device is one query, not a table scan.
        self._put({"pk": "DEVICES", "sk": d.device_id, "village_id": d.village_id, "device_kind": d.kind})

    def get_device(self, device_id: str) -> Device | None:
        ref = self._get("DEVICES", device_id)
        if not ref:
            return None
        item = self._get(f"VILLAGE#{ref['village_id']}", f"DEVICE#{device_id}")
        return _device(item) if item else None

    def list_devices(self, village_id: str | None = None) -> list[Device]:
        if village_id is not None:
            items = self._query(f"VILLAGE#{village_id}", "DEVICE#")
            return [_device(i) for i in items]
        refs = self._query("DEVICES")
        by_village: dict[str, list[str]] = {}
        for r in refs:
            by_village.setdefault(str(r["village_id"]), []).append(str(r["sk"]))
        out = []
        for vid in sorted(by_village):
            out += [d for d in self.list_devices(vid) if d.device_id in by_village[vid]]
        return out

    def update_device(self, village_id: str, device_id: str, *, condition: Any = None, **fields: Any) -> Device:
        remove = [k for k, v in fields.items() if v is None]
        sets = {k: (v.model_dump() if isinstance(v, BaseModel) else v) for k, v in fields.items() if v is not None}
        cond = Attr("pk").exists() if condition is None else (Attr("pk").exists() & condition)
        return _device(self._update(f"VILLAGE#{village_id}", f"DEVICE#{device_id}", sets, remove=remove,
                                           condition=cond))

    def claim_device_seq(self, device_id: str, boot: int, seq: int, ttl_days: int = 14) -> bool:
        """Idempotency for device events: True the first time (device, boot, seq) is seen."""
        try:
            self._put({"pk": f"DEVICE#{device_id}", "sk": f"DEVSEQ#{boot}#{seq}",
                       "ttl": int(clock.now().timestamp()) + ttl_days * 86400}, condition=Attr("pk").not_exists())
            return True
        except ConflictError:
            return False

    def put_device_event(self, device_id: str, at: str, boot: int, seq: int, body: dict[str, Any],
                         ttl_days: int = 90) -> None:
        self._put({"pk": f"DEVICE#{device_id}", "sk": f"EVT#{at}#{boot}#{seq}", "kind": "device_event",
                   "ttl": int(clock.now().timestamp()) + ttl_days * 86400,
                   "body": json.dumps(body, separators=(",", ":"), ensure_ascii=False)[:8000]})

    def list_device_events(self, device_id: str, since: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"ScanIndexForward": False, "Limit": max(1, min(limit, 500))}
        cond = Key("pk").eq(f"DEVICE#{device_id}")
        cond = cond & (Key("sk").between(f"EVT#{since}", "EVT#~") if since else Key("sk").begins_with("EVT#"))
        page = self.t.query(KeyConditionExpression=cond, **kwargs)
        now = int(clock.now().timestamp())
        return [json.loads(str(i["body"])) for i in page.get("Items", []) if not _expired(i, now)]

    def put_device_test(self, device_id: str, at: str, body: dict[str, Any], ttl_days: int = 400) -> None:
        self._put({"pk": f"DEVICE#{device_id}", "sk": f"TEST#{at}", "kind": "device_test",
                   "ttl": int(clock.now().timestamp()) + ttl_days * 86400, **body})

    def next_device_ctr(self, device_id: str) -> int:
        """The next command counter for a device, shared by the shadow, LoRa and SMS paths (atomic ADD)."""
        return int(self._update(f"DEVICE#{device_id}", "CTR", {}, add={"n": 1}).get("n", 0))

    def put_command(self, c: SirenCommand, ttl_days: int = 400) -> None:
        self._put({"pk": f"DEVICE#{c.device_id}", "sk": f"CMD#{c.id}", "kind": "siren_command",
                   "ttl": int(clock.now().timestamp()) + ttl_days * 86400, **c.model_dump()},
                  condition=Attr("pk").not_exists())

    def get_command(self, device_id: str, cmd_id: str) -> SirenCommand | None:
        item = self._get(f"DEVICE#{device_id}", f"CMD#{cmd_id}")
        return _model(SirenCommand, item) if item else None

    def list_commands(self, device_id: str, limit: int = 50) -> list[SirenCommand]:
        items = self._query(f"DEVICE#{device_id}", "CMD#", newest_first=True, limit=limit)
        return [_model(SirenCommand, i) for i in items]

    def update_command(self, device_id: str, cmd_id: str, *, condition: Any = None, **fields: Any) -> SirenCommand:
        cond = Attr("pk").exists() if condition is None else (Attr("pk").exists() & condition)
        sets = {k: v for k, v in fields.items() if v is not None}
        return _model(SirenCommand, self._update(f"DEVICE#{device_id}", f"CMD#{cmd_id}", sets, condition=cond))

    def put_siren_row(self, row: SirenDelivery) -> bool:
        """The siren tier row of an alert; False when (alert, device, round) is already there (idempotent)."""
        try:
            self._put({"pk": f"ALERT#{row.alert_id}", "sk": f"SIREN#{row.device_id}#{row.round:02d}",
                       "kind": "siren_row", **row.model_dump()}, condition=Attr("pk").not_exists())
            return True
        except ConflictError:
            return False

    def list_siren_rows(self, alert_id: str) -> list[SirenDelivery]:
        return [_model(SirenDelivery, i) for i in self._query(f"ALERT#{alert_id}", "SIREN#")]

    def update_siren_row(self, alert_id: str, device_id: str, round_no: int, *, condition: Any = None,
                         **fields: Any) -> SirenDelivery:
        cond = Attr("pk").exists() if condition is None else (Attr("pk").exists() & condition)
        sets = {k: v for k, v in fields.items() if v is not None}
        return _model(SirenDelivery, self._update(f"ALERT#{alert_id}", f"SIREN#{device_id}#{round_no:02d}", sets,
                                                  condition=cond))

    def put_siren_request(self, r: SirenRequest, ttl_days: int = 1) -> None:
        self._put({"pk": f"SIRENREQ#{r.id}", "sk": "META", "kind": "siren_request",
                   "ttl": int(clock.now().timestamp()) + ttl_days * 86400, **r.model_dump()},
                  condition=Attr("pk").not_exists())
        self._put({"pk": f"VILLAGE#{r.village_id}", "sk": f"SIRENREQ#{r.requested_at}#{r.id}", "request_id": r.id,
                   "ttl": int(clock.now().timestamp()) + ttl_days * 86400})

    def get_siren_request(self, request_id: str) -> SirenRequest | None:
        item = self._get(f"SIRENREQ#{request_id}", "META")
        return _model(SirenRequest, item) if item and not _expired(item) else None

    def list_siren_requests(self, village_id: str, limit: int = 10) -> list[SirenRequest]:
        refs = self._query(f"VILLAGE#{village_id}", "SIRENREQ#", newest_first=True, limit=limit)
        return [r for r in (self.get_siren_request(str(i["request_id"])) for i in refs) if r is not None]

    def update_siren_request(self, request_id: str, *, condition: Any = None, **fields: Any) -> SirenRequest:
        cond = Attr("pk").exists() if condition is None else (Attr("pk").exists() & condition)
        return _model(SirenRequest, self._update(f"SIRENREQ#{request_id}", "META", fields, condition=cond))

    def claim_siren_rate(self, village_id: str, slot: str, key: str, ttl_seconds: int = 7200) -> bool:
        """True the first time this key (an alert, a request) sounds the village's sirens in this hour."""
        try:
            self._put({"pk": f"SIRENRATE#{village_id}", "sk": f"{slot}#{key}",
                       "ttl": int(clock.now().timestamp()) + ttl_seconds}, condition=Attr("pk").not_exists())
            return True
        except ConflictError:
            return False

    def add_alert_counts(self, alert_id: str, **counts: int) -> Alert:
        """Atomic ADD of the alert's siren counters (two events at once never lose one)."""
        return _model(Alert, self._update(f"ALERT#{alert_id}", "META", {"updated_at": clock.iso(clock.now())},
                                          add=counts, condition=Attr("pk").exists()))

    def put_local_shadow(self, device_id: str, name: str, desired: dict[str, Any]) -> int:
        """Local mode only: the desired document a device would read from its named shadow."""
        item = self._update(f"DEVICE#{device_id}", f"SHADOW#{name}",
                            {"desired": json.dumps(desired, separators=(",", ":"))}, add={"version": 1})
        return int(item.get("version", 0))

    def get_local_shadow(self, device_id: str, name: str) -> dict[str, Any] | None:
        item = self._get(f"DEVICE#{device_id}", f"SHADOW#{name}")
        return {"desired": json.loads(str(item["desired"])), "version": int(item.get("version", 0))} if item else None

    # -- the duty officer (services/duty.py) and inbound calls (delivery/inbound.py) --
    def put_handover(self, h: HandoverNote, ttl_days: int = ROSTER_TTL_DAYS) -> None:
        self._put({"pk": f"HANDOVER#{h.district}", "sk": f"{h.date}#{h.shift}", **h.model_dump(),
                   "ttl": int(clock.now().timestamp()) + ttl_days * 86400})

    def get_handover(self, district: str, date: str, shift: str) -> HandoverNote | None:
        item = self._get(f"HANDOVER#{district}", f"{date}#{shift}")
        return _model(HandoverNote, item) if item else None

    def list_handovers(self, district: str, first_date: str, last_date: str) -> list[HandoverNote]:
        kwargs: dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(f"HANDOVER#{district}")
                                  & Key("sk").between(f"{first_date}#", f"{last_date}#~")}
        items: list[dict] = []
        while True:
            page = self.t.query(**kwargs)
            items.extend(page.get("Items", []))
            if "LastEvaluatedKey" not in page:
                return [_model(HandoverNote, i) for i in items]
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def acknowledge_handover(self, district: str, date: str, shift: str, by: str, at: str) -> HandoverNote:
        """Once: a second acknowledgement is a ConflictError."""
        return _model(HandoverNote, self._update(f"HANDOVER#{district}", f"{date}#{shift}",
                                                 {"acknowledged_by": by, "acknowledged_at": at},
                                                 condition=Attr("pk").exists() & Attr("acknowledged_by").not_exists()))

    def claim_once(self, name: str, key: str, ttl_seconds: int = 3 * 86400) -> bool:
        """True for the first caller only (a conditional put): a job that must run once per key."""
        try:
            self._put({"pk": f"ONCE#{name}", "sk": key, "at": clock.iso(clock.now()),
                       "ttl": int(clock.now().timestamp()) + ttl_seconds}, condition=Attr("pk").not_exists())
            return True
        except ConflictError:
            return False

    def put_inbound(self, call_id: str, fields: dict[str, Any], ttl_seconds: int = 2 * 3600) -> None:
        self._put({"pk": f"INBOUND#{call_id}", "sk": "META", **fields,
                   "ttl": int(clock.now().timestamp()) + ttl_seconds})

    def get_inbound(self, call_id: str) -> dict[str, Any] | None:
        item = self._get(f"INBOUND#{call_id}", "META")
        if not item or _expired(item):
            return None
        return {k: v for k, v in _from_dynamo(item).items() if k not in _KEY_FIELDS}

    def delete_inbound(self, call_id: str) -> None:
        self.t.delete_item(Key={"pk": f"INBOUND#{call_id}", "sk": "META"})

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

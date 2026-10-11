"""Web Push: approval alerts on an officer's phone, even with the console closed
(services/officer_push.py). The public key is public; everything under /me needs a sign-in
and the Cedar action subscribe_push, and touches only the caller's own subscriptions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from Pukaar.api.auth import Allowed
from Pukaar.delivery.webpush import PushError
from Pukaar.policy.guard import Principal
from Pukaar.services import officer_push
from Pukaar.store.repo import get_repo

router = APIRouter()


@router.get("/push/vapid-public-key")
def vapid_public_key() -> dict:
    """The applicationServerKey browsers subscribe with. null when Web Push is not set up yet."""
    key = officer_push.public_key()
    return {"key": key, "configured": key is not None}


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class SubscriptionBody(BaseModel):
    """PushSubscription.toJSON() from the browser."""

    endpoint: str = Field(max_length=1024)
    keys: SubscriptionKeys
    expirationTime: float | None = None


@router.get("/me/push-subscriptions")
def list_subscriptions(principal: Principal = Depends(Allowed("subscribe_push"))) -> list[dict]:
    return [officer_push.view(s) for s in get_repo().list_push_subscriptions(principal.username)]


@router.post("/me/push-subscriptions")
def add_subscription(body: SubscriptionBody, request: Request,
                     principal: Principal = Depends(Allowed("subscribe_push"))) -> dict:
    if officer_push.public_key() is None:
        raise HTTPException(503, {"code": "push_off", "reason": "Web Push is not set up on this server yet."})
    try:
        sub = officer_push.subscribe(get_repo(), principal.username, body.endpoint, body.keys.p256dh, body.keys.auth,
                                     request.headers.get("user-agent", ""))
    except PushError as exc:
        raise HTTPException(400, {"code": "bad_subscription", "reason": str(exc)}) from exc
    return officer_push.view(sub)


@router.delete("/me/push-subscriptions/{sub_id}")
def remove_subscription(sub_id: str, principal: Principal = Depends(Allowed("subscribe_push"))) -> dict:
    if not get_repo().delete_push_subscription(principal.username, sub_id[:64]):
        raise HTTPException(404, "Subscription not found")
    return {"ok": True, "id": sub_id}


@router.post("/me/push-test")
def push_test(principal: Principal = Depends(Allowed("subscribe_push"))) -> dict:
    repo = get_repo()
    if not repo.list_push_subscriptions(principal.username):
        raise HTTPException(404, {"code": "no_subscription", "reason": "Turn on approval alerts on this phone first."})
    if not repo.claim_push_test(principal.username, officer_push.TEST_INTERVAL_SECONDS):
        raise HTTPException(429, {"code": "rate_limited",
                                  "reason": "One test notification a minute. Try again in a moment.",
                                  "message_hi": "एक मिनट में एक जाँच सूचना। थोड़ी देर में फिर कोशिश करें।"})
    r = officer_push.send_test(repo, principal.username)
    return {"sent": r.sent, "failed": r.failed, "removed": r.removed}

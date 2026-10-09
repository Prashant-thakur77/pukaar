"""Who is calling.

AWS mode: API Gateway's Cognito JWT authorizer has already checked the token;
the Lambda Web Adapter passes the request context (with the claims) in the
x-amzn-request-context header. Local mode: short-lived HS256 dev tokens from
POST /auth/dev-login for the seeded demo users.
"""

from __future__ import annotations

import json
import time

import jwt
from fastapi import Depends, HTTPException, Request

from Pukaar.core.config import get_settings
from Pukaar.core.secrets import get_secret
from Pukaar.policy.guard import Principal, authorize
from Pukaar.store.repo import get_repo

DEV_USERS = {
    "officer1": ("officer", []),
    "officer2": ("officer", []),
    "pradhan_thunag": ("pradhan", ["thunag"]),
}


def dev_token(username: str) -> str:
    role, villages = DEV_USERS[username]
    key = get_secret("link_secret", generate_locally=True) or ""
    return jwt.encode({"sub": username, "role": role, "village_ids": villages, "exp": int(time.time()) + 12 * 3600},
                      key, algorithm="HS256")


def _from_claims(claims: dict) -> Principal | None:
    groups = claims.get("cognito:groups") or []
    if isinstance(groups, str):
        groups = [g.strip() for g in groups.strip("[]").replace(",", " ").split() if g.strip()]
    role = "officer" if "officer" in groups else ("pradhan" if "pradhan" in groups else None)
    if role is None:
        return None
    villages = [v.strip() for v in str(claims.get("custom:village_ids", "")).split(",") if v.strip()]
    return Principal(str(claims.get("cognito:username") or claims.get("username") or claims.get("sub")), role, villages)


def current_principal(request: Request) -> Principal | None:
    s = get_settings()
    if s.is_local:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return None
        try:
            data = jwt.decode(header[7:], get_secret("link_secret", generate_locally=True) or "", algorithms=["HS256"])
        except jwt.PyJWTError:
            return None
        return Principal(data["sub"], data["role"], list(data.get("village_ids", [])))
    raw = request.headers.get("x-amzn-request-context")
    if not raw:
        return None
    try:
        claims = json.loads(raw)["authorizer"]["jwt"]["claims"]
    except (ValueError, KeyError, TypeError):
        return None
    return _from_claims(claims)


def require_user(request: Request) -> Principal:
    p = current_principal(request)
    if p is None:
        raise HTTPException(status_code=401, detail="Sign in required.")
    return p


class Allowed:
    """Dependency factory: authorize(action) against a resource taken from the path."""

    def __init__(self, action: str, resource_type: str = "app", path_param: str | None = None) -> None:
        self.action, self.resource_type, self.path_param = action, resource_type, path_param

    def __call__(self, request: Request, principal: Principal = Depends(require_user)) -> Principal:
        rid = request.path_params.get(self.path_param, "pukaar") if self.path_param else "pukaar"
        village = request.query_params.get("village_id", "")
        decision = authorize(principal, self.action, self.resource_type, rid, {"village_id": village}, repo=get_repo())
        if not decision.allowed:
            raise HTTPException(status_code=403, detail={"code": "denied", "reason": decision.reason,
                                                         "action": self.action, "role": principal.role})
        return principal

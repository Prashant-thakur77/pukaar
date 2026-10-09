"""Who is calling.

AWS mode: the API verifies the Cognito ID token itself (signature against the
pool's JWKS, issuer, audience = app client, token_use = id). API Gateway's JWT
authorizer checks it too on protected routes, but public routes have no
authorizer, so no request header is trusted on its own. Local mode:
short-lived HS256 dev tokens from POST /auth/dev-login for the demo users.
"""

from __future__ import annotations

import time
from functools import lru_cache

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


@lru_cache(maxsize=1)
def _jwks() -> jwt.PyJWKClient:
    s = get_settings()
    return jwt.PyJWKClient(f"https://cognito-idp.{s.aws_region}.amazonaws.com/{s.cognito_user_pool_id}/.well-known/jwks.json",
                           cache_keys=True, lifespan=3600)


def verify_cognito(token: str) -> dict | None:
    s = get_settings()
    if not (s.cognito_user_pool_id and s.cognito_client_id):
        return None
    try:
        key = _jwks().get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=s.cognito_client_id,
                            issuer=f"https://cognito-idp.{s.aws_region}.amazonaws.com/{s.cognito_user_pool_id}")
    except jwt.PyJWTError:
        return None
    return claims if claims.get("token_use") == "id" else None


def current_principal(request: Request) -> Principal | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    token = header[7:].strip()
    if get_settings().is_local:
        try:
            data = jwt.decode(token, get_secret("link_secret", generate_locally=True) or "", algorithms=["HS256"])
        except jwt.PyJWTError:
            return None
        return Principal(data["sub"], data["role"], list(data.get("village_ids", [])))
    claims = verify_cognito(token)
    return _from_claims(claims) if claims else None


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

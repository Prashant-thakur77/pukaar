"""Who is calling.

AWS mode: the API verifies the Cognito ID token itself (signature against the
pool's JWKS, issuer, audience = app client, token_use = id). API Gateway's JWT
authorizer checks it too on protected routes, but public routes have no
authorizer, so no request header is trusted on its own. Local mode:
short-lived HS256 dev tokens from POST /auth/dev-login for the demo users.
"""

from __future__ import annotations

import time
from dataclasses import replace
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, Request

from Pukaar.core.config import get_settings
from Pukaar.core.secrets import get_secret
from Pukaar.policy.guard import Decision, Principal, authorize, evaluate
from Pukaar.store.repo import get_repo

DEV_USERS = {
    "officer1": ("officer", []),
    "officer2": ("officer", []),
    "pradhan_thunag": ("pradhan", ["thunag"]),
    "pradhan_pandoh": ("pradhan", ["pandoh"]),  # Raahat demo: Pandoh is the village the satellite pair covers
    # The public demo accounts, as on the live stack: Cedar holds them to replay alerts only.
    "judge": ("officer", []),
    "judge_pradhan": ("pradhan", ["thunag"]),
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


def resource_facts(repo, resource_type: str, resource_id: str) -> dict:
    """Policy context read from the record itself (never from the request): whether an alert or
    report is a replay's, its village, and an alert's level. Anything unreadable is left out, so
    context.replay stays false and the stricter rule applies."""
    try:
        if resource_type == "alert":
            a = repo.get_alert(resource_id)
            return {"replay": a.replay, "level": a.level, "village_id": a.village_id} if a else {}
        if resource_type == "report":
            r = repo.get_report(resource_id)
            return {"replay": r.replay, "village_id": r.village_id} if r else {}
    except Exception:
        return {}
    return {}


class Allowed:
    """Dependency factory: authorize(action) against a resource taken from the path.

    village_from_path: the policy's context.village_id is the path's village id, not the
    query string, so a pradhan cannot point a write at another village.

    A pradhan's request that names no village (a list) is asked once for each of their own
    villages: no Cedar policy matches an empty village (policy/base.cedar), and the route
    filters the list to those villages.

    replay_reads: for read routes that list villagers' data. When Cedar refuses the live read
    but allows the same read of replay records (a public demo account), the request goes on
    with principal.replay_only set and the route serves replay records only.
    """

    def __init__(self, action: str, resource_type: str = "app", path_param: str | None = None,
                 village_from_path: bool = False, replay_reads: bool = False) -> None:
        self.action, self.resource_type, self.path_param = action, resource_type, path_param
        self.village_from_path = village_from_path
        self.replay_reads = replay_reads

    def _decide(self, principal: Principal, rid: str, context: dict, repo) -> tuple[Decision, bool]:
        """(the audited decision, whether it holds for replay records only). One audit row."""
        if self.replay_reads and context.get("replay") is not True:
            live = evaluate(principal, self.action, self.resource_type, rid, context)
            if not live.allowed:
                as_replay = {**context, "replay": True}
                if evaluate(principal, self.action, self.resource_type, rid, as_replay).allowed:
                    return authorize(principal, self.action, self.resource_type, rid, as_replay, repo=repo), True
        return authorize(principal, self.action, self.resource_type, rid, context, repo=repo), False

    def __call__(self, request: Request, principal: Principal = Depends(require_user)) -> Principal:
        rid = request.path_params.get(self.path_param, "pukaar") if self.path_param else "pukaar"
        if self.village_from_path:
            village = str(request.path_params.get(self.path_param or "village_id", ""))
        else:
            village = request.query_params.get("village_id", "")
        repo = get_repo()
        context = {"village_id": village, **resource_facts(repo, self.resource_type, rid)}
        own = [v for v in principal.village_ids if v] if principal.role == "pradhan" else []
        if principal.role == "pradhan" and not context.get("village_id") and own:
            results = [self._decide(principal, rid, {**context, "village_id": v}, repo) for v in own]
            allowed = [r for r in results if r[0].allowed]
            decision, replay_only = (allowed[0][0], any(r[1] for r in allowed)) if allowed else results[0]
        else:
            decision, replay_only = self._decide(principal, rid, context, repo)
        if not decision.allowed:
            raise HTTPException(status_code=403, detail={"code": "denied", "reason": decision.reason,
                                                         "action": self.action, "role": principal.role})
        return replace(principal, replay_only=replay_only) if replay_only else principal

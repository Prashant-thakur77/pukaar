"""Prod behind CloudFront and AWS WAF: the API answers only requests that came through CloudFront.

AWS WAF cannot be attached to an API Gateway HTTP API (only to REST APIs, CloudFront, ALB, AppSync,
Cognito and a few others). So on prod with an edge web ACL (template condition HasApiEdge, docs/DEPLOY.md
"AWS WAF on prod") a CloudFront distribution with the WAF sits in front of the HTTP API and adds the
origin-verify header X-Pukaar-Edge, whose value is the SSM parameter /pukaar/edge_origin_secret.
With PUKAAR_EDGE_REQUIRED=true this middleware refuses every request without it (403), so the WAF's
rate limits cannot be gone round by calling the execute-api URL directly. /health is exempt: the Lambda
Web Adapter's readiness check calls it inside the function, not through API Gateway.

The caller's IP is then CloudFront's CloudFront-Viewer-Address (services/report_guard.client_ip), never
the CloudFront edge address API Gateway sees.
"""

from __future__ import annotations

import hmac

from Pukaar.core.config import get_settings

HEADER = "x-pukaar-edge"
SECRET_NAME = "edge_origin_secret"
EXEMPT_PATHS = frozenset({"/health"})


def required() -> bool:
    return get_settings().edge_required


def verified(headers) -> bool:
    """True when the request carries CloudFront's origin-verify header. Fails closed without the secret."""
    from Pukaar.core.secrets import get_secret

    sent = headers.get(HEADER) or ""
    secret = get_secret(SECRET_NAME) or ""
    return bool(secret) and hmac.compare_digest(sent.encode(), secret.encode())


def allowed(path: str, headers) -> bool:
    return not required() or path in EXEMPT_PATHS or verified(headers)


def viewer_ip(headers) -> str | None:
    """The viewer's IP as CloudFront saw it: CloudFront-Viewer-Address ("ip:port"), else the X-Forwarded-For
    entry CloudFront appended (API Gateway appends CloudFront's own address after it)."""
    addr = (headers.get("cloudfront-viewer-address") or "").strip()
    if addr:
        return addr.rsplit(":", 1)[0].strip("[]") or None
    hops = [h.strip() for h in (headers.get("x-forwarded-for") or "").split(",") if h.strip()]
    return hops[-2] if len(hops) >= 2 else None

"""The live jury demo's presenter screen (/console/demo; services/demo.py, docs/DEMO_LIVE.md).

    GET  /demo          the session: join code and link (only for someone who may run it), people joined, and the
                        demo alert's delivered / confirmed counts and times. Counts only, never a name or chat id.
    POST /demo/open     open the session, or rotate its join code (the old one stops working at once)
    POST /demo/alert    start the one labelled practice alert (then approve it with hold-to-approve)
    POST /demo/reset    erase every demo person and demo alert now

Cedar: view_demo (officers and state operators; the public demo accounts too, to watch) and run_demo (officers and
state operators, never the public demo accounts).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from Pukaar.api.auth import Allowed
from Pukaar.policy.guard import Principal, evaluate
from Pukaar.services import demo
from Pukaar.store.repo import get_repo
from Pukaar.workflow.client import get_workflow

router = APIRouter()


def _refused(exc: demo.DemoError) -> HTTPException:
    headers = {"Retry-After": str(exc.extra["retry_after"])} if "retry_after" in exc.extra else None
    return HTTPException(exc.status, exc.detail(), headers=headers)


@router.get("/demo")
def demo_status(principal: Principal = Depends(Allowed("view_demo"))) -> dict:
    repo = get_repo()
    can_run = evaluate(principal, "run_demo", "app", "demo", {}, repo=repo).allowed
    return {**demo.status(repo, show_code=can_run), "can_run": can_run}


@router.post("/demo/open")
def demo_open(principal: Principal = Depends(Allowed("run_demo"))) -> dict:
    repo = get_repo()
    try:
        demo.open_session(repo, principal.username, principal.role)
    except demo.DemoError as exc:
        raise _refused(exc) from None
    return {**demo.status(repo, show_code=True), "can_run": True}


@router.post("/demo/alert")
def demo_alert(principal: Principal = Depends(Allowed("run_demo"))) -> dict:
    repo = get_repo()
    try:
        demo.start_alert(repo, get_workflow(), principal.username, principal.role)
    except demo.DemoError as exc:
        raise _refused(exc) from None
    return {**demo.status(repo, show_code=True), "can_run": True}


@router.post("/demo/reset")
def demo_reset(principal: Principal = Depends(Allowed("run_demo"))) -> dict:
    repo = get_repo()
    erased = demo.reset(repo, principal.username, principal.role)
    return {**demo.status(repo, show_code=True), "can_run": True, "erased": erased}

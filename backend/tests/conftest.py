from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

BACKEND_SRC = Path(__file__).resolve().parents[1] / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

# Offline, deterministic settings for every test.
os.environ.update({
    "PUKAAR_MODE": "local",
    "PUKAAR_LLM_ENABLED": "false",
    "PUKAAR_LINK_SECRET": "test-link-secret-at-least-32-bytes-long",
    "PUKAAR_TABLE_NAME": "pukaar-test",
    "PUKAAR_BUCKET": "pukaar-test-bucket",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_DEFAULT_REGION": "us-east-1",
})
for var in ("PUKAAR_TELEGRAM_TOKEN", "PUKAAR_TELEGRAM_WEBHOOK_SECRET"):
    os.environ.pop(var, None)

NOW = datetime(2026, 7, 1, 2, 0, tzinfo=timezone.utc)


@pytest.fixture()
def repo():
    """A fresh moto table and bucket, seeded with the real village file."""
    from moto import mock_aws

    with mock_aws():
        import boto3

        from Pukaar.core.config import get_settings
        from Pukaar.scripts.seed import seed
        from Pukaar.services import action_guard, storage
        from Pukaar.store.repo import Repo, get_repo, table_schema

        import uuid

        get_repo.cache_clear()
        storage._s3.cache_clear()
        s = get_settings()
        # A unique table per test: the API tests' app may already hold a mock open.
        name = f"pukaar-test-{uuid.uuid4().hex[:8]}"
        boto3.client("dynamodb", region_name=s.aws_region).create_table(**table_schema(name))
        try:
            boto3.client("s3", region_name=s.aws_region).create_bucket(Bucket=s.bucket)
        except Exception:
            pass  # already exists in a shared mock
        r = Repo(boto3.resource("dynamodb", region_name=s.aws_region).Table(name))
        seed(r)
        action_guard.reset()
        yield r
        get_repo.cache_clear()
        storage._s3.cache_clear()


@pytest.fixture()
def frozen():
    from Pukaar.core import clock

    state = {"now": NOW}
    clock.set_clock(lambda: state["now"])
    yield state
    clock.set_clock(None)


class FakeWorkflow:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.successes: list[tuple[str, dict]] = []
        self.reject = False

    def start(self, alert):
        self.started.append(alert.id)
        return f"arn:fake:{alert.id}"

    def send_success(self, token, output):
        if self.reject:
            raise RuntimeError("TaskTimedOut")
        self.successes.append((token, output))


@pytest.fixture()
def workflow():
    return FakeWorkflow()

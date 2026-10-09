"""Create the Cognito demo users (idempotent).

    officer1, officer2   group officer, all villages
    pradhan_thunag       group pradhan, Thunag only

Passwords come from the environment, never from this file:
    PUKAAR_DEMO_PASSWORD        permanent password for all three (required)
    PUKAAR_DEMO_TEMP_PASSWORD   temporary password used at creation (optional; random if unset)
Stack outputs are read from CloudFormation (stack PUKAAR_STACK, default pukaar-dev).
Village ids come from data/villages.json, or PUKAAR_DEMO_VILLAGE_IDS (comma separated).
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
REGION = (
    os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
)
STACK = os.environ.get("PUKAAR_STACK", "pukaar-dev")


def stack_output(name: str) -> str:
    stack = boto3.client("cloudformation", region_name=REGION).describe_stacks(
        StackName=STACK
    )
    outputs = {o["OutputKey"]: o["OutputValue"] for o in stack["Stacks"][0]["Outputs"]}
    return outputs[name]


def village_ids() -> tuple[list[str], str]:
    """All village ids, and the id of Thunag."""
    if os.environ.get("PUKAAR_DEMO_VILLAGE_IDS"):
        ids = [
            v.strip()
            for v in os.environ["PUKAAR_DEMO_VILLAGE_IDS"].split(",")
            if v.strip()
        ]
        return ids, next((i for i in ids if "thunag" in i.lower()), ids[0])
    path = ROOT / "data" / "villages.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    villages = data["villages"] if isinstance(data, dict) else data
    ids = [str(v["id"]) for v in villages]
    thunag = next(
        str(v["id"]) for v in villages if str(v.get("name", "")).lower() == "thunag"
    )
    return ids, thunag


def ensure_user(
    cognito,
    pool_id: str,
    username: str,
    group: str,
    villages: list[str],
    temp_password: str,
    password: str,
) -> None:
    attributes = [{"Name": "custom:village_ids", "Value": ",".join(villages)}]
    try:
        cognito.admin_create_user(
            UserPoolId=pool_id,
            Username=username,
            TemporaryPassword=temp_password,
            UserAttributes=attributes,
            MessageAction="SUPPRESS",
        )
        print(f"created {username}")
    except cognito.exceptions.UsernameExistsException:
        cognito.admin_update_user_attributes(
            UserPoolId=pool_id, Username=username, UserAttributes=attributes
        )
        print(f"updated {username}")
    # Skip the FORCE_CHANGE_PASSWORD challenge so the demo can sign in directly.
    cognito.admin_set_user_password(
        UserPoolId=pool_id, Username=username, Password=password, Permanent=True
    )
    cognito.admin_add_user_to_group(
        UserPoolId=pool_id, Username=username, GroupName=group
    )


def main() -> int:
    password = os.environ.get("PUKAAR_DEMO_PASSWORD")
    if not password:
        print(
            "Set PUKAAR_DEMO_PASSWORD (12+ chars, upper, lower, digit).",
            file=sys.stderr,
        )
        return 2
    temp_password = (
        os.environ.get("PUKAAR_DEMO_TEMP_PASSWORD")
        or f"Tmp-{secrets.token_urlsafe(16)}1a"
    )

    pool_id = stack_output("UserPoolId")
    ids, thunag = village_ids()
    cognito = boto3.client("cognito-idp", region_name=REGION)
    for username, group, villages in (
        ("officer1", "officer", ids),
        ("officer2", "officer", ids),
        ("pradhan_thunag", "pradhan", [thunag]),
    ):
        ensure_user(
            cognito, pool_id, username, group, villages, temp_password, password
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

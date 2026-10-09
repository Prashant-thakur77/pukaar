"""One tiny Bedrock call with the configured model; on failure, list the Nova
models this account can see so the right id can go into PUKAAR_BEDROCK_MODEL_ID.

    python -m Pukaar.scripts.smoke_bedrock
"""

from __future__ import annotations

import sys

import boto3

from Pukaar.core.config import get_settings


def main() -> int:
    s = get_settings()
    runtime = boto3.client("bedrock-runtime", region_name=s.aws_region)
    try:
        resp = runtime.converse(modelId=s.bedrock_model_id,
                                messages=[{"role": "user", "content": [{"text": "Reply with OK."}]}],
                                inferenceConfig={"maxTokens": 5, "temperature": 0})
        text = resp["output"]["message"]["content"][0]["text"]
        print(f"OK {s.bedrock_model_id} in {s.aws_region}: {text!r} usage={resp.get('usage')}")
        return 0
    except Exception as exc:
        print(f"FAILED {s.bedrock_model_id}: {type(exc).__name__}: {exc}")
    try:
        models = boto3.client("bedrock", region_name=s.aws_region).list_foundation_models(byProvider="amazon")
        nova = [m["modelId"] for m in models["modelSummaries"] if "nova" in m["modelId"]]
        print("Nova models visible in this region:", ", ".join(nova) or "none")
        print("Enable model access in the Bedrock console, then set PUKAAR_BEDROCK_MODEL_ID (SAM parameter BedrockModelId).")
    except Exception as exc:
        print(f"could not list models: {type(exc).__name__}: {exc}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

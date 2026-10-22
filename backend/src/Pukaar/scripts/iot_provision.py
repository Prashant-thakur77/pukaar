"""Provision a village's river gauge on AWS IoT Core: one thing, one certificate, one policy.

    python -m Pukaar.scripts.iot_provision gohar            # via `make gauge-provision VILLAGE=gohar`
    python -m Pukaar.scripts.iot_provision gohar --delete   # tear it all down again

For the village's registered gauge device (its gauge.device_id on the deployed stack, or
--device), this:

1. creates an IoT thing named after the device id (the IoT policy pins the MQTT client id and
   the publish topic to the thing name, so thing name == device id is what authenticates it);
2. creates an RSA key pair and an ACTIVE certificate (the private key exists only in this
   process's memory and in SSM; it is never printed or written to disk);
3. attaches the stack's gauge policy (output GaugePolicyName) to the certificate and the
   certificate to the thing;
4. stores the private key and the certificate PEM as SSM SecureString parameters
   /pukaar/gauge/<device>/key and /pukaar/gauge/<device>/cert;
5. prints the ATS data endpoint and the two topics the device publishes to: .../reading for
   live readings and .../backfill for readings it buffered while offline.

Idempotent: a thing that already has a certificate and both parameters is left alone. A
failure after the certificate was created rolls it back, so a re-run starts clean.

The alarm layer's devices (`make device-provision KIND=siren VILLAGE=thunag`): --kind siren, box or relay
uses that kind's policy (stack outputs SirenPolicyName, BoxPolicyName, RelayPolicyName), the parameters
/pukaar/<kind>/<device>/key and /cert, and the device id <kind>-<village>-sim unless --device names one.
For a labelled simulator ("-sim") it also derives the device's signing key from the SSM root
/pukaar/device_root (HKDF; services/devices/keys.py) and stores it as /pukaar/<kind>/<device>/hmac, which
scripts/siren_sim_mqtt.py reads to verify its commands. A real device's key is never stored server side:
it goes into the device's encrypted NVS at provisioning (slice M; docs/hardware/ALARM.md).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any

# The stage's stack and region: `make gauge-provision STAGE=prod` exports both (Makefile).
REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
STACK = os.environ.get("PUKAAR_STACK", "pukaar-dev")
SSM_PREFIX = "/pukaar/gauge"
KINDS = ("gauge", "siren", "box", "relay")
POLICY_OUTPUT = {"gauge": "GaugePolicyName", "siren": "SirenPolicyName", "box": "BoxPolicyName",
                 "relay": "RelayPolicyName"}
TOPICS = {"gauge": ("reading", "backfill"), "siren": ("event", "heartbeat", "backfill"),
          "box": ("event", "heartbeat", "backfill"), "relay": ()}


def param_names(device_id: str, kind: str = "gauge") -> tuple[str, str]:
    prefix = SSM_PREFIX if kind == "gauge" else f"/pukaar/{kind}"
    return f"{prefix}/{device_id}/key", f"{prefix}/{device_id}/cert"


def hmac_param(device_id: str, kind: str) -> str:
    return f"/pukaar/{kind}/{device_id}/hmac"


def topic(village: str, device_id: str, kind: str = "reading") -> str:
    """The topics the IoT policy lets this device publish to (kind: reading or backfill)."""
    if kind not in ("reading", "backfill"):
        raise ValueError(kind)
    return f"pukaar/gauge/{village}/{device_id}/{kind}"


def stack_output(cfn: Any, stack: str, key: str) -> str | None:
    outs = cfn.describe_stacks(StackName=stack)["Stacks"][0].get("Outputs", [])
    return next((o["OutputValue"] for o in outs if o["OutputKey"] == key), None)


def ats_endpoint(iot: Any) -> str:
    return iot.describe_endpoint(endpointType="iot:Data-ATS")["endpointAddress"]


def village_device(village: str) -> str:
    """The deployed village's registered gauge device id (the ingest checks against it)."""
    from Pukaar.scripts import gauge_sim

    base = gauge_sim.stack_api_url()
    status, detail = gauge_sim._request(f"{base.rstrip('/')}/villages/{village}")
    cfg = (detail.get("gauge") or {}).get("config") if status == 200 else None
    if not cfg:
        raise SystemExit(f"{village}: no gauge configured on the deployed stack (GET -> {status}); re-run `make seed`?")
    return cfg["device_id"]


def _thing_principals(iot: Any, thing: str) -> list[str] | None:
    try:
        return iot.list_thing_principals(thingName=thing)["principals"]
    except iot.exceptions.ResourceNotFoundException:
        return None


def _params_exist(ssm: Any, device_id: str, kind: str = "gauge") -> bool:
    # Without WithDecryption: only checks the parameters are there, never reads the key.
    found = ssm.get_parameters(Names=list(param_names(device_id, kind)))["Parameters"]
    return len(found) == 2


def _put_secure(ssm: Any, name: str, value: str, description: str) -> None:
    # boto3 sends the value in the request body: it never reaches a command line or a file.
    ssm.put_parameter(Name=name, Value=value, Type="SecureString", Overwrite=True, Description=description)


def _remove_cert(iot: Any, thing: str | None, cert_arn: str) -> None:
    cert_id = cert_arn.rsplit("/", 1)[-1]
    if thing:
        try:
            iot.detach_thing_principal(thingName=thing, principal=cert_arn)
        except iot.exceptions.ResourceNotFoundException:
            pass
    for pol in iot.list_attached_policies(target=cert_arn).get("policies", []):
        iot.detach_policy(policyName=pol["policyName"], target=cert_arn)
    iot.update_certificate(certificateId=cert_id, newStatus="INACTIVE")
    for attempt in range(10):  # detaching a thing principal is eventually consistent
        try:
            iot.delete_certificate(certificateId=cert_id)
            return
        except iot.exceptions.DeleteConflictException:
            time.sleep(1 + attempt)
    raise SystemExit(f"certificate {cert_id} is still attached; delete it in the IoT console")


def provision(iot: Any, ssm: Any, village: str, device_id: str, policy: str, kind: str = "gauge") -> str:
    key_name, cert_name = param_names(device_id, kind)
    principals = _thing_principals(iot, device_id)
    if principals:
        if _params_exist(ssm, device_id, kind):
            print(f"{device_id}: thing, certificate and SSM parameters already exist; nothing to do")
            return "exists"
        raise SystemExit(f"{device_id} has a certificate but its key is not in SSM ({key_name}). The key cannot "
                         "be recovered: run with --delete, then provision again.")
    if principals is None:
        iot.create_thing(thingName=device_id, attributePayload={
            "attributes": {"village": village, "kind": kind, "simulated": str(device_id.endswith("-sim")).lower()}})
        print(f"created thing {device_id}")

    created = iot.create_keys_and_certificate(setAsActive=True)
    cert_arn = created["certificateArn"]
    try:
        iot.attach_policy(policyName=policy, target=cert_arn)
        iot.attach_thing_principal(thingName=device_id, principal=cert_arn)
        _put_secure(ssm, key_name, created["keyPair"]["PrivateKey"], f"Private key of {kind} {device_id} (AWS IoT)")
        _put_secure(ssm, cert_name, created["certificatePem"], f"Certificate of {kind} {device_id} (AWS IoT)")
    except BaseException:
        print("provisioning failed; removing the new certificate so a re-run starts clean", file=sys.stderr)
        _remove_cert(iot, device_id, cert_arn)
        raise
    print(f"created certificate {created['certificateId'][:12]}... (ACTIVE), attached policy {policy}")
    print(f"stored {key_name} and {cert_name} (SecureString)")
    return "created"


def store_sim_key(ssm: Any, device_id: str, kind: str, kid: int = 1) -> bool:
    """A "-sim" device only: its HKDF signing key, derived from /pukaar/device_root, for the simulator.
    Never printed. A real device's key is never stored server side."""
    if not device_id.endswith("-sim"):
        return False
    from Pukaar.services.devices import protocol

    raw = ssm.get_parameter(Name="/pukaar/device_root", WithDecryption=True)["Parameter"]["Value"].strip()
    try:
        root = bytes.fromhex(raw)
    except ValueError:
        root = raw.encode("utf-8")
    key = protocol.derive_device_key(root, device_id, kid)
    _put_secure(ssm, hmac_param(device_id, kind), key.hex(), f"Signing key of the SIMULATED {kind} {device_id}")
    return True


def teardown(iot: Any, ssm: Any, device_id: str, kind: str = "gauge") -> None:
    principals = _thing_principals(iot, device_id)
    for arn in principals or []:
        _remove_cert(iot, device_id, arn)
        print(f"deleted certificate {arn.rsplit('/', 1)[-1][:12]}...")
    if principals is not None:
        iot.delete_thing(thingName=device_id)
        print(f"deleted thing {device_id}")
    for name in (*param_names(device_id, kind), *([hmac_param(device_id, kind)] if kind != "gauge" else [])):
        try:
            ssm.delete_parameter(Name=name)
            print(f"deleted {name}")
        except ssm.exceptions.ParameterNotFound:
            pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("village", nargs="?", default="gohar")
    p.add_argument("--kind", choices=KINDS, default="gauge", help="gauge (default), siren, box or relay")
    p.add_argument("--device", help="device id (default: the village's gauge.device_id on the deployed stack, "
                                    "or <kind>-<village>-sim)")
    p.add_argument("--policy", help="IoT policy name (default: the stack output GaugePolicyName)")
    p.add_argument("--stack", default=STACK)
    p.add_argument("--region", default=REGION)
    p.add_argument("--delete", action="store_true", help="detach and delete the certificate, thing and parameters")
    args = p.parse_args(argv)

    import boto3

    iot = boto3.client("iot", region_name=args.region)
    ssm = boto3.client("ssm", region_name=args.region)
    kind = args.kind
    device_id = args.device or (village_device(args.village) if kind == "gauge" else f"{kind}-{args.village}-sim")

    if args.delete:
        teardown(iot, ssm, device_id, kind)
        return 0

    output = POLICY_OUTPUT[kind]
    policy = args.policy or stack_output(boto3.client("cloudformation", region_name=args.region), args.stack, output)
    if not policy:
        print(f"Stack {args.stack} has no {output} output: deploy the stack first (`make deploy`).", file=sys.stderr)
        return 1
    provision(iot, ssm, args.village, device_id, policy, kind)
    if kind != "gauge" and store_sim_key(ssm, device_id, kind):
        print(f"stored {hmac_param(device_id, kind)} (SecureString; the simulator's signing key, never printed)")
    print(f"endpoint  {ats_endpoint(iot)}:8883 (MQTT over TLS; ALPN x-amzn-mqtt-ca on 443 also works)")
    print(f"client id {device_id}")
    for sub in TOPICS[kind]:
        print(f"topic     pukaar/{kind}/{args.village}/{device_id}/{sub}")
    if kind != "gauge":
        print(f"shadow    $aws/things/{device_id}/shadow/name/siren (desired.cmd: the signed command)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

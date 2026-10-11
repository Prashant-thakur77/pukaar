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
5. prints the ATS data endpoint and the topic the device publishes to.

Idempotent: a thing that already has a certificate and both parameters is left alone. A
failure after the certificate was created rolls it back, so a re-run starts clean.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

REGION = "us-east-1"
STACK = "pukaar-dev"
SSM_PREFIX = "/pukaar/gauge"


def param_names(device_id: str) -> tuple[str, str]:
    return f"{SSM_PREFIX}/{device_id}/key", f"{SSM_PREFIX}/{device_id}/cert"


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


def _params_exist(ssm: Any, device_id: str) -> bool:
    # Without WithDecryption: only checks the parameters are there, never reads the key.
    found = ssm.get_parameters(Names=list(param_names(device_id)))["Parameters"]
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


def provision(iot: Any, ssm: Any, village: str, device_id: str, policy: str) -> str:
    key_name, cert_name = param_names(device_id)
    principals = _thing_principals(iot, device_id)
    if principals:
        if _params_exist(ssm, device_id):
            print(f"{device_id}: thing, certificate and SSM parameters already exist; nothing to do")
            return "exists"
        raise SystemExit(f"{device_id} has a certificate but its key is not in SSM ({key_name}). The key cannot "
                         "be recovered: run with --delete, then provision again.")
    if principals is None:
        iot.create_thing(thingName=device_id, attributePayload={
            "attributes": {"village": village, "simulated": str(device_id.endswith("-sim")).lower()}})
        print(f"created thing {device_id}")

    created = iot.create_keys_and_certificate(setAsActive=True)
    cert_arn = created["certificateArn"]
    try:
        iot.attach_policy(policyName=policy, target=cert_arn)
        iot.attach_thing_principal(thingName=device_id, principal=cert_arn)
        _put_secure(ssm, key_name, created["keyPair"]["PrivateKey"], f"Private key of gauge {device_id} (AWS IoT)")
        _put_secure(ssm, cert_name, created["certificatePem"], f"Certificate of gauge {device_id} (AWS IoT)")
    except BaseException:
        print("provisioning failed; removing the new certificate so a re-run starts clean", file=sys.stderr)
        _remove_cert(iot, device_id, cert_arn)
        raise
    print(f"created certificate {created['certificateId'][:12]}... (ACTIVE), attached policy {policy}")
    print(f"stored {key_name} and {cert_name} (SecureString)")
    return "created"


def teardown(iot: Any, ssm: Any, device_id: str) -> None:
    principals = _thing_principals(iot, device_id)
    for arn in principals or []:
        _remove_cert(iot, device_id, arn)
        print(f"deleted certificate {arn.rsplit('/', 1)[-1][:12]}...")
    if principals is not None:
        iot.delete_thing(thingName=device_id)
        print(f"deleted thing {device_id}")
    for name in param_names(device_id):
        try:
            ssm.delete_parameter(Name=name)
            print(f"deleted {name}")
        except ssm.exceptions.ParameterNotFound:
            pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("village", nargs="?", default="gohar")
    p.add_argument("--device", help="device id (default: the village's gauge.device_id on the deployed stack)")
    p.add_argument("--policy", help="IoT policy name (default: the stack output GaugePolicyName)")
    p.add_argument("--stack", default=STACK)
    p.add_argument("--region", default=REGION)
    p.add_argument("--delete", action="store_true", help="detach and delete the certificate, thing and parameters")
    args = p.parse_args(argv)

    import boto3

    iot = boto3.client("iot", region_name=args.region)
    ssm = boto3.client("ssm", region_name=args.region)
    device_id = args.device or village_device(args.village)

    if args.delete:
        teardown(iot, ssm, device_id)
        return 0

    policy = args.policy or stack_output(boto3.client("cloudformation", region_name=args.region), args.stack,
                                         "GaugePolicyName")
    if not policy:
        print(f"Stack {args.stack} has no GaugePolicyName output: deploy the stack first (`make deploy`).",
              file=sys.stderr)
        return 1
    provision(iot, ssm, args.village, device_id, policy)
    print(f"endpoint  {ats_endpoint(iot)}:8883 (MQTT over TLS; ALPN x-amzn-mqtt-ca on 443 also works)")
    print(f"client id {device_id}")
    print(f"topic     pukaar/gauge/{args.village}/{device_id}/reading")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

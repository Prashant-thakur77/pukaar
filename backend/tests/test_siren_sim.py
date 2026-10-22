"""The terminal siren simulator (scripts/siren_sim_mqtt.py): what it reports for a signed test command."""
import time

import pytest

from Pukaar.scripts.siren_sim_mqtt import Node
from Pukaar.services.devices import protocol

DEVICE = "siren-thunag-sim"
KEY = bytes(range(32))  # TEST ONLY


def command(cid, volume, ctr=1):
    now = int(time.time())
    cmd = {name: 0 for name in protocol.CMD_INT_FIELDS}
    cmd.update(id=cid, action="test", pattern="T1", volume=volume, iat=now, exp=now + 600, ctr=ctr,
               src="officer_manual", kid=1)
    cmd["sig"] = protocol.sign_command(KEY, cmd, DEVICE)
    return cmd


def run(fault, volume, ctr=1):
    sent = []
    node = Node("thunag", DEVICE, KEY, fault, lambda topic, body: sent.append(body))
    node.command(command(f"cmd_test{ctr}", volume, ctr))
    return {e["type"]: e for e in sent}


@pytest.mark.parametrize(("fault", "volume", "ok"), [
    (None, 0, True),         # silent: into the dummy load, the current alone decides
    (None, 50, True),        # audible: current and the microphone
    ("mic_dead", 50, True),  # audible with a dead microphone: current only, as the server rule says
    ("amp_open", 0, False),  # an open amplifier fails a silent test
    ("amp_open", 50, False),
])
def test_test_result_matches_what_was_measured(fault, volume, ok):
    events = run(fault, volume)
    assert events["cmd_received"]["pattern"] == "T1"
    result = events["test_result"]
    assert result["kind"] == ("silent" if volume == 0 else "audible")
    assert result["ok"] is ok
    assert events["finished"]["cmd_id"] == "cmd_test1"


def test_a_tampered_command_is_rejected_and_never_tested():
    sent = []
    node = Node("thunag", DEVICE, KEY, None, lambda topic, body: sent.append(body))
    cmd = command("cmd_x", 0)
    cmd["volume"] = 100
    node.command(cmd)
    assert [e["type"] for e in sent] == ["rejected"]

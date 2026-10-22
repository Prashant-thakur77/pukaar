"""The alarm layer's devices: siren nodes, pradhan boxes, LoRa relays, rain nodes and the river gauges.

protocol.py      the one canonical codec and signer (shadow command, LoRa frame, signed SMS)
siren_model.py   a pure-Python reference of the device-side checks (replay, expiry, verification)
keys.py          the per-device keys (HKDF from the SSM root secret)
registry.py      the device registry and its health, in the single table
shadow.py        the named-shadow transport (AWS IoT Core, or an in-table copy in local mode)

None of this has run on hardware: the devices exist only as the labelled simulators.
"""

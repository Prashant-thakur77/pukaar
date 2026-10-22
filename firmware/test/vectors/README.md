# Golden protocol vectors

`protocol_vectors.json` is written by the backend's canonical codec
(`cd backend && python -m Pukaar.scripts.protocol_vectors`, or `make protocol-vectors`), from
`services/devices/protocol.py` and `siren_model.py`. Do not edit it by hand. Every key in it is
TEST ONLY, derived from the public root 0x00..0x1f.

`test/native/test_vectors` checks the C code against every section:

| Section | What the firmware must reproduce |
|---|---|
| `enums`, `constants` | the wire values in `schema.h`, payload sizes, limits, and the pattern defaults |
| `derivation` | each device key (HKDF-SHA256) |
| `commands` | the canonical string and the 22-character signature |
| `command_checks` | the acceptance matrix, step by step, and the exact restore after a reboot |
| `frames` | payload bytes, frame bytes and MAC, and the compact command's inner signature |
| `frame_rejects` | each refused frame's reason, in order (one frame's acceptance changes the next), and after a reboot the gauge's next frame accepted at once |
| `sms` | each SMS text, its signing string, the sequenced checks and the sender hash |
| `verification` | when a sound counts as verified |

If the file is absent, the eight tests are reported as SKIPPED with a message. Set
`PUKAAR_VECTORS=/path/file.json` to run them against another copy.

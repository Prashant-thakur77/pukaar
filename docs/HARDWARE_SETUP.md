# Hardware Setup

Full hardware bring-up lives in [`raspberry-pi-pukaar-node.md`](raspberry-pi-pukaar-node.md).

## Profiles

| Profile | Hardware | Runner |
|---|---|---|
| Pi 8GB demo | Raspberry Pi 5 8GB + Pi Camera Module 3 | `scripts/run_pukaar_pi8_multimodal_demo.sh` |
| Pi 16GB prod | Raspberry Pi 5 16GB + USB cam / RTSP | `scripts/run_pukaar_pi16_multimodal_prod.sh` |
| Workstation | x86_64, 16GB+ RAM, optional GPU | `scripts/demo.py` |
| Android | Pixel 7 / mid-range (>=6GB RAM) | `android/` Gradle build |

See also: [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md), [`PUKAAR_AI_USAGE.md`](PUKAAR_AI_USAGE.md).

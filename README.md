# dreo-local

Local control for **Dreo smart fans** that **keeps the Dreo app working.**

Flash your Dreo fan with ESPHome for full local/Home-Assistant control — and,
unlike cloud-*cutter* tools that sever the cloud, run a small **bridge** that
speaks to the Dreo cloud as your device so the **official Dreo app keeps working
too.** Have both.

> Right-to-repair tooling for hardware **you own**. It talks to Dreo's cloud using
> **your own device's** factory identity and **your own** Dreo account/app
> credentials — none of which are shipped here (see "Bring your own"). You can
> brick a fan flashing firmware; be ready for a UART recovery.

## What's here

| Path | What |
|---|---|
| `esphome/dreo-minimal.yaml` | the ESPHome build for the Wi-Fi module (local control: light/fan/speed/brightness/CCT/direction) |
| `esphome/components/flashdump/` | ESPHome button that reads the module flash over Wi-Fi (how you dump your own license region) |
| `tools/extract_license.py` + `EXTRACT-LICENSE.md` | pull your device's factory license (SN + signature) out of a flash dump, offline |
| `tools/dreo_register.py` | register your device SN with the Dreo cloud (mint MQTT creds from the signature) |
| `tools/dreo_bridge.py` | the PC cloud↔ESPHome bridge (keeps the app working) |
| `ha-integration/` | the same bridge as a Home Assistant integration (`dreo_app_bridge`) |
| `tools/ota-sim/` | a safe behavioral simulator of the stock `/ota` flash path (develop/test with no device) |
| `tools/dreo-setup.py` | profile-driven onboarding CLI with a mandatory key-backup gate |
| `profiles/` | per-device profile (flash layout, DP map, protocol) |
| `docs/` | how the bridge works; the key-read feasibility analysis |

See also the firmware emulator: **https://github.com/ahmedwalid05/dreo-firmware-emulator**

## Bring your own (not shipped — they're yours or Dreo's)

- **Dreo app client credentials** — the bridge/register use the Dreo app's client
  pair. Supply yours: `export DREO_CLIENT_ID=… DREO_CLIENT_SECRET=…` (and
  `DREO_USER_ID=…`). For the HA integration, set them in
  `ha-integration/custom_components/dreo_app_bridge/const.py`.
- **Your fan's factory license** — `license.json` from `extract_license.py`.
- **Wi-Fi secrets** — copy `esphome/secrets.yaml.example` → `esphome/secrets.yaml`.
- **Firmware images** — not distributed (vendor copyright); you dump your own.

## Quick start (sketch)

1. Flash `esphome/dreo-minimal.yaml` to the module → local control + HA.
2. Dump the license region (the `flashdump` button) and run `extract_license.py` → `license.json`.
3. `export DREO_CLIENT_ID/SECRET/USER_ID`, then `dreo_register.py` to confirm the cloud accepts it.
4. Run `dreo_bridge.py` (or the HA integration) → the Dreo app works alongside local control.

## License

MIT (see `LICENSE`). Not affiliated with Dreo. Use on your own devices.

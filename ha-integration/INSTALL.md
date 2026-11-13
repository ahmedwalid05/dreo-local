# Dreo App Bridge — Home Assistant integration

Runs the Dreo-cloud bridge INSIDE Home Assistant (no desktop process, no
supervision needed). Keeps the official Dreo app working for an
ESPHome-flashed Dreo device, exactly like `tools/dreo_bridge.py` did.

## Install (HA Container / Core — any install without add-ons)

1. On the PC running Home Assistant, copy this folder so you end up with:
   `<config>/custom_components/dreo_app_bridge/`  (the folder containing
   manifest.json — create `custom_components` if it doesn't exist)
   From this repo dir the copy is:  `custom_components/dreo_app_bridge`
2. Restart Home Assistant (container: `docker restart <ha-container>`).
3. Settings → Devices & Services → Add Integration → search **"Dreo App
   Bridge"** (first install of a custom component requires Advanced mode
   enabled in your HA profile, and may need a cache refresh — if it doesn't
   appear, wait 30s and reload the page).
4. Fill the form:
   - **Factory license JSON**: paste the contents of `MY-FAN-LICENSE-…json`
     (kept out of the component on purpose — it is your device's identity!)
   - **Fan IP**: `dreo-fan.local`
   - **userId**: prefilled
   - **Region**: EU
   It validates against the Dreo API before saving.
5. A `binary_sensor.dreo_app_bridge_connected` device appears; ON = the Dreo
   app has a live path to the fan.

Then stop the old PC bridge (it re-mints credentials and would fight):
`pkill -f dreo_bridge.py`

## Notes
- Requirements (`paho-mqtt`) install automatically on first load.
- The license JSON never leaves your HA box (config entry storage).
- Uninstall = remove the integration + delete the folder.
- All bridge semantics (ghost-absorbing desired-align publish, remembered
  speed, echo suppression) are identical to the battle-tested daemon —
  see ~/projects/dreo/research/dreo-bridge.md.

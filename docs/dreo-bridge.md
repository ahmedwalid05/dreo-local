# The Dreo Cloud ↔ ESPHome Bridge (`tools/dreo_bridge.py`) — Complete Documentation

Status: **RUNNING and working** — full Dreo app control of the fan since 2026-11-05
~23:41 (brightness/mode/muteon added 2026-11-06 ~03:10), alongside unchanged full
local control. This is the project's end goal, delivered. Current state:
**research/FINAL-STATE-2026-11-06.md**.

## 1. What it is

A small Python daemon (v2, 278 lines) that runs **on the PC** (not on the fan) and
impersonates the fan's cloud identity. It bridges two halves:

```
Dreo app ⇄ Dreo cloud (mqtts-eu.dreo-cloud.com:8883, EMQX) ⇄ dreo_bridge.py ⇄ ESPHome REST (http://dreo-fan.local)
                                                                          ⇄ (fan module, local control unchanged)
```

The fan itself keeps running plain ESPHome (`dreo-minimal.yaml`). The bridge speaks
MQTT as the device (using the fan's genuine factory license), translates cloud
desired-state into ESPHome REST calls, and reports fan state back to the cloud.

## 2. Authentication chain (per connection)

1. `POST https://device-api-eu.dreo-cloud.com/api/oauth/login` — device grant with
   your client pair (DREO_CLIENT_ID/SECRET), `devicesn` = our SN
2. `POST /api/device/activate/emq` with:
   - `signature` = **our fan's factory license signature** (recovered from the
     flash islands — `tools/our-license.json`, durable copy; script default is
     `/tmp/dreo/our_license.json`)
   - `userId` = `<YOUR_USER_ID>` (our Dreo account), `automatic: true`
   - `metaInfo` claims the real product: `HeFi` module `3.8.13`, MCU `FP6063U/EU` `3.6.4`
   - → fresh `{endPoint, port 8883, username "admin", password, certificatePem,
     privateKey, prefix "$emq"}`
3. MQTT 3.1.1 connect: TLS with `tools/hesung-root-ca.pem` (+ `VERIFY_X509_STRICT`
   cleared — broker leaf has no AKI), **client cert from the mint is mandatory**,
   `clientId` = SN, keepalive 30 s, LWT on `lwt/{sn}` reporting `connected: false`.

Each activate mints fresh creds and invalidates the previous set, so the bridge
re-registers on every (re)connect. The license signature itself is **reusable
indefinitely** — it's the durable secret; the passwords/certs are ephemeral.

## 3. Topics

| Direction | Topic | Use |
|---|---|---|
| sub | `$emq/things/{sn}/shadow/update/delta` | app commands (shadow deltas) |
| sub | `event/{sn}/desired` | app commands (event flavor) |
| sub | `data/{sn}/desired/schedule` | schedules — **subscribed but NOT handled yet** |
| sub | `ota/{sn}` | cloud OTA pushes — **subscribed but NOT handled yet** |
| pub | `$emq/things/{sn}/shadow/update` | state reports, `clientToken` `D:I:{sn}` |
| pub | `$emq/rules/iot_data_rule/{sn}` | realtime notify (feeds the app's websocket push) |
| pub | `lwt/{sn}` | last-will (offline marker) |

## 4. State translation — the cloud model (hard-won semantics)

The cloud's device model for this fan, learned live on 2026-11-05 (lighttest/
ghosttest experiments):

- **`fanon`** (bool) = power flag, **independent from `windlevel`** (the remembered
  speed). Reporting `windlevel: 0` when the fan is off causes an **infinite delta
  loop** — always report the remembered speed and zero only the power flag.
- `fanon: true` → ESPHome `Speed = remembered windlevel`; `false` → `Speed 0`.
- `windlevel` arriving while fan is off → **remember only, no actuation**.
- Keys we cannot actuate (`mode`, `muteon`, `scheid`, `scheon`, `brightness`) are
  **mirrored back** into the report so desired/reported never mismatch (the
  "revert-ghost" fix — without this the app UI snaps back ~2 s after each tap).
- **Immediate confirm**: after applying, the bridge waits 0.35 s then publishes —
  the app reverts its UI if state doesn't confirm within ~1–2 s of the tap.
- **Echo suppression**: own reports bounce back as deltas; `D:I:` clientTokens
  within 2 s of own actuation are ignored (`A:I:` = app-initiated, never suppressed).
- Per-key actuation rate-limit 1 s.

### Actuated mapping

| Cloud key | ESPHome action |
|---|---|
| `lighton` | `POST /switch/Light/turn_on\|turn_off` |
| `fanon` | `POST /select/Speed/set?option={remembered\|0}` |
| `windlevel` | `POST /select/Speed/set?option=N` (only if fan running) |
| `colortemp` | `POST /number/Color%20Temp/set?value=N` |
| `brightness` | `POST /number/Brightness/set?value=N` (dp6 — resolved 2026-11-06 from stock fw attr table) |
| `mode` | `POST /select/Direction/set?option=Forward|Reverse` (dp5; 1/4) |
| `muteon` | `POST /switch/Audio%20Feedback/turn_on|turn_off` (dp0C) |

### Reported state block

`connected, mcuon, fanon, windlevel, lighton, brightness, colortemp,
mcu_firmware_version (3.6.4), module_hardware_model (HeFi),
module_firmware_version (3.8.13), module_hardware_mac (001cc2a1f659)` + mirror keys.
State is polled from ESPHome REST every 1 s and published **only on change**, with
a `desired` alignment block to absorb any pending cloud desired state.

## 5. Resilience & recovery

- Main loop: register → connect → poll/publish forever. **Any** exception (network
  blip, MQTT drop, stale creds) tears down and re-registers after 8 s — visible
  working in `bridge.log` (`URLError … re-registering in 8s → cloud: registered OK →
  mqtt: connected`).
- MQTT reconnect backoff 1–8 s; CONNACK timeout 20 s.
- ESPHome REST timeouts 8 s; oauth/activate timeout 25 s.

## 6. Current deployment

- **Process**: `~/projects/esp32/fw-analysis/tools/venv/bin/python3 -I
  ~/projects/dreo/tools/dreo_bridge.py` (started
  2026-11-05 from a shell with `| tee /tmp/dreo/bridge.log`)
- **Runtime deps**: paho-mqtt (fw-analysis venv). TLS via `tools/hesung-root-ca.pem`
  next to the script.
- **Log**: `/tmp/dreo/bridge.log` (volatile — snapshots in
  `~/projects/dreo/tmp-dreo-snapshot-2026-11-06/`)
- **License**: durable copy at `tools/our-license.json` (2026-11-06). The script's
  `--license` default still points to `/tmp/dreo/our_license.json` — **after a
  reboot, start with `--license tools/our-license.json`**.
- Not supervised (no systemd) — dies with its parent shell/reboot. Restart command:
  `~/projects/esp32/fw-analysis/tools/venv/bin/python3 -I tools/dreo_bridge.py
  --license tools/our-license.json 2>&1 | tee -a /tmp/dreo/bridge.log`

## 7. Lineage / how we got here (test history, logs in tmp-snapshot)

| Date (2026-11) | Artifact | What it established |
|---|---|---|
| 04 late | `creds_tower_live.json`, notes §"CLOUD MQTT — CRACKED" | register + MQTT-as-device proven with tower SN |
| 05 00:37–01:08 | `native_dump.py`, `fan_tail_dump.bin`, `fan_tail_islands.bin`, `island_stream.log` | full 128 KB tail dump via ESPHome; **license found in surviving data islands** (cal@0x1E0000, NET-info@0x1E1000, license island further in — the earlier 13 KB partial dump's "all erased" read was incomplete) |
| 05 01:08 | `our_license.json`, `creds_OURFAN.json` | **our own SN's signature recovered; our fan registered** |
| 05 21:00+ | `datarule.c`, `attrdp.c`, `dptable.py` (Ghidra decompiles of the DP-table/attr-dispatch functions) | cloud key ↔ DP mapping RE |
| 05 21:53–23:52 | `lighttest{,2,3}.log`, `ghosttest.log`, `lightghost.log`, `watchnow.log`, `finaltest.log`, `verify2.log` | app-tap → delta → actuate loop; discovered the windlevel-0 delta loop and revert-ghost → v2 semantics; verified via ESPHome SSE + DP Dump sensor (`03=1 04=5 05=1 0C=0 …`) |
| 05 23:40 → now | `tools/dreo_bridge.py` v2 + `bridge.log` | stable bridge, running since ~23:41 |
| 06 00:51–01:27 | `ota{,2,3}.log` (ESPHome 2026.7.0 rebuild/uf2ota logs) | fan-side rebuilds during bridge bring-up |

## 8. Known gaps / next engineering

1. `ota/{sn}` messages ignored — if Dreo pushes an OTA to our (now-online) device,
   the bridge should ack or ignore deliberately; risk of cloud-side re-push loops.
2. `data/{sn}/desired/schedule` (timers/schedules) ignored — app-scheduled on/off
   won't actuate.
3. `brightness` not actuated (true DP unresolved) — dp5 needs a capture with the
   light dimmed from the wall remote vs app to pin down.
4. No supervision (systemd unit or ESPHome-side `dreo_cloud` component would make
   it reboot-proof; an on-device ESPHome MQTT component is the eventual clean home).
5. `--license` default path is volatile (/tmp) — pass `--license` explicitly after
   reboots or patch the default.

## 9. Security notes

- The license signature is the *only* irreplaceable secret; it's stored in three
  places now: `tools/our-license.json` (workspace), `/tmp/dreo/our_license.json`
  (volatile original), `~/projects/dreo/tmp-dreo-snapshot-2026-11-06/our_license.json`.
  Treat those files as credentials.
- The bridge holds full device-identity power: anyone with the signature can
  register as this fan and receive its commands (and shadow-write its state).
- MQTT creds it mints are short-lived and re-mintable; losing them is a non-event.

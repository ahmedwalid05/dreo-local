# Tier-1 OTA simulator — a "fake stock fan" on your PC

A software model of the Dreo BK7231N `/ota` flash path, faithful to the RE in
`research/module-firmware-report.md §3` and the RBL format in `tools/pack_rbl.py`.
Zero hardware, zero risk. Use it to develop/test the flashing toolkit and to
*prove* the Phase-0 key-extraction reasoning before touching real silicon.

## What it models

| Piece | File | Fidelity |
|---|---|---|
| 2 MB flash + real partition geometry | `flash.py` | offsets from the on-flash table (DR-HTF004S dump) |
| stock `/ota` HTTP handler | `device.py` | multipart parse (2nd `\r\n\r\n` → 1st `\r\n---`), `1023 < size ≤ 655360`, verbatim write to `ota` partition, 200 OK + WDT reboot |
| rt_ota bootloader | `bootloader.py` | validate → install-or-reject in the real gate order; reject keeps current app |
| RBL pack/validate | `rbl.py` | byte-for-byte with `tools/pack_rbl.py` (AES-256-CBC + gzip, crc32 header/data, fnv1a hash) |
| factory license in flash | `seed.py` | stand-in blob at the real offset `0x1F2000` (Usr Config) |

The `Application` partition length is trimmed to end exactly at `ota` (`0x132000`);
the real table over-declares it to `0x143000`, overlapping `ota` on paper but not
in used bytes — a vendor quirk that doesn't change the write invariants.

## Run

```bash
cd ~/projects/dreo/tools/ota-sim
PYTHONPATH=. ~/projects/dreo/fw-analysis/tools/venv/bin/python3 run_demo.py   # full proof
# or run the fake device and poke it yourself:
PYTHONPATH=. .../venv/bin/python3 device.py --port 8080    # GET http://127.0.0.1:8080/ota
```

(Use `PYTHONPATH=.`, not `-I`: `-I` drops the script dir from the path. This is
our own code, not an untrusted download, so that's fine.)

## What `run_demo.py` proves (executable assertions)

- **A — a "failing" image reads nothing.** A reader image crafted to exfiltrate
  the license, then corrupted, is **rejected** by the bootloader *before any code
  runs*. Application and the license are byte-identical; no dump is produced.
  → confirms you cannot "read via an image that fails to install": reject precedes
  execution.
- **B — reading requires a successful install, and the key is still safe.** A
  valid reader image installs, boots, and dumps the license. `Application` changes
  (stock is overwritten — the *replaceable* thing), but the license partition is
  byte-identical before and after.
- **C — full round-trip, nothing irreplaceable lost.** Re-flashing stock restores
  `Application`; the license hash is unchanged across A, B, and C.

The license `sha16` printed at the end is identical throughout — the irreplaceable
secret is never in any write path, exactly as the partition geometry predicts.

## Driving it with the real orchestrator

`tools/dreo-setup.py` is the profile-driven onboarding CLI. It talks pure HTTP,
so the same commands hit the sim or a real fan (only `--device` changes). Against
the sim it also serves the extracted license back over `GET /flashdump/<name>`,
modelling the booted reader firmware's own HTTP read endpoint:

```bash
cd ~/projects/dreo/tools/ota-sim
V=~/projects/dreo/fw-analysis/tools/venv/bin/python3
PROF=~/projects/dreo/profiles/dr-hcf001s.json
PYTHONPATH=. $V seed.py && PYTHONPATH=. $V device.py --port 8138 &   # fake fan
$V ~/projects/dreo/tools/dreo-setup.py detect     --profile $PROF --device http://127.0.0.1:8138
$V ~/projects/dreo/tools/dreo-setup.py restore    --profile $PROF --device http://127.0.0.1:8138 --image stock.rbl  # BLOCKED: no backup
$V ~/projects/dreo/tools/dreo-setup.py backup-key --profile $PROF --device http://127.0.0.1:8138 --sim             # extract+verify key
$V ~/projects/dreo/tools/dreo-setup.py restore    --profile $PROF --device http://127.0.0.1:8138 --image stock.rbl  # now ALLOWED
```

The mandatory key-backup gate (`restore`/`flash` refuse until a *verified* backup
exists in `backups/<model>/`) is the enforced form of the Phase-0 safety rule.
Full reasoning: `research/phase0-key-read.md`.

## Using it as a toolkit harness

`device.DeviceState(flash_path, outdir)` is a pure-logic device (no socket):
`handle_post(raw_request_bytes)` returns the device's view (`http`, `wrote`,
`boot`). Point your real `dreo-setup.py` upload client at `device.py` over HTTP to
test RBL packing, size limits, boundary parsing, and the read-then-restore
sequence against stock-faithful behavior. Then graduate to Tier 2 (a sacrificial
BK7231N over `bk7231tools`).

# Phase 0 — Key-read feasibility (verdict + method + proof)

**Question:** for a reusable "any Dreo device" tool, how do we read the factory
license off a *still-stock* device, over the air, with zero risk to the
irreplaceable secret — before flashing anything?

**Date:** 2026-11-06. Companion code: `tools/ota-sim/` (Tier-1 simulator),
`tools/dreo-setup.py` (orchestrator), `profiles/dr-hcf001s.json`.

---

## 1. Verdict: there is no read-only OTA path on stock firmware

Evidence (your own captures + RE):

- **Live port scan in pairing mode** (`research/fan-pairing-recon/NOTES.md`):
  nmap top-2000 + fingerprint → **only port 80 open**. No telnet/ssh/console.
- **Only route that answers is `/ota` / `/ota.html`** — a firmware *upload*
  form. Everything else 404s on the ceiling-fan build (even `/devinfoget`,
  `/wifilist` that exist on other builds).
- **License/signature reads (`getlic`/`getsig`) are UART2-console only**
  (`research/firmware-report.md` line 74) — physical pads, not networked.
- The signature leaves the device **only inside a TLS POST to Dreo's cloud**
  (`firmware-report.md` lines 34–42); the **app never asks the device for it**
  (every APK "signature" hit is framework noise).

So the only network door is a flash **write**. A purely read-only ("nothing
written") OTA extraction is **not possible** on unmodified stock.

### Corollary: a "self-rejecting reader" image cannot work

An image crafted to read the license and then deliberately fail validation reads
nothing: the bootloader's validation **precedes execution**. rt_ota validates the
staged image by CRC/hash and only *then* installs+boots it; a rejected image
never runs. Read requires execution; execution requires a successful install.
(Proven as assertion **A** below.)

---

## 2. Why the key is safe anyway — partition geometry, not luck

On-flash partition table (`research/module-firmware-report.md`, confirmed vs the
DR-HTF004S dump; same BK7231N/rt_ota family):

| # | Name | Start | End |
|---|---|---|---|
| 0 | Bootloader | 0x000000 | 0x00F000 |
| 1 | Application | 0x011000 | ~0x121000 (image) |
| 2 | ota (upload staging) | 0x132000 | 0x1E0000 |
| 3 | RF Firmware | 0x1E0000 | 0x1E1000 |
| 4 | NET info | 0x1E1000 | 0x1E2000 |
| 5 | **Usr Config info** | 0x1E3000 | 0x200000 |

- `/ota` writes **only** partition 2 (`0x132000..0x1E0000`).
- The bootloader install writes **only** Application (`< 0x132000`).
- The **license at `0x1F2000` lives in Usr Config** (`0x1E3000..0x200000`) —
  disjoint from both. **No OTA operation can reach it, by construction.**

This is why the license survived the original ESPHome flash. A flash write
endangers the key exactly zero; a failed write falls back to "keep current app"
(there is **no stored factory image** to restore — see §4).

---

## 3. The method: one OTA write that is its own backup tool

1. Upload a **flashdump-capable reader image** via `/ota` (no opening the unit).
2. It boots and does one thing first: **read `0x1F2000` and serve it over HTTP**.
   The client fetches + verifies + backs up the license.
3. Only then proceed to the real install, or **re-flash stock** to restore.

Residual-risk ledger:

| Risk | Level | Why |
|---|---|---|
| License wiped / lost | **Zero** | outside every write range; non-volatile |
| Brick | **Low, recoverable** | any flash write; bootloader falls back to current app; UART (`bk7231tools`) is the unbrickable backstop |

"Zero risk of *anything*" is physically impossible OTA (any write has some brick
chance). "**Zero risk to the irreplaceable key, OTA, no opening the device**" is
achievable and is the bar we build to.

---

## 4. What the fallback is (and isn't)

There is **no factory/recovery partition**. The bootloader string
`Need to recovery factory firmware` means **reject the bad image and keep the
current app**, not "restore pristine stock." Consequences:

- A failed flash **while still stock** → stays on working stock (safety net for
  the first flash).
- After a **successful** custom flash → stock is overwritten; **no copy remains
  on flash**. Restoring stock = deliberately re-flashing the model's stock `.rbl`.
- Therefore each **device profile must bundle/link the stock `.rbl`** as the
  documented restore path (`profiles/*.json → images.stock_rbl`).

---

## 5. Proof — executable, in `tools/ota-sim/`

A software model of the `/ota` path, faithful to the RE and byte-compatible with
`tools/pack_rbl.py`. `run_demo.py` asserts (all passing):

- **A.** a license-stealer image, corrupted → **rejected before running**;
  Application + license byte-identical; **no dump produced**.
- **B.** a valid reader image → installs, dumps the license over HTTP; Application
  changes (replaceable stock), **license partition unchanged**.
- **C.** re-flash stock → Application restored; **license sha identical across
  A, B, C**.

`tools/dreo-setup.py` drives the same path as a real CLI over HTTP, enforcing the
**mandatory key-backup gate**:

```
restore BEFORE backup  -> BLOCK (exit 5)   "no license backup found"
backup-key             -> extract + VERIFY + save to backups/<model>/<ts>/
restore AFTER backup   -> ALLOW
```

The same tool targets a real device by changing `--device` to the fan's IP.

### 5.1 Real-firmware validation (`tools/fw-emu/`)

The mock is only as correct as the RE notes. To check it against ground truth,
`tools/fw-emu/` is a **Unicorn CPU emulator that executes the actual ARM Thumb
code** from `app.bin` (load base `0x10000`). `validate.py` runs the stock `/ota`
trailer-search function (`0x18514`, with real `strlen`/`memcmp`) on 8 inputs.

Result: 7/8 matched the naive model; the emulator **found a genuine off-by-one in
the stock parser** — its loop stops at `len - needle_len`, so a `\r\n---`
boundary flush at the very end of the buffer is not matched (`body.find` would
match it). Benign for real uploads (the closing boundary always has trailing
`--\r\n`), but the mock (`tools/ota-sim/device.py`) now replicates the exact
bound, so it is firmware-accurate. This is the payoff of real emulation over a
behavioral mock, and the pattern for validating the remaining handlers.

---

## 6. Open items before real hardware

- Build the real **reader image** = a minimal ESPHome/LibreTiny build with the
  existing `flashdump` island-scanner serving the license region over HTTP
  (replaces the sim's synthesized reader; wire as `profiles.images.reader_rbl`).
- **Tier 2**: validate on a sacrificial BK7231N (WB3S/CB3S or a $5 Tuya plug)
  flashed with the stock HCF001S `.rbl`, UART (`bk7231tools`) as the unbrick path.
- **License offset varies per unit** (0x1F2000 here, 0x1E35C0 on the tower dump) —
  `dreo-setup` should scan `search_from..search_to` for the CBOR blob rather than
  trust a fixed offset. (Sim currently seeds/reads the fixed offset.)

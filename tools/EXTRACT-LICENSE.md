# Extracting your Dreo device's factory license — no-open, non-destructive

The factory **license** (`{sn, signature, client_id, client_secret}`) is your
device's own cloud identity. The `signature` is a 256-byte RSA key that is
**stored in flash, not computed** — so it can only be read out, and it's what the
cloud-bridge needs to talk to Dreo's cloud as your device.

This gets it **without opening the device and without breaking the firmware**:
you take a read-only flash image over the air, then parse the license out of that
image offline. Nothing is flashed; the stock firmware is never modified.

> ⚠️ The license is **private key material** — your device's irreplaceable
> identity. Keep `license.json` like an SSH private key: don't post it, don't
> commit it (`.gitignore` already excludes `*license*.json`). Share the **method**
> (this doc + the tool), never the extracted key. Only extract from **your own**
> device.

## Step 1 — dump the flash over the air (non-destructive)

Use **dreo-cloudcutter** (`research/cloudcutter/`), the open-source Tuya/Beken
right-to-repair tool. It exploits the device's own pairing AP to run a small
payload **in RAM** that reads the flash and sends it back — then the device
reboots to its **untouched** stock firmware. No flashing, no soldering, nothing
overwritten.

- Follow `research/cloudcutter/README.md`. You put the device in pairing (AP)
  mode and run the "profile + dump" flow for a BK7231 device.
- It needs a device **profile**; `research/cloudcutter/code/Dreo_DR-HTF004S.yaml`
  is one. Feasibility depends on your model being exploitable — this is the only
  no-open path (stock firmware exposes no read-only network endpoint; see
  `research/phase0-key-read.md`). If cloudcutter can't dump your model, the
  fallback is a one-time UART read (`bk7231tools`, read-only — opens the device
  but still never writes it).
- Output: a flash image file (`.bin`).

## Step 2 — extract the license from the dump (offline, no device)

```bash
python3 tools/extract_license.py YOUR_DUMP.bin --out license.json
```

It locates the license in the image and writes `license.json`. It prints **only**
non-secret metadata (field offsets, lengths, a SHA-256) — never the key values.

- **HCF001S ceiling fan** (and the text-keyed CBOR generation): parsed exactly by
  CBOR key — verified byte-for-byte against the known-good license.
- **Older generation** (e.g. HTF004S): a base64/offset fallback; raw 2 MB BK7231
  dumps that are CRC-interleaved are de-interleaved automatically (or pass
  `--deinterleave`). Some very old images store the signature NUL-terminated at a
  fixed offset — `tools/dreo_register.py --tower` shows that path.

## Step 3 — use it (your own device)

`license.json` (`sn` + `signature`) is what `tools/dreo_register.py` /
`tools/dreo_bridge.py` use to register and bridge **your** device to the Dreo
cloud while keeping full local control. See `research/dreo-bridge.md`.

## Why this is the "without breaking the firmware" answer

Phase-0 analysis (`research/phase0-key-read.md`) showed stock firmware has **no
read-only OTA channel** — the only network door is `/ota`, a *write*. So the only
no-open way to read the key without modifying firmware is a **RAM-resident
exploit that dumps flash and reboots to intact stock** — exactly what cloudcutter
does. The extraction itself is pure offline parsing of an image you already hold.

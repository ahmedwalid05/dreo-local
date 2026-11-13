#!/usr/bin/env python3
"""dreo-setup — profile-driven onboarding for Dreo BK7231N devices.

THE SAFETY RULE (enforced here): no destructive step (restore/flash) runs until
a VERIFIED backup of the factory license exists on disk. The license partition
is never in a write path, but it is irreplaceable, so we read and verify it
first, every time.

Flow (all over plain HTTP, so the same tool drives the Tier-1 sim and a real
device — only --device changes):

  detect      confirm the upload endpoint is reachable
  backup-key  upload a flashdump reader image -> fetch the license over HTTP
              -> save + verify + checksum into backups/<model>/<ts>/
  restore     re-flash the stock .rbl  (GATED on a verified backup)
  flash       flash a target image     (GATED on a verified backup)
  status      show the device's last boot result

Usage:
  dreo-setup.py backup-key --profile profiles/dr-hcf001s.json --device http://127.0.0.1:8137 --sim
  dreo-setup.py restore    --profile profiles/dr-hcf001s.json --device http://127.0.0.1:8137 --image stock.rbl
"""
import os
import sys

# Python auto-prepends this script's directory (tools/, which contains helper
# modules like dis.py / inspect-shadowing names) to sys.path. That shadows
# stdlib modules the imports below need, so drop it before importing anything.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != HERE]

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
import urllib.request  # noqa: E402

ROOT = os.path.dirname(HERE)
BACKUPS = os.path.join(ROOT, "backups")
SIM_DIR = os.path.join(HERE, "ota-sim")


def hx(v) -> int:
    return int(v, 16) if isinstance(v, str) else int(v)


def load_profile(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


# ---- HTTP helpers -------------------------------------------------------
def _multipart(payload: bytes) -> bytes:
    b = b"----WebKitFormBoundaryDREOSETUP"
    return (b"--" + b + b"\r\n"
            b'Content-Disposition: form-data; name="firmware"; filename="fw.rbl"\r\n'
            b"Content-Type: application/octet-stream\r\n\r\n" +
            payload + b"\r\n--" + b + b"--\r\n")


def http_get(url: str, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:  # noqa: BLE001
        return None, str(e).encode()


def http_post(url: str, payload: bytes, timeout=30):
    req = urllib.request.Request(url, data=_multipart(payload), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# ---- reader-image acquisition ------------------------------------------
def build_reader_image(profile: dict, dump_name: str) -> bytes:
    """Return the RBL of a flashdump-capable image that reads the license region.

    --sim path: synthesize one with the sim's helpers. Real path: a prebuilt
    ESPHome-flashdump .rbl given in the profile or via --reader-image."""
    sys.path.insert(0, SIM_DIR)
    import bootloader  # noqa: E402  (sim helper)
    lic = profile["license"]
    return bootloader.build_flashdump_image(
        [{"off": hx(lic["offset"]), "len": int(lic["length"]), "file": dump_name}])


# ---- commands -----------------------------------------------------------
def cmd_detect(args, profile):
    ep = profile["upload"]["endpoint"]
    code, _ = http_get(args.device + ep)
    ok = code == 200
    print(f"detect {args.device}{ep}: {'reachable' if ok else f'FAILED ({code})'}")
    return 0 if ok else 2


def cmd_backup_key(args, profile):
    model = profile["model"]
    lic = profile["license"]
    dump_name = "license-dump.bin"

    code, _ = http_get(args.device + profile["upload"]["endpoint"])
    if code != 200:
        print(f"ERROR: device not reachable ({code})")
        return 2

    if args.reader_image:
        reader = open(args.reader_image, "rb").read()
    elif args.sim:
        reader = build_reader_image(profile, dump_name)
    else:
        print("ERROR: need --reader-image <prebuilt flashdump .rbl> (or --sim)")
        return 2

    print(f"uploading reader image ({len(reader)} B) to extract license "
          f"@ {lic['offset']} …")
    code, body = http_post(args.device + profile["upload"]["endpoint"], reader)
    print(f"  device: HTTP {code}")

    # poll the booted reader's dump endpoint
    data = None
    for _ in range(20):
        c, b = http_get(f"{args.device}/flashdump/{dump_name}")
        if c == 200 and b:
            data = b
            break
        time.sleep(0.2)
    if not data:
        print("ERROR: reader produced no dump (image rejected? wrong endpoint?)")
        return 3

    # ---- verify -------------------------------------------------------
    problems = []
    if len(data) != int(lic["length"]):
        problems.append(f"length {len(data)} != expected {lic['length']}")
    for m in lic.get("expect_markers", []):
        if m.encode() not in data:
            problems.append(f"marker {m!r} missing")
    if set(data) == {0xFF} or set(data) == {0x00}:
        problems.append("region is blank (all 0xFF/0x00)")

    sha = hashlib.sha256(data).hexdigest()
    ts = time.strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(BACKUPS, model, ts)
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, "license.bin"), "wb") as f:
        f.write(data)
    manifest = {"model": model, "device": args.device, "ts": ts,
                "offset": lic["offset"], "length": len(data),
                "sha256": sha, "verified": not problems,
                "problems": problems}
    with open(os.path.join(dest, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    # also update a stable "latest" pointer per model
    latest = os.path.join(BACKUPS, model, "latest.json")
    with open(latest, "w") as f:
        json.dump({**manifest, "path": dest}, f, indent=2)

    print(f"  saved  {dest}/license.bin")
    print(f"  sha256 {sha}")
    if problems:
        print("  VERIFY: FAILED -> " + "; ".join(problems))
        print("  (backup kept, but destructive steps stay BLOCKED)")
        return 4
    print("  VERIFY: OK — license backed up and validated")
    print(f"  bytes: {data[:48]!r}…")
    return 0


def _gate(profile) -> tuple[bool, str]:
    """Allow a destructive step only if a VERIFIED backup exists for this model."""
    latest = os.path.join(BACKUPS, profile["model"], "latest.json")
    if not os.path.exists(latest):
        return False, "no license backup found — run `backup-key` first"
    with open(latest) as f:
        m = json.load(f)
    if not m.get("verified"):
        return False, f"last backup failed verification ({m.get('problems')})"
    return True, f"verified backup {m['sha256'][:16]} at {m['path']}"


def _destructive(args, profile, label):
    ok, why = _gate(profile)
    print(f"[safety gate] {label}: {'ALLOW' if ok else 'BLOCK'} — {why}")
    if not ok:
        return 5
    if not args.image:
        print("ERROR: --image <.rbl> required")
        return 2
    img = open(args.image, "rb").read()
    code, _ = http_post(args.device + profile["upload"]["endpoint"], img)
    print(f"  flashed {args.image} ({len(img)} B): HTTP {code}")
    return 0


def cmd_restore(args, profile):
    return _destructive(args, profile, "restore stock")


def cmd_flash(args, profile):
    return _destructive(args, profile, "flash target firmware")


def cmd_status(args, profile):
    code, body = http_get(args.device + "/status")
    print(body.decode(errors="replace") if code == 200 else f"status failed ({code})")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Dreo BK7231N onboarding (key-backup first)")
    ap.add_argument("command", choices=["detect", "backup-key", "restore", "flash", "status"])
    ap.add_argument("--profile", required=True)
    ap.add_argument("--device", required=True, help="base URL, e.g. http://192.168.0.1")
    ap.add_argument("--image", help=".rbl for restore/flash")
    ap.add_argument("--reader-image", help="prebuilt flashdump .rbl for backup-key")
    ap.add_argument("--sim", action="store_true", help="synthesize the reader image for the Tier-1 sim")
    args = ap.parse_args()
    profile = load_profile(args.profile)
    fn = {"detect": cmd_detect, "backup-key": cmd_backup_key, "restore": cmd_restore,
          "flash": cmd_flash, "status": cmd_status}[args.command]
    sys.exit(fn(args, profile))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Fake rt_ota bootloader: runs on every (simulated) reboot.

Models the real gate order and — crucially — the ORDERING the whole Phase-0
analysis turned on:

    reject happens BEFORE any install, and nothing "runs" until AFTER a
    successful install. So a deliberately-invalid image executes nothing and
    cannot read the license. A valid image overwrites Application (the
    replaceable stock app) to run — the license partition is never in the path.

A "booted app" that carries the FLASHDUMP manifest models your ESPHome
flashdump component: on its first boot it reads a flash region and emits it
(here: writes out/license-dump.bin). This is the ONLY way bytes leave flash,
and it requires a successful install first.
"""
import json
import os

import flash as flashmod
import rbl

FLASHDUMP_MAGIC = b"FLASHDUMP"  # marks a raw payload as a reader image
STOCK_MAGIC = b"STOCKAPP"


def boot(fl: "flashmod.Flash", outdir: str) -> dict:
    """Validate the staged 'ota' image and install-or-reject. Returns a report."""
    start, end = fl.bounds("ota")
    staged = fl.read(start, end - start).rstrip(b"\xff")
    if not staged:
        return {"action": "no_staged_image", "installed": False,
                "ran": None, "note": "ota partition empty; booting current app"}

    ok, reason, raw = rbl.validate(staged)
    if not ok:
        # ---- REJECT path: Application left EXACTLY as-is. Nothing executes.
        return {"action": "reject", "installed": False, "ran": None,
                "reason": reason,
                "note": "App verify failed! Need to recovery factory firmware. "
                        "-> kept current Application, read NOTHING"}

    # ---- ACCEPT path: overwrite Application with the decrypted image, boot it.
    fl.write_in("Application", 0, raw)
    # clear the staging partition the way a real install consumes it
    fl.write_in("ota", 0, b"\xff" * (end - start))

    ran = _run_app(fl, raw, outdir)
    return {"action": "install", "installed": True, "ran": ran,
            "reason": reason, "image_name": _tag(raw)}


def _tag(raw: bytes) -> str:
    if raw.startswith(FLASHDUMP_MAGIC):
        return "flashdump-reader"
    if raw.startswith(STOCK_MAGIC):
        return "stock"
    return "unknown"


def _run_app(fl: "flashmod.Flash", raw: bytes, outdir: str):
    """Simulate booting the just-installed app."""
    if raw.startswith(FLASHDUMP_MAGIC):
        manifest = json.loads(raw[len(FLASHDUMP_MAGIC):].split(b"\x00", 1)[0])
        dumps = []
        for reg in manifest["read"]:
            data = fl.read(reg["off"], reg["len"])
            path = os.path.join(outdir, reg.get("file", f"dump-{reg['off']:#x}.bin"))
            with open(path, "wb") as f:
                f.write(data)
            dumps.append({"off": hex(reg["off"]), "len": reg["len"], "file": path,
                          "sha16": __import__("hashlib").sha256(data).hexdigest()[:16]})
        return {"app": "flashdump-reader", "dumped": dumps}
    if raw.startswith(STOCK_MAGIC):
        return {"app": "stock", "note": "stock app running (waiting for MCU heartbeat)"}
    return {"app": "unknown", "note": "booted an unrecognized image"}


# ---- image builders used by the harness --------------------------------
def build_stock_image(size: int = 4096) -> bytes:
    return rbl.pack(STOCK_MAGIC + b"\x00" + os.urandom(size), name=b"app")


def build_flashdump_image(read_regions: list[dict]) -> bytes:
    manifest = json.dumps({"type": "flashdump-reader", "read": read_regions}).encode()
    # pad past the stock >1023-byte minimum with incompressible filler placed
    # AFTER a null terminator (so _run_app's split-on-null manifest parse is unaffected)
    raw = FLASHDUMP_MAGIC + manifest + b"\x00" + os.urandom(2048)
    return rbl.pack(raw, name=b"app")

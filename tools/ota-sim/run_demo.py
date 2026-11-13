#!/usr/bin/env python3
"""End-to-end Tier-1 demo, driven over REAL HTTP against the fake /ota server.

Proves the three Phase-0 claims as executable assertions:

  A. A deliberately-invalid image is REJECTED by the bootloader, Application is
     untouched, and NOTHING is read  -> the "failing image that reads the key"
     idea cannot work (reject precedes execution).
  B. A valid flashdump-reader image INSTALLS, runs, and dumps the license;
     Application changes (stock overwritten) but the license bytes do NOT.
  C. Re-flashing stock restores Application; the license STILL never moved
     -> nothing irreplaceable was ever at risk.
"""
import os
import threading
import urllib.request
from http.server import HTTPServer

import bootloader
import device
import flash as flashmod
import seed as seedmod

HERE = os.path.dirname(os.path.abspath(__file__))
FLASH = os.path.join(HERE, "flash.img")
OUT = os.path.join(HERE, "out")
PORT = 8137


def multipart(payload: bytes, field=b"firmware", filename=b"fw.rbl") -> bytes:
    b = b"----WebKitFormBoundarySIM"
    return (b"--" + b + b"\r\n"
            b'Content-Disposition: form-data; name="' + field +
            b'"; filename="' + filename + b'"\r\n'
            b"Content-Type: application/octet-stream\r\n\r\n" +
            payload + b"\r\n--" + b + b"--\r\n")


def post(payload: bytes) -> str:
    body = multipart(payload)
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/ota", data=body,
                                 method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read().decode()


def line(c="-"):
    print(c * 72)


def main():
    os.makedirs(OUT, exist_ok=True)
    # clear previous dumps
    for f in os.listdir(OUT):
        os.remove(os.path.join(OUT, f))
    seedmod.seed(FLASH)

    state = device.DeviceState(FLASH, OUT)
    srv = HTTPServer(("127.0.0.1", PORT), device._make_handler(state))
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    lic0 = state.fl.license_hash()
    app_stock = state.fl.part_hash("Application")
    print(f"\nstart: license sha16={lic0}  Application sha16={app_stock}\n")

    # ---- A. corrupt image: must be rejected, change nothing, read nothing ---
    line("=")
    print("A. upload a license-STEALER image, then corrupt it (bad package CRC)")
    # a reader image that WOULD exfiltrate the license to out/STOLEN-license.bin
    stealer = bootloader.build_flashdump_image(
        [{"off": flashmod.LICENSE_OFF, "len": flashmod.LICENSE_LEN,
          "file": "STOLEN-license.bin"}])
    # flip one payload byte -> data CRC no longer matches -> bootloader rejects
    bad = bytearray(stealer)
    bad[100] ^= 0xFF
    post(bytes(bad))
    b = state.last_boot
    print(f"   bootloader: action={b['action']}  reason={b.get('reason')}")
    assert b["action"] == "reject" and not b["installed"]
    assert b["ran"] is None, "a rejected image must not run"
    assert state.fl.license_hash() == lic0, "license changed!"
    assert state.fl.part_hash("Application") == app_stock, "Application changed!"
    assert not os.path.exists(os.path.join(OUT, "STOLEN-license.bin"))
    print("   -> rejected; Application + license UNTOUCHED; read NOTHING  [OK]")

    # ---- B. valid reader image: installs, dumps license, license unchanged --
    line("=")
    print("B. upload a VALID flashdump-reader image")
    good = bootloader.build_flashdump_image(
        [{"off": flashmod.LICENSE_OFF, "len": flashmod.LICENSE_LEN,
          "file": "license-dump.bin"}])
    post(good)
    b = state.last_boot
    print(f"   bootloader: action={b['action']}  image={b.get('image_name')}")
    print(f"   app ran:    {b['ran']}")
    dump_path = os.path.join(OUT, "license-dump.bin")
    assert b["action"] == "install" and b["installed"]
    assert os.path.exists(dump_path), "reader image should have dumped the license"
    dumped = open(dump_path, "rb").read()
    assert dumped == state.fl.license_bytes(), "dump != on-flash license"
    assert state.fl.license_hash() == lic0, "license changed during read!"
    app_reader = state.fl.part_hash("Application")
    assert app_reader != app_stock, "Application should now hold the reader app"
    print(f"   -> license dumped to out/license-dump.bin  sha16={lic0}")
    print(f"   -> Application CHANGED (stock overwritten by reader): {app_reader}")
    print(f"   -> license partition UNCHANGED: {state.fl.license_hash()}  [OK]")

    # ---- C. re-flash stock: Application restored, license still untouched ---
    line("=")
    print("C. re-flash STOCK (.rbl) to restore the device")
    post(bootloader.build_stock_image(size=4096))
    b = state.last_boot
    assert b["action"] == "install" and b["ran"]["app"] == "stock"
    assert state.fl.license_hash() == lic0, "license changed during restore!"
    print(f"   -> stock reinstalled; license STILL {state.fl.license_hash()}  [OK]")

    srv.shutdown()
    line("=")
    print("\nALL ASSERTIONS PASSED")
    print(f"  license sha16 across A,B,C:  {lic0}  (never changed)")
    print(f"  recovered license -> {dump_path}")
    print(f"  bytes: {open(dump_path, 'rb').read()[:64]!r}...")


if __name__ == "__main__":
    main()

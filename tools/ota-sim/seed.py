#!/usr/bin/env python3
"""Initialise flash.img: pristine stock device with a factory license in place.

  - 'Application' holds an installed STOCK image (decrypted, as the bootloader
    would have left it)
  - 'Usr Config info' holds a stand-in factory license blob at 0x1F2000
    (a tagged blob, not real CBOR — we only track that these bytes never move)
"""
import argparse
import os

import bootloader
import flash as flashmod
import rbl

LICENSE_BLOB = (b"FAKELICENSE{sn:1706512872524279810,"
                b"sig:DEADBEEFfactorysignatureNOTforgeable,"
                b"cert:---stand-in---}")


def seed(path: str):
    fl = flashmod.Flash(path)
    # install a stock app the way a successful boot would (decrypted raw bytes)
    stock_rbl = bootloader.build_stock_image(size=4096)
    _, _, raw = rbl.validate(stock_rbl)
    fl.write_in("Application", 0, raw)
    # NET info: some wifi config
    fl.write_in("NET info", 0, b"SSID=DREOcf01-f659\x00")
    # the irreplaceable secret, at its real offset inside Usr Config
    off_in_part = flashmod.LICENSE_OFF - flashmod.PARTITIONS["Usr Config info"][0]
    fl.write_in("Usr Config info", off_in_part,
                LICENSE_BLOB.ljust(flashmod.LICENSE_LEN, b"\x00"))
    fl.save()
    print(f"seeded {path}")
    print(f"  license @ {flashmod.LICENSE_OFF:#08x}  sha16={fl.license_hash()}")
    for p, h in fl.snapshot().items():
        print(f"  {p:<16} {h}")
    return fl


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--flash", default="flash.img")
    a = ap.parse_args()
    os.makedirs("out", exist_ok=True)
    seed(a.flash)

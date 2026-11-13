#!/usr/bin/env python3
"""Extract the Dreo factory license (SN + signature) from a flash dump.

Pure offline data parsing on a flash image you already pulled from YOUR OWN
device. The usual no-open, non-destructive way to get that image is
dreo-cloudcutter, which dumps flash from RAM without flashing or modifying the
stock firmware (research/cloudcutter/); any read-only dump works too. This tool
never touches a device or the network.

In flash the license is stored as NUL-terminated ASCII strings (the offset moves
by model — tower HTF004S @0x1E35C0, ceiling-fan HCF001S @0x1F2000 — so this tool
*scans* instead of trusting an offset):
  - signature : ~344-char base64 (a 256-byte RSA-2048 signature), stored not derived
  - sn        : the device serial, e.g. 1706...-9ae6...:001:0000000000w

The signature is your device's irreplaceable factory identity. This tool writes
it to a file and prints ONLY non-secret metadata (offsets, lengths, a SHA-256) —
never the values. Treat the output like a private key; .gitignore already
excludes *license*.json.

Usage:  extract_license.py DUMP.bin [--out license.json]
"""
import os
import sys

sys.path[:] = [p for p in sys.path
               if os.path.abspath(p or ".") != os.path.dirname(os.path.abspath(__file__))]

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402

# The license is a text-keyed CBOR map: key "<name>" (CBOR text) then a CBOR
# text value (length-prefixed). We read each field by locating its key and
# decoding the following CBOR text string's length header — exact boundaries,
# independent of per-model offsets or value lengths.
def _cbor_text_after(buf, i):
    """Decode the CBOR text string that starts at buf[i]; return (value, end)."""
    b = buf[i]
    if b >> 5 != 3:                       # major type 3 = text string
        raise ValueError("not a CBOR text string at %#x" % i)
    ai = b & 0x1F
    i += 1
    if ai < 24:
        n = ai
    elif ai == 24:
        n = buf[i]; i += 1
    elif ai == 25:
        n = int.from_bytes(buf[i:i + 2], "big"); i += 2
    else:
        raise ValueError("unexpected CBOR text length form %d" % ai)
    return buf[i:i + n].decode("utf-8", "replace"), i + n


def _field(buf, name):
    """Find CBOR key `name` (text) and return (value, key_offset) or (None, -1)."""
    key = bytes([0x60 | len(name)]) + name.encode()   # CBOR text key, len < 24
    k = buf.find(key)
    if k < 0:
        return None, -1
    val, _ = _cbor_text_after(buf, k + len(key))
    return val, k


# fallback for the older gen (HTF004S etc.): the signature is a NUL/boundary-
# delimited 344-char base64 string, not a CBOR text-keyed map.
SIG_RE = re.compile(rb"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{344}(?![A-Za-z0-9+/])")
SN_RE = re.compile(rb"[0-9]{16,}-[0-9a-fA-F]{12,}:[0-9]{3}:[0-9A-Za-z]{4,}")


def find_license(buf):
    out = {}
    # primary: text-keyed CBOR map (HCF001S ceiling-fan gen)
    for name in ("sn", "signature", "client_id", "client_secret"):
        v, off = _field(buf, name)
        if v is not None:
            out[name] = v
            out["_%s_off" % name] = off
    if "signature" in out:
        return out
    # fallback: NUL/boundary-delimited base64 signature (HTF004S / older gen)
    sig = SIG_RE.search(buf)
    if sig:
        out["signature"] = sig.group().decode()
        out["_signature_off"] = sig.start()
        sn = SN_RE.search(buf)
        if sn:
            out["sn"] = sn.group().decode()
            out["_sn_off"] = sn.start()
        return out
    raise ValueError("no signature found — dump may be partial/erased, or "
                     "CRC-interleaved (de-interleave the raw 2 MB dump first), "
                     "or a fuller/full-flash dump is needed")


def main():
    ap = argparse.ArgumentParser(description="Extract Dreo factory license from a flash dump")
    ap.add_argument("dump")
    ap.add_argument("--out", default="license.json")
    ap.add_argument("--deinterleave", action="store_true",
                    help="strip the raw BK7231 flash CRC interleave (4 CRC bytes "
                         "per 32 data bytes) before parsing — for raw 2 MB dumps")
    a = ap.parse_args()
    buf = open(a.dump, "rb").read()
    if a.deinterleave:
        buf = b"".join(buf[i:i + 32] for i in range(0, len(buf), 36))
    try:
        info = find_license(buf)
    except ValueError:
        # auto-retry with de-interleave if it wasn't requested
        if not a.deinterleave:
            dj = b"".join(buf[i:i + 32] for i in range(0, len(buf), 36))
            info = find_license(dj)
        else:
            raise

    lic = {k: info[k] for k in ("sn", "signature", "client_id", "client_secret")
           if k in info}
    with open(a.out, "w") as f:
        json.dump(lic, f, indent=2)

    # metadata only — never the secret values
    for k in ("sn", "signature", "client_id", "client_secret"):
        if k in info:
            print(f"  {k:<14} {len(info[k]):>4} chars @ dump {info['_%s_off' % k]:#08x}"
                  f"  sha256={hashlib.sha256(info[k].encode()).hexdigest()[:16]}")
    print(f"written -> {a.out}  (private key material — do not share or commit)")
    if "sn" not in lic:
        print("note: 'sn' not in dump; take it from the device label if needed", file=sys.stderr)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Beken/Dreo RBL pack + validate — byte-faithful to tools/pack_rbl.py.

The simulator's fake bootloader uses validate() to decide install-vs-reject,
mirroring the real rt_ota gate order so the harness tests the real logic:

  1. magic "RBL\\0"
  2. header_crc32 @92 == crc32(header[:92])
  3. enc != 0            (real bootloader: "none encrypt ... Not allow!")
  4. data_size   @88 == len(enc_payload on disk)
  5. data_crc    @76 == crc32(enc_payload)
  6. AES-256-CBC decrypt -> strip pad -> gunzip -> raw
  7. raw_size    @84 == len(raw)
  8. data_hash   @80 == fnv1a(raw)

Header layout (96 bytes), from pack_rbl.py's struct "<4sbbxxI16s24s24sIIII"+I:
  0x00 magic 4s | 0x04 enc b | 0x05 comp b | 0x06 pad xx | 0x08 ts I
  0x0C name 16s | 0x1C ver 24s | 0x34 sn 24s
  0x4C data_crc I | 0x50 data_hash I | 0x54 raw_size I | 0x58 data_size I
  0x5C header_crc32 I
"""
import gzip
import struct
from binascii import crc32

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

KEY = b"0123456789ABCDEF0123456789ABCDEF"
IV = b"0123456789ABCDEF"
FNV_OFF, FNV_PRIME, FNV_MOD = 0x811C9DC5, 0x01000193, 1 << 32

HDR_FMT = "<4sbbxxI16s24s24sIIII"  # 92 bytes
assert struct.calcsize(HDR_FMT) == 92


def fnv1a(data: bytes) -> int:
    h = FNV_OFF
    for b in data:
        h = ((h ^ b) * FNV_PRIME) % FNV_MOD
    return h


def _aes_cbc_encrypt(payload: bytes) -> bytes:
    return Cipher(algorithms.AES(KEY), modes.CBC(IV)).encryptor().update(payload)


def _aes_cbc_decrypt(payload: bytes) -> bytes:
    return Cipher(algorithms.AES(KEY), modes.CBC(IV)).decryptor().update(payload)


def pack(raw: bytes, *, name: bytes = b"app", ver: bytes = b"20191018",
         sn: bytes = b"0001", ts: int = 0,
         corrupt: str | None = None) -> bytes:
    """Build a valid RBL from a raw firmware payload.

    corrupt lets the harness forge images the bootloader must reject:
      "magic"   bad RBL magic
      "hdrcrc"  flip a header byte after the crc is computed
      "datacrc" flip a payload byte after data_crc is computed
      "plain"   enc=0 (plaintext not allowed)
      "hash"    wrong data_hash (payload tampered post-hash)
    """
    comp = 1
    enc = 0 if corrupt == "plain" else 2
    gz = gzip.compress(raw, compresslevel=9, mtime=0)
    pad = (16 - (len(gz) % 16)) % 16
    payload = gz + bytes([pad]) * pad
    enc_payload = _aes_cbc_encrypt(payload) if enc == 2 else payload

    hdr = bytearray(struct.pack(
        HDR_FMT, b"RBL\x00", enc, comp, ts,
        name.ljust(16, b"\0")[:16], ver.ljust(24, b"\0")[:24],
        sn.ljust(24, b"\0")[:24],
        crc32(enc_payload), fnv1a(raw), len(raw), len(enc_payload)))

    if corrupt == "magic":
        hdr[0:4] = b"XXX\x00"
    if corrupt == "datacrc":
        struct.pack_into("<I", hdr, 76, (crc32(enc_payload) ^ 0xFFFF) & 0xFFFFFFFF)
    if corrupt == "hash":
        struct.pack_into("<I", hdr, 80, (fnv1a(raw) ^ 0x1234) & 0xFFFFFFFF)

    rbl = bytes(hdr) + struct.pack("<I", crc32(bytes(hdr)))
    if corrupt == "hdrcrc":
        rbl = bytes(hdr) + struct.pack("<I", (crc32(bytes(hdr)) ^ 0x1) & 0xFFFFFFFF)
    return rbl + enc_payload


def parse_header(data: bytes) -> dict:
    (magic, enc, comp, ts, name, ver, sn,
     data_crc, data_hash, raw_size, data_size) = struct.unpack(HDR_FMT, data[:92])
    header_crc32, = struct.unpack("<I", data[92:96])
    return dict(magic=magic, enc=enc, comp=comp, ts=ts,
                name=name.split(b"\0")[0], ver=ver.split(b"\0")[0],
                sn=sn.split(b"\0")[0], data_crc=data_crc, data_hash=data_hash,
                raw_size=raw_size, data_size=data_size, header_crc32=header_crc32)


def validate(data: bytes):
    """Return (ok: bool, reason: str, raw: bytes|None) exactly where the real
    bootloader would accept or reject, and why."""
    if len(data) < 96:
        return False, "too short (< 96-byte header)", None
    h = parse_header(data)
    if h["magic"] != b"RBL\x00":
        return False, f"bad magic {h['magic']!r} (expect RBL\\0)", None
    if crc32(data[:92]) != h["header_crc32"]:
        return False, "header CRC mismatch", None
    if h["enc"] == 0:
        return False, "enc=0 -> 'none encrypt ... Not allow!'", None
    enc_payload = data[96:]
    if len(enc_payload) != h["data_size"]:
        return False, f"data_size {h['data_size']} != payload {len(enc_payload)}", None
    if crc32(enc_payload) != h["data_crc"]:
        return False, "package (data) CRC mismatch", None
    try:
        payload = _aes_cbc_decrypt(enc_payload) if h["enc"] == 2 else enc_payload
        pad = payload[-1]
        if 0 < pad <= 16 and payload[-pad:] == bytes([pad]) * pad:
            payload = payload[:-pad]
        raw = gzip.decompress(payload)
    except Exception as e:  # noqa: BLE001
        return False, f"decrypt/decompress failed: {e}", None
    if len(raw) != h["raw_size"]:
        return False, f"raw_size {h['raw_size']} != decompressed {len(raw)}", None
    if fnv1a(raw) != h["data_hash"]:
        return False, "firmware hash (fnv1a) mismatch", None
    return True, "ok", raw

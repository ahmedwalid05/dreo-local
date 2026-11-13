#!/usr/bin/env python3
"""A fake 2 MB BK7231N flash with the real Dreo partition geometry.

Offsets verified against the on-flash partition table in
research/module-firmware-report.md (DR-HTF004S dump, same BK7231N/rt_ota family).

Invariants the harness proves:
  - /ota upload writes ONLY the 'ota' partition      (0x132000..0x1E0000)
  - bootloader install writes ONLY 'Application'      (0x011000..0x132000)
  - the factory license at 0x1F2000 lives in          'Usr Config info'
    (0x1E3000..0x200000) -> disjoint from both -> never written.
"""
import hashlib

SIZE = 0x200000  # 2 MB

# name: (start, length)  -- Application length trimmed to 0x121000 so it ends
# exactly at 'ota'; the real table over-declares it to 0x143000 (a vendor quirk
# that overlaps 'ota' on paper but not in used bytes). See README.
PARTITIONS = {
    "Bootloader":      (0x000000, 0x00F000),
    "Application":     (0x011000, 0x121000),  # ends at 0x132000 (ota start)
    "ota":             (0x132000, 0x0AE000),  # ends at 0x1E0000
    "RF Firmware":     (0x1E0000, 0x001000),
    "NET info":        (0x1E1000, 0x001000),
    "Usr Config info": (0x1E3000, 0x01D000),  # ends at 0x200000
}
LICENSE_OFF = 0x1F2000   # inside 'Usr Config info'
LICENSE_LEN = 0x100


class WriteViolation(Exception):
    """Raised when a simulated write leaves its declared partition."""


class Flash:
    def __init__(self, path: str):
        self.path = path
        self.mem = bytearray(b"\xff" * SIZE)
        self.log: list[str] = []

    # ---- persistence ----------------------------------------------------
    def load(self):
        with open(self.path, "rb") as f:
            data = f.read()
        self.mem = bytearray(data.ljust(SIZE, b"\xff")[:SIZE])
        return self

    def save(self):
        with open(self.path, "wb") as f:
            f.write(self.mem)
        return self

    # ---- partition helpers ---------------------------------------------
    @staticmethod
    def bounds(part: str) -> tuple[int, int]:
        start, length = PARTITIONS[part]
        return start, start + length

    def read(self, addr: int, length: int) -> bytes:
        return bytes(self.mem[addr:addr + length])

    def write_in(self, part: str, offset_in_part: int, data: bytes):
        """Write, hard-asserting the bytes stay inside `part` (models the
        driver only ever being handed that partition's base)."""
        start, end = self.bounds(part)
        addr = start + offset_in_part
        if addr < start or addr + len(data) > end:
            raise WriteViolation(
                f"write of {len(data)}B at {addr:#08x} escapes {part} "
                f"[{start:#08x}..{end:#08x})")
        self.mem[addr:addr + len(data)] = data
        self.log.append(f"write {len(data):>7}B -> {part} @ {addr:#08x}")

    # ---- inspection -----------------------------------------------------
    def part_hash(self, part: str) -> str:
        start, end = self.bounds(part)
        return hashlib.sha256(self.mem[start:end]).hexdigest()[:16]

    def license_bytes(self) -> bytes:
        return self.read(LICENSE_OFF, LICENSE_LEN)

    def license_hash(self) -> str:
        return hashlib.sha256(self.license_bytes()).hexdigest()[:16]

    def snapshot(self) -> dict:
        return {p: self.part_hash(p) for p in PARTITIONS}

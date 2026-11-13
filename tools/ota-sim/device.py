#!/usr/bin/env python3
"""Fake stock '/ota' HTTP endpoint — mirrors the DR-ceiling-fan 3.8.13 handler
reversed in research/module-firmware-report.md §3.

Faithful quirks:
  - routes: GET /ota, GET /ota.html -> 457B-style upload form; POST -> upload
  - multipart body data = bytes between the 2ND '\\r\\n\\r\\n' (end of part
    headers) and the 1ST '\\r\\n---' (closing boundary); the boundary value is
    never parsed, the field name is never checked
  - size gate: 1023 < len(data) <= 655360
  - accepted bytes written verbatim into the 'ota' partition (0x132000)
  - replies 'HTTP/1.0 200 OK' then WDT-reboots -> the bootloader runs

Run as a server:  python3 -I device.py [--flash flash.img] [--port 8080]
Or import DeviceState and call handle_post(body) directly (no socket).
"""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer

import bootloader
import flash as flashmod

OTA_FORM = (b"<html><head><title>MODULE OTA: 3.8.13</title></head>"
            b"<body><h3>MODULE OTA</h3>"
            b"<form method='post' enctype='multipart/form-data'>"
            b"<input type=file name=firmware><input type=submit></form></body></html>")

MIN_BODY = 1023      # strict: must be > this
MAX_BODY = 655360    # <= this


class DeviceState:
    """Pure-logic model of one fake device (no sockets)."""

    def __init__(self, flash_path: str, outdir: str):
        self.outdir = outdir
        self.fl = flashmod.Flash(flash_path).load()
        self.last_boot: dict | None = None

    @staticmethod
    def extract_upload(body: bytes) -> bytes | None:
        """Stock parse: 2nd '\\r\\n\\r\\n' .. 1st '\\r\\n---'."""
        first = body.find(b"\r\n\r\n")
        if first < 0:
            return None
        second = body.find(b"\r\n\r\n", first + 4)
        if second < 0:
            return None
        datastart = second + 4
        trailer = body.find(b"\r\n---", datastart)
        # firmware-faithful (emulator-confirmed, tools/fw-emu): the stock trailer
        # search loop stops at len - needle_len, so a boundary flush at the very
        # end of the buffer (no trailing byte) is NOT matched. Benign for real
        # uploads (the closing boundary always has trailing '--\r\n').
        if trailer < 0 or trailer > len(body) - len(b"\r\n---") - 1:
            return None
        return body[datastart:trailer]

    def handle_post(self, body: bytes) -> dict:
        """Returns the device's view of the result (status + post-reboot boot)."""
        data = self.extract_upload(body)
        if data is None:
            return {"http": 400, "note": "could not locate multipart data", "wrote": False}
        if not (MIN_BODY < len(data) <= MAX_BODY):
            return {"http": 200, "note": f"size {len(data)} outside "
                    f"({MIN_BODY}, {MAX_BODY}] -> ignored, no write", "wrote": False}
        # verbatim write into 'ota' staging, then WDT reboot -> bootloader
        self.fl.write_in("ota", 0, data)
        self.fl.save()
        boot = bootloader.boot(self.fl, self.outdir)
        self.fl.save()
        self.last_boot = boot
        return {"http": 200, "wrote": True, "staged_bytes": len(data), "boot": boot}


def _make_handler(state: DeviceState):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, code, body=b"", ctype="text/html;charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            import os as _os
            # /ota is always accepted as the upload interface. (On real hardware
            # this is stock's /ota before flashing and ESPHome's OTA after; the
            # sim abstracts both as one upload endpoint — see README.)
            if self.path in ("/ota", "/ota.html"):
                self._send(200, OTA_FORM)
            elif self.path.startswith("/flashdump/"):
                # the currently-running reader app serving a dump it produced
                name = _os.path.basename(self.path[len("/flashdump/"):])
                path = _os.path.join(state.outdir, name)
                if _os.path.exists(path):
                    with open(path, "rb") as f:
                        self._send(200, f.read(), "application/octet-stream")
                else:
                    self._send(404, b"no such dump")
            elif self.path == "/status":
                self._send(200, str(state.last_boot or {}).encode(), "text/plain")
            else:
                self._send(404, b"The path which is requested is not found!")

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            # reconstruct the raw request the stock server sees on the socket:
            # HTTP headers + part headers = the two '\r\n\r\n' it counts. We
            # prepend a guaranteed HTTP terminator so the 1st '\r\n\r\n' is the
            # HTTP block and the 2nd is the multipart part-header block.
            raw = b"POST /ota HTTP/1.1\r\nContent-Type: multipart/form-data\r\n\r\n" + body
            res = state.handle_post(raw)
            self._send(res["http"], str(res).encode(), "text/plain")
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flash", default="flash.img")
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    state = DeviceState(args.flash, args.outdir)
    srv = HTTPServer(("127.0.0.1", args.port), _make_handler(state))
    print(f"fake stock /ota on http://127.0.0.1:{args.port}/ota  flash={args.flash}")
    srv.serve_forever()


if __name__ == "__main__":
    main()

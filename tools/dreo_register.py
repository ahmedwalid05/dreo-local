#!/usr/bin/env python3
"""Register a Dreo device SN on the cloud and mint its MQTT credentials.

THE RECIPE (discovered 2026-11-04, proven live):

  1. POST {device-api}/api/oauth/login            (device grant: your client pair
     (DREO_CLIENT_ID/SECRET), grant_type=device, devicesn=<SN>)          → device Bearer
  2. POST {device-api}/api/device/activate/emq    (the netconfRegisterUrl from the
     app's GET /api/user-device/device/product — user token needed only to LOOK it up)
        Authorization: Bearer <device token>
        UA: dreo/hefi 1.0.3
        {"signature": "<factory license signature, 344-char base64>",
         "userId": "<dreo user id, e.g. from GET /api/user/info>",
         "automatic": true,                     # binds device to that account
         "metaInfo": {"moduleHardwareModel":"HeFi","moduleFirmwareVersion":"…",
                      "mcuHardwareModel":"…","mcuFirmwareVersion":"…"}}
     → {"code":0,"data":{"endPoint","port","username","password","prefix",
        "certificatePem","privateKey","type":"emq","env":"pro", …}}

  The signature is per-SN factory data (344-char base64 = 256-byte RSA-2048),
  stored in the device flash. Read it with tools/extract_license.py, or the UART
  factory console `getsig`/`getlic`.

  Each activate call mints a FRESH password/cert and appears to invalidate the
  previous set — register, then connect immediately.

Usage:
  dreo_register.py --sn <SN> --sig <signature> [--uid <userId>] [--host eu|us] [--out creds.json]
"""
import argparse
import os
import json
import ssl
import time
import urllib.request

HOSTS = {"eu": "https://device-api-eu.dreo-cloud.com",
         "us": "https://device-api-us.dreo-cloud.com"}
# Dreo app client credentials come FROM THE DREO ANDROID APP (not shipped here).
# Supply your own: export DREO_CLIENT_ID / DREO_CLIENT_SECRET / DREO_USER_ID.
CLIENT_ID = os.environ.get("DREO_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("DREO_CLIENT_SECRET", "")
UA = "dreo/hefi 1.0.3"
DEFAULT_UID = os.environ.get("DREO_USER_ID", "")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE  # device-api TLS cert expired 2025-09 (devices ignore)


def post(url, body, tok=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("content-type", "application/json")
    for k, v in {"accept": "*/*", "user-agent": UA, "ua": UA, "lang": "en-US",
                 **({"authorization": f"Bearer {tok}"} if tok else {})}.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, context=CTX, timeout=25) as r:
        return json.loads(r.read())




def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sn")
    ap.add_argument("--sig")
    ap.add_argument("--uid", default=DEFAULT_UID)
    ap.add_argument("--host", choices=["eu", "us"], default="eu")
    ap.add_argument("--out", default=None)
    ap.add_argument("--module-fw", default="1.2.52")
    ap.add_argument("--mcu-model", default="TS32F020SOP28")
    ap.add_argument("--mcu-fw", default="1.0.0")
    args = ap.parse_args()

    if not (args.sn and args.sig):
        ap.error("need --sn and --sig")
    if not (CLIENT_ID and CLIENT_SECRET):
        ap.error("set DREO_CLIENT_ID and DREO_CLIENT_SECRET (from the Dreo app)")

    host = HOSTS[args.host]
    d = post(f"{host}/api/oauth/login?timestamp={int(time.time()*1000)}&lang=en-US",
             {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
              "grant_type": "device", "scope": "all", "devicesn": args.sn})
    tok = (d.get("data") or {}).get("access_token")
    if not tok:
        raise SystemExit(f"device oauth failed: {d}")

    body = {"signature": args.sig, "userId": args.uid, "automatic": True,
            "metaInfo": {"moduleHardwareModel": "HeFi",
                         "moduleFirmwareVersion": args.module_fw,
                         "mcuHardwareModel": args.mcu_model,
                         "mcuFirmwareVersion": args.mcu_fw}}
    r = post(f"{host}/api/device/activate/emq", body, tok)
    print(json.dumps({k: (v[:50] + "…" if isinstance(v, str) and len(v) > 50 else v)
                      for k, v in (r.get("data") or {}).items()}, indent=1)
          if r.get("code") == 0 else json.dumps(r))
    if r.get("code") != 0:
        raise SystemExit(f"register failed: {r}")

    out = args.out or f"/tmp/dreo/creds_{args.sn.split('-')[0]}.json"
    json.dump({"sn": args.sn, "host": args.host, **r["data"]},
              open(out, "w"), indent=1)
    print(f"creds saved → {out}")
    print("connect NOW with dreo_mqtt.py — mints are fresh per call")


if __name__ == "__main__":
    main()

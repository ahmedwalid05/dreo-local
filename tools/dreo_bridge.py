#!/usr/bin/env python3
"""Dreo cloud <-> ESPHome bridge daemon for DR-HCF001S. v2 — stable semantics.

Cloud model (learned live): `fanon` = power flag, `windlevel` = remembered speed
(independent!). Reporting windlevel=0 when off causes an infinite delta loop;
instead report the remembered speed and only zero the power flag.

  - fanon:  true  -> Speed = remembered windlevel
            false -> Speed 0
  - windlevel while fan off -> remember only (no actuation)
  - keys we cannot actuate (mode, muteon, timers...) are mirrored back so the
    desired/reported mismatch never loops
"""
import argparse
import json
import os
import ssl
import tempfile
import time
import urllib.error
import urllib.request

import paho.mqtt.client as mqtt

DEVAPI = "https://device-api-eu.dreo-cloud.com"
CLIENT_ID = os.environ.get("DREO_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("DREO_CLIENT_SECRET", "")
UA = "dreo/hefi 1.0.3"
OCTX = ssl.create_default_context()
OCTX.check_hostname = False
OCTX.verify_mode = ssl.CERT_NONE
ESP = os.environ.get("DREO_FAN_URL", "http://dreo-fan.local")

MIRROR_DEFAULTS = {"scheid": 0, "scheon": False}
# Full DP map (stock 3.5.9 CBOR attr table @0xe0553): dp2=lighton dp3=fanon
# dp4=windlevel dp5=mode(direction) dp6=brightness dp7=colortemp dp0C=muteon.
ACTUATED = ("lighton", "windlevel", "colortemp", "fanon", "brightness", "mode", "muteon")


def log(tag, msg):
    print(f"[{time.strftime('%H:%M:%S')}] {tag}: {msg}", flush=True)


def http_post(url, body, tok=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("content-type", "application/json")
    for k, v in {"accept": "*/*", "user-agent": UA, "ua": UA, "lang": "en-US",
                 **({"authorization": f"Bearer {tok}"} if tok else {})}.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, context=OCTX, timeout=25) as r:
        return json.loads(r.read())


def register(sn, sig, uid, meta):
    d = http_post(f"{DEVAPI}/api/oauth/login?timestamp={int(time.time()*1000)}&lang=en-US",
                  {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                   "grant_type": "device", "scope": "all", "devicesn": sn})
    tok = (d.get("data") or {}).get("access_token")
    if not tok:
        raise RuntimeError(f"oauth failed: {d}")
    r = http_post(f"{DEVAPI}/api/device/activate/emq",
                  {"signature": sig, "userId": uid, "automatic": True, "metaInfo": meta}, tok)
    if r.get("code") != 0:
        raise RuntimeError(f"activate failed: {r}")
    creds = dict(r["data"], sn=sn)
    log("cloud", f"registered OK  {creds['endPoint']}:{creds['port']}")
    return creds


class Bridge:
    def __init__(self, sn, prefix, cl):
        self.sn, self.prefix, self.cl = sn, prefix, cl
        self.remembered_speed = 3
        self.mirror = dict(MIRROR_DEFAULTS)
        self.last_pub = None
        self.last_apply = {}          # key -> ts, rate-limit actuation
        self.suppress_until = 0.0     # ignore deltas for a moment after WE actuate
        self.desired = {}             # cloud desired (tracked to stop revert-ghost)

    # ---- fan side -------------------------------------------------------
    def esp(self, path):
        with urllib.request.urlopen(ESP + path, timeout=8) as r:
            return json.loads(r.read())

    def esp_post(self, path):
        req = urllib.request.Request(ESP + path, method="POST")
        with urllib.request.urlopen(req, timeout=8) as r:
            r.read()

    def read_state(self):
        speed = int(self.esp("/select/Speed")["state"])
        light = self.esp("/switch/Light")["state"] == "ON"
        ct = int(self.esp("/number/Color%20Temp")["state"])
        bri = int(float(self.esp("/number/Brightness")["state"]))
        mode = 4 if self.esp("/select/Direction")["state"] == "Reverse" else 1
        mute = self.esp("/switch/Audio%20Feedback")["state"] == "ON"
        if speed > 0:
            self.remembered_speed = speed
        return {"connected": True, "mcuon": True, "fanon": speed > 0,
                "windlevel": self.remembered_speed, "lighton": light,
                "brightness": bri, "mode": mode, "muteon": mute, "colortemp": ct,
                "mcu_firmware_version": "3.6.4",
                "module_hardware_model": "HeFi",
                "module_firmware_version": "3.8.13",
                "module_hardware_mac": "001cc2a1f659",
                **self.mirror}

    def act(self, key, fn):
        now = time.time()
        if now - self.last_apply.get(key, 0) < 1.0:
            return
        self.last_apply[key] = now
        self.suppress_until = now + 2.0   # our own report may bounce a delta
        fn()

    def apply_desired(self, doc):
        state = doc
        if isinstance(doc, dict) and isinstance(doc.get("state"), dict):
            inner = doc["state"]
            state = inner.get("desired") or inner.get("delta") or inner
        if isinstance(doc, dict) and isinstance(doc.get("params"), dict):
            state = doc["params"]
        if not isinstance(state, dict):
            return
        # A:I: = app-initiated command (never suppress); D:I: = echo of our own report
        token = str(doc.get("clientToken", "")) if isinstance(doc, dict) else ""
        if token.startswith("D:I:") and time.time() < self.suppress_until:
            log("apply", f"suppressed (echo) {json.dumps(state)[:120]}")
            return
        applied = False
        for key, val in state.items():
            if key in ("version", "timestamp", "metadata", "clientToken"):
                continue
            self.desired[key] = val   # consume the desired so we stop defending it
            if key not in ACTUATED:
                self.mirror[key] = val          # cannot actuate: mirror to clear delta
                log("mirror", f"{key}={val}")
                continue
            try:
                if key == "lighton":
                    self.act(key, lambda v=val: self.esp_post(f"/switch/Light/turn_{'on' if v else 'off'}"))
                elif key == "brightness":
                    self.act(key, lambda v=int(val): self.esp_post(f"/number/Brightness/set?value={v}"))
                elif key == "mode":
                    self.act(key, lambda v=int(val): self.esp_post(f"/select/Direction/set?option={'Reverse' if v == 4 else 'Forward'}"))
                elif key == "muteon":
                    self.act(key, lambda v=bool(val): self.esp_post(f"/switch/Audio%20Feedback/turn_{'on' if v else 'off'}"))
                elif key == "fanon":
                    if val:
                        target = self.mirror.get("windlevel", self.remembered_speed)
                        self.act(key, lambda t=target: self.esp_post(f"/select/Speed/set?option={t}"))
                    else:
                        self.act(key, lambda: self.esp_post("/select/Speed/set?option=0"))
                elif key == "windlevel":
                    self.remembered_speed = max(1, int(val))
                    cur = int(self.esp("/select/Speed")["state"])
                    if cur > 0:                  # only actuate a running fan
                        self.act(key, lambda v=int(val): self.esp_post(f"/select/Speed/set?option={v}"))
                elif key == "colortemp":
                    self.act(key, lambda v=int(val): self.esp_post(f"/number/Color%20Temp/set?value={v}"))
                log("apply", f"{key}={val}")
                applied = True
            except Exception as e:
                log("apply", f"{key}={val} failed: {e}")
        if applied:
            # confirm IMMEDIATELY (event-driven) — the app reverts its UI if the
            # state doesn't confirm within ~1-2s of the tap
            time.sleep(0.35)
            try:
                self.publish_state()
            except Exception as e:
                log("pub", f"post-apply publish failed: {e}")

    def publish_state(self):
        cur = self.read_state()
        if cur != self.last_pub:
            align = {k: v for k, v in cur.items() if self.desired.get(k) != v}
            state_block = {"reported": cur}
            if align:
                state_block["desired"] = align
                self.desired.update(align)  # absorbed; don't republish
            payload = {"clientToken": f"D:I:{self.sn}", "state": state_block}
            self.cl.publish(f"{self.prefix}/things/{self.sn}/shadow/update",
                            json.dumps(payload), qos=1)
            # realtime notify channel (feeds the app's websocket push)
            changed = {k: v for k, v in cur.items()
                       if not self.last_pub or self.last_pub.get(k) != v}
            self.cl.publish(f"{self.prefix}/rules/iot_data_rule/{self.sn}",
                            json.dumps({"data": changed}), qos=1)
            log("pub", json.dumps({k: cur[k] for k in
                                   ("fanon", "windlevel", "lighton", "brightness", "colortemp", "mode", "muteon")}))
            self.last_pub = cur
        return cur


def connect(creds, bridge_holder):
    sn, prefix = creds["sn"], creds.get("prefix", "$emq")
    tls = ssl.create_default_context()
    tls.load_verify_locations(os.path.join(os.path.dirname(os.path.abspath(__file__)), "hesung-root-ca.pem"))
    tls.verify_flags &= ~ssl.VERIFY_X509_STRICT
    crt = tempfile.NamedTemporaryFile("w", suffix=".crt", delete=False)
    key = tempfile.NamedTemporaryFile("w", suffix=".key", delete=False)
    crt.write(creds["certificatePem"]); crt.close()
    key.write(creds["privateKey"]); key.close()
    tls.load_cert_chain(crt.name, key.name)

    st = {"conn": False}
    cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=sn, protocol=mqtt.MQTTv311)
    cl.username_pw_set(creds["username"], creds["password"])
    cl.tls_set_context(tls)
    cl.will_set(f"lwt/{sn}", json.dumps({"clientToken": f"D:I:{sn}",
                                         "state": {"reported": {"connected": False}}}), qos=1)

    def on_connect(c, u, f, reason, props):
        st["conn"] = True
        log("mqtt", f"connected: {reason}")
        c.subscribe([(f"{prefix}/things/{sn}/shadow/update/delta", 1),
                     (f"event/{sn}/desired", 1),
                     (f"data/{sn}/desired/schedule", 1),
                     (f"ota/{sn}", 1)])

    def on_message(c, u, m):
        body = m.payload.decode("utf-8", "replace")
        log("recv", f"{m.topic.split('/')[-1]}: {body[:300]}")
        b = bridge_holder.get("b")
        if b and ("delta" in m.topic or "desired" in m.topic):
            try:
                b.apply_desired(json.loads(body))
            except Exception as e:
                log("apply", f"error: {e}")

    def on_disconnect(c, u, f, reason, props):
        st["conn"] = False
        log("mqtt", f"disconnected: {reason}")

    cl.on_connect, cl.on_message, cl.on_disconnect = on_connect, on_message, on_disconnect
    cl.reconnect_delay_set(1, 8)
    cl.connect(creds["endPoint"], int(creds["port"]), keepalive=30)
    cl.loop_start()
    t0 = time.time()
    while not st["conn"] and time.time() - t0 < 20:
        time.sleep(0.2)
    if not st["conn"]:
        cl.loop_stop()
        raise RuntimeError("no CONNACK")
    return cl, st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--license", default="license.json")
    ap.add_argument("--uid", default=os.environ.get("DREO_USER_ID", ""))
    ap.add_argument("--poll", type=float, default=1.0)
    args = ap.parse_args()

    lic = json.load(open(args.license))
    meta = {"moduleHardwareModel": "HeFi", "moduleFirmwareVersion": "3.8.13",
            "mcuHardwareModel": "FP6063U/EU", "mcuFirmwareVersion": "3.6.4"}

    while True:
        cl = None
        try:
            creds = register(lic["sn"], lic["signature"], args.uid, meta)
            holder = {}
            cl, st = connect(creds, holder)
            b = Bridge(lic["sn"], creds.get("prefix", "$emq"), cl)
            holder["b"] = b
            while st["conn"]:
                b.publish_state()
                time.sleep(args.poll)
        except KeyboardInterrupt:
            log("bridge", "bye")
            return
        except Exception as e:
            log("bridge", f"{type(e).__name__}: {e} — re-registering in 8s")
        finally:
            if cl:
                try:
                    cl.disconnect(); cl.loop_stop()
                except Exception:
                    pass
        time.sleep(8)


if __name__ == "__main__":
    main()

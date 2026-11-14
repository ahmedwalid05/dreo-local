"""The proven dreo_bridge daemon, packaged to run inside a HA worker thread.

Semantics are identical to tools/dreo_bridge.py (v2): register -> activate/emq
-> MQTT 3.1.1 with minted client cert -> apply desired -> poll+publish with the
ghost-absorbing desired-alignment block. See ~/projects/dreo/research/.
"""
import json, os, ssl, tempfile, threading, time
import urllib.error, urllib.request

import paho.mqtt.client as mqtt

from .const import ACTUATED, DEVAPI, MIRROR_DEFAULTS, META, UA

CA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hesung-root-ca.pem")


def _log(tag, msg):
    print(f"dreo_app_bridge [{time.strftime('%H:%M:%S')}] {tag}: {msg}", flush=True)


def _post(url, body, tok=None, timeout=25):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    for k, v in {"content-type": "application/json", "accept": "*/*",
                 "user-agent": UA, "ua": UA, "lang": "en-US",
                 **({"authorization": f"Bearer {tok}"} if tok else {})}.items():
        req.add_header(k, v)
    octx = ssl.create_default_context()
    octx.check_hostname = False
    octx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, context=octx, timeout=timeout) as r:
        return json.loads(r.read())


def register(devapi, sn, sig, uid, client_id, client_secret):
    d = _post(f"{devapi}/api/oauth/login?timestamp={int(time.time()*1000)}&lang=en-US",
              {"client_id": client_id, "client_secret": client_secret,
               "grant_type": "device", "scope": "all", "devicesn": sn})
    tok = (d.get("data") or {}).get("access_token")
    if not tok:
        raise RuntimeError(f"oauth failed: {d}")
    r = _post(f"{devapi}/api/device/activate/emq",
              {"signature": sig, "userId": uid, "automatic": True, "metaInfo": META}, tok)
    if r.get("code") != 0:
        raise RuntimeError(f"activate failed: {r}")
    creds = dict(r["data"], sn=sn)
    _log("cloud", f"registered OK {creds['endPoint']}:{creds['port']}")
    return creds


class Bridge:
    def __init__(self, esp, sn, prefix, cl):
        self.esp_base, self.sn, self.prefix, self.cl = esp, sn, prefix, cl
        self.remembered_speed = 3
        self.mirror = dict(MIRROR_DEFAULTS)
        self.last_pub = None
        self.last_apply = {}
        self.suppress_until = 0.0
        self.desired = {}

    def esp(self, path):
        with urllib.request.urlopen(self.esp_base + path, timeout=8) as r:
            return json.loads(r.read())

    def esp_post(self, path):
        req = urllib.request.Request(self.esp_base + path, method="POST")
        urllib.request.urlopen(req, timeout=8).read()

    def act(self, key, fn):
        now = time.time()
        if now - self.last_apply.get(key, 0) < 1.0:
            return
        self.last_apply[key] = now
        fn()

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
                **{k: self.mirror.get(k, v) for k, v in
                   MIRROR_DEFAULTS.items()}}

    def apply_desired(self, doc):
        state = doc
        if isinstance(doc, dict) and isinstance(doc.get("state"), dict):
            inner = doc["state"]
            state = inner.get("desired") or inner.get("delta") or inner
        if isinstance(doc, dict) and isinstance(doc.get("params"), dict):
            state = doc["params"]
        if not isinstance(state, dict):
            return
        token = str(doc.get("clientToken", "")) if isinstance(doc, dict) else ""
        if token.startswith("D:I:") and time.time() < self.suppress_until:
            _log("apply", f"suppressed (echo) {json.dumps(state)[:120]}")
            return
        applied = False
        for key, val in state.items():
            if key in ("version", "timestamp", "metadata", "clientToken"):
                continue
            self.desired[key] = val
            if key not in ACTUATED:
                self.mirror[key] = val
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
                        t = self.mirror.get("windlevel", self.remembered_speed)
                        self.act(key, lambda t=t: self.esp_post(f"/select/Speed/set?option={t}"))
                    else:
                        self.act(key, lambda: self.esp_post("/select/Speed/set?option=0"))
                elif key == "windlevel":
                    self.remembered_speed = max(1, int(val))
                    if int(self.esp("/select/Speed")["state"]) > 0:
                        self.act(key, lambda v=int(val): self.esp_post(f"/select/Speed/set?option={v}"))
                elif key == "colortemp":
                    self.act(key, lambda v=int(val): self.esp_post(f"/number/Color%20Temp/set?value={v}"))
                _log("apply", f"{key}={val}")
                applied = True
            except Exception as e:
                _log("apply", f"{key}={val} failed: {e}")
        if applied:
            time.sleep(0.35)
            try:
                self.publish_state()
            except Exception as e:
                _log("pub", f"post-apply publish failed: {e}")

    def publish_state(self):
        cur = self.read_state()
        if cur != self.last_pub:
            align = {k: v for k, v in cur.items() if self.desired.get(k) != v}
            state_block = {"reported": cur}
            if align:
                state_block["desired"] = align
                self.desired.update(align)
            payload = {"clientToken": f"D:I:{self.sn}", "state": state_block}
            self.cl.publish(f"{self.prefix}/things/{self.sn}/shadow/update",
                            json.dumps(payload), qos=1)
            changed = {k: v for k, v in cur.items()
                       if not self.last_pub or self.last_pub.get(k) != v}
            self.cl.publish(f"{self.prefix}/rules/iot_data_rule/{self.sn}",
                            json.dumps({"data": changed}), qos=1)
            _log("pub", json.dumps({k: cur[k] for k in
                                    ("fanon", "windlevel", "lighton", "brightness",
                                     "colortemp", "mode", "muteon")}))
            self.last_pub = cur
        return cur


def connect(creds, bridge_holder):
    sn, prefix = creds["sn"], creds.get("prefix", "$emq")
    tls = ssl.create_default_context()
    tls.load_verify_locations(CA)
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
        _log("mqtt", f"connected: {reason}")
        c.subscribe([(f"{prefix}/things/{sn}/shadow/update/delta", 1),
                     (f"event/{sn}/desired", 1),
                     (f"data/{sn}/desired/schedule", 1),
                     (f"ota/{sn}", 1)])

    def on_message(c, u, m):
        body = m.payload.decode("utf-8", "replace")
        _log("recv", f"{m.topic.split('/')[-1]}: {body[:300]}")
        b = bridge_holder.get("b")
        if b and ("delta" in m.topic or "desired" in m.topic):
            try:
                b.apply_desired(json.loads(body))
            except Exception as e:
                _log("apply", f"error: {e}")

    def on_disconnect(c, u, f, reason, props):
        st["conn"] = False
        _log("mqtt", f"disconnected: {reason}")

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


def run_bridge(devapi, esp, lic, uid, client_id, client_secret,
               stop: threading.Event, status: dict, poll=1.0):
    """Thread target: the daemon loop. Updates status for the HA entity."""
    while not stop.is_set():
        cl = None
        try:
            status.update(state="registering", error=None)
            creds = register(devapi, lic["sn"], lic["signature"], uid,
                             client_id, client_secret)
            holder = {}
            cl, st = connect(creds, holder)
            b = Bridge(esp, lic["sn"], creds.get("prefix", "$emq"), cl)
            holder["b"] = b
            status.update(state="connected", error=None, sn=lic["sn"])
            while st["conn"] and not stop.is_set():
                b.publish_state()
                stop.wait(poll)
        except Exception as e:
            status.update(state="error", error=f"{type(e).__name__}: {e}")
            _log("bridge", f"{type(e).__name__}: {e} — re-registering in 8s")
            stop.wait(8)
        finally:
            if cl:
                try:
                    cl.loop_stop(); cl.disconnect()
                except Exception:
                    pass
    status.update(state="stopped")

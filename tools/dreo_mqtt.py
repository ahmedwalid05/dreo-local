#!/usr/bin/env python3
"""Connect to the Dreo device-MQTT broker as a registered device and report status.

PROVEN AUTH FORMULA (2026-11-04):
  TLS (HESUNG ROOT CA) + client cert from register + username/password from
  register + MQTT 3.1.1 + clientId = <SN>.  → CONNACK Success, shadow publishes
  land in the app realm within seconds (verified via /api/user-device/device/state).

Input: creds json written by dreo_register.py ({sn, endPoint, port, username,
password, certificatePem, privateKey, prefix, …}).

Topics (prefix from creds, usually "$emq"):
  pub  {prefix}/things/{sn}/shadow/update
  sub  {prefix}/things/{sn}/shadow/update/delta | /accepted
       event/{sn}/desired, data/{sn}/desired/schedule, ota/{sn}

Shadow report format:
  {"clientToken":"D:I:{sn}","state":{"reported":{…}}}

Usage:
  dreo_mqtt.py creds.json [--report '{"windlevel":3}'] [--seconds 30] [--insecure]
"""
import argparse
import json
import os
import ssl
import sys
import tempfile
import time

import paho.mqtt.client as mqtt

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("creds_json")
    ap.add_argument("--report", default=None, help="JSON reported-state")
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--insecure", action="store_true")
    args = ap.parse_args()

    d = json.load(open(args.creds_json))
    sn = d["sn"]
    prefix = d.get("prefix", "$emq")
    host, port = d["endPoint"], int(d.get("port", 8883))

    tls = ssl.create_default_context()
    if args.insecure:
        tls.check_hostname = False
        tls.verify_mode = ssl.CERT_NONE
    else:
        ca = os.path.join(HERE, "hesung-root-ca.pem")
        tls.load_verify_locations(ca)   # broker serves *.dreo-cloud.com signed by HESUNG ROOT CA
        # broker leaf lacks an Authority Key Identifier ext; python>=3.13 strict
        # verification rejects it — openssl itself is happy with this chain
        tls.verify_flags &= ~ssl.VERIFY_X509_STRICT

    # client cert is REQUIRED (username+password alone → silent CONNECT drop)
    crt = tempfile.NamedTemporaryFile("w", suffix=".crt", delete=False)
    key = tempfile.NamedTemporaryFile("w", suffix=".key", delete=False)
    crt.write(d["certificatePem"]); crt.close()
    key.write(d["privateKey"]); key.close()
    tls.load_cert_chain(crt.name, key.name)

    cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=sn, protocol=mqtt.MQTTv311)
    cl.username_pw_set(d["username"], d["password"])
    cl.tls_set_context(tls)

    state = {"conn": False, "got": 0}

    def on_connect(c, u, f, reason, props):
        state["conn"] = True
        print(f"[conn] {reason}")
        topics = [(f"{prefix}/things/{sn}/shadow/update/delta", 1),
                  (f"{prefix}/things/{sn}/shadow/update/accepted", 1),
                  (f"event/{sn}/desired", 1),
                  (f"data/{sn}/desired/schedule", 1),
                  (f"ota/{sn}", 1)]
        c.subscribe(topics)

    def on_message(c, u, m):
        state["got"] += 1
        print(f"[msg] {m.topic}: {m.payload.decode('utf-8','replace')[:600]}")

    def on_disconnect(c, u, f, reason, props):
        if not state["conn"]:
            print(f"[drop pre-CONNACK] {reason}")

    cl.on_connect, cl.on_message, cl.on_disconnect = on_connect, on_message, on_disconnect
    cl.reconnect_delay_set(1, 4)

    print(f"connecting {host}:{port} clientId={sn} user={d['username']} prefix={prefix}")
    cl.connect(host, port, keepalive=30)
    cl.loop_start()

    deadline = time.time() + args.seconds
    while not state["conn"] and time.time() < deadline - 5:
        time.sleep(0.3)

    if not state["conn"]:
        print("NO CONNACK — creds likely stale (each register mint invalidates the last); "
              "re-run dreo_register.py and connect immediately")
        cl.loop_stop()
        return 1

    if args.report is not None:
        payload = {"clientToken": f"D:I:{sn}", "state": {"reported": json.loads(args.report)}}
        topic = f"{prefix}/things/{sn}/shadow/update"
        i = cl.publish(topic, json.dumps(payload), qos=1)
        i.wait_for_publish(10)
        print(f"[pub] {topic} rc={i.rc} {json.dumps(payload)}")

    time.sleep(max(3, min(args.seconds, 25)))
    cl.disconnect(); cl.loop_stop()
    os.unlink(crt.name); os.unlink(key.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())

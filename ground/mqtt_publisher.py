#!/usr/bin/env python3
"""Publish KU-SIRAJ 1 telemetry to MQTT so the hosted dashboard updates live.

    py mqtt_publisher.py --serial COM5          forward ESP32 JSON lines from USB serial
    py mqtt_publisher.py --simulate             synthetic orbit (marked simulated)
    py mqtt_publisher.py --simulate --faults    synthetic orbit that cycles through the fault tests
    py mqtt_publisher.py --replay ..\\examples\\sample-orbit.jsonl

Data path: ESP32 -> USB serial -> this script -> MQTT broker -> dashboard (any browser, via the link).
The script only publishes; it never sends anything back to the ESP32.

The default broker is HiveMQ's free public test broker. Anyone who knows the topic can read or
write it, so use it for testing and demos only, and never send secrets over it.
"""
import argparse
import json
import logging
import sys
import threading
import time
import uuid

import paho.mqtt.client as mqtt

from telemetry import OrbitSimulator, now_iso, parse_packet

LOG = logging.getLogger("ku_siraj_mqtt")
FAULT_CYCLE = [(20, "drain", "battery falling"), (45, "clear", None), (60, "spike", "temperature spike"),
               (90, "clear", None), (105, "link", "link lost 12 s"), (130, "sensor", "temperature sensor null"),
               (150, "clear", None)]


def make_client(client_id):
    try:  # paho-mqtt 2.x
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    except AttributeError:  # paho-mqtt 1.x
        return mqtt.Client(client_id=client_id)


class Publisher:
    def __init__(self, args):
        self.args = args
        base = args.topic[: -len("/telemetry")] if args.topic.endswith("/telemetry") else args.topic
        self.status_topic = base + "/status"
        self.connected = threading.Event()
        self.sent = 0
        self.client = make_client("ku-siraj-pub-" + uuid.uuid4().hex[:8])
        self.client.will_set(self.status_topic, json.dumps({"state": "offline", "at": now_iso()}), qos=1, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        if args.tls:
            self.client.tls_set()

    def _on_connect(self, client, userdata, flags, *rest):
        reason = rest[0] if rest else 0
        ok = getattr(reason, "is_failure", None)
        failed = ok if ok is not None else (reason != 0)
        if failed:
            LOG.warning("Broker refused the connection: %s", reason)
            return
        self.connected.set()
        LOG.info("Connected to %s:%s; publishing on %s", self.args.broker, self.args.port, self.args.topic)
        client.publish(self.status_topic, json.dumps({"state": "online", "source": self.args.source_label, "at": now_iso()}), qos=1, retain=True)

    def _on_disconnect(self, client, userdata, *rest):
        self.connected.clear()
        LOG.warning("Disconnected from broker; paho will reconnect automatically.")

    def start(self):
        while True:
            try:
                self.client.connect(self.args.broker, self.args.port, keepalive=30)
                break
            except OSError as exc:
                LOG.warning("Cannot reach %s:%s (%s). Retrying in 5 s.", self.args.broker, self.args.port, exc)
                time.sleep(5)
        self.client.loop_start()
        self.connected.wait(timeout=10)

    def publish(self, packet):
        if not self.connected.is_set():
            LOG.warning("Not connected; packet %s dropped.", packet.get("packet_id", "?"))
            return
        body = json.dumps(packet, separators=(",", ":"), allow_nan=False)
        # retain=True: someone opening the dashboard sees the latest packet straight away (with its age).
        self.client.publish(self.args.topic, body, qos=0, retain=True)
        self.sent += 1
        if self.sent % 10 == 1:
            LOG.info("Published packet %s (%d sent)", packet.get("packet_id", "?"), self.sent)

    def stop(self):
        try:
            if self.connected.is_set():
                info = self.client.publish(self.status_topic, json.dumps({"state": "offline", "at": now_iso()}), qos=1, retain=True)
                info.wait_for_publish(timeout=2)
        finally:
            self.client.loop_stop()
            self.client.disconnect()


def run_serial(pub, args):
    import serial  # pyserial
    import serial.tools.list_ports

    port = args.serial
    if port == "auto":
        keys = ("esp32", "cp210", "ch340", "ftdi", "usb serial", "usb-serial")
        found = [p.device for p in serial.tools.list_ports.comports() if any(k in (p.description or "").lower() for k in keys)]
        if not found:
            sys.exit("No ESP32 serial port found. Pass it explicitly, e.g. --serial COM5")
        port = found[0]
    while True:
        try:
            with serial.Serial(port, args.baudrate, timeout=1) as ser:
                LOG.info("Reading %s at %s baud", port, args.baudrate)
                while True:
                    line = ser.readline()
                    if not line:
                        continue
                    packet = parse_packet(line, default_device=args.device_id, default_source="ESP32 via USB serial")
                    if packet:
                        pub.publish(packet)
                    else:
                        text = line.decode("utf-8", errors="replace").strip()
                        if text:
                            LOG.info("Device: %s", text[:200])
        except (serial.SerialException, OSError) as exc:
            LOG.warning("Serial error on %s: %s. Retrying in 3 s.", port, exc)
            time.sleep(3)


def run_simulate(pub, args):
    sim = OrbitSimulator(device_id=args.device_id + "-sim")
    step = 0
    while True:
        if args.faults:
            for at, name, label in FAULT_CYCLE:
                if step % 160 == at:
                    sim.fault(name)
                    LOG.info("Fault: %s", label or "cleared")
        packet = sim.next()
        if packet:
            pub.publish(packet)
        step += 1
        time.sleep(args.interval)


def run_replay(pub, args):
    with open(args.replay, encoding="utf-8") as fh:
        rows = [r for r in (parse_packet(line, default_device=args.device_id) for line in fh) if r]
    if not rows:
        sys.exit("No packets found in " + args.replay)
    LOG.info("Replaying %d packets from %s with fresh timestamps.", len(rows), args.replay)
    for r in rows:
        r["timestamp"] = now_iso()
        pub.publish(r)
        time.sleep(args.interval)


def main():
    ap = argparse.ArgumentParser(description="Publish KU-SIRAJ 1 telemetry to MQTT for the live dashboard.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--serial", metavar="PORT", help="ESP32 serial port, e.g. COM5, or 'auto'")
    src.add_argument("--simulate", action="store_true", help="publish simulated orbit packets")
    src.add_argument("--replay", metavar="FILE", help="publish a .jsonl log, one packet per line")
    ap.add_argument("--faults", action="store_true", help="with --simulate: cycle through the fault tests")
    ap.add_argument("--broker", default="broker.hivemq.com")
    ap.add_argument("--port", type=int, default=None, help="1883 (default) or 8883 with --tls")
    ap.add_argument("--tls", action="store_true", help="encrypt the connection (port 8883)")
    ap.add_argument("--topic", default="ku-shihab/ku-siraj-1/telemetry")
    ap.add_argument("--device-id", default="ku-siraj-1")
    ap.add_argument("--baudrate", type=int, default=115200)
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between packets (simulate/replay)")
    args = ap.parse_args()
    args.port = args.port or (8883 if args.tls else 1883)
    args.source_label = "serial " + args.serial if args.serial else "simulator" if args.simulate else "replay"

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    pub = Publisher(args)
    pub.start()
    try:
        if args.serial:
            run_serial(pub, args)
        elif args.simulate:
            run_simulate(pub, args)
        else:
            run_replay(pub, args)
    except KeyboardInterrupt:
        LOG.info("Stopping.")
    finally:
        pub.stop()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Local read-only telemetry bridge for the KU-SIRAJ 1 ground dashboard.

The dashboard connects to this process over a loopback WebSocket. The bridge
reads newline-delimited JSON telemetry from USB serial; it never sends control
commands to the ESP32 or switches any power path.
"""
import argparse
import asyncio
import json
import logging
import math
import re
import threading
import time
from datetime import datetime, timezone

import serial
import serial.tools.list_ports
import websockets

LOG = logging.getLogger("ku_siraj_bridge")
from telemetry import now_iso, parse_packet as parse_contract_packet


class GroundStationBridge:
    def __init__(self, serial_port=None, baudrate=115200):
        self.requested_port = serial_port
        self.baudrate = baudrate
        self.clients = set()
        self.latest_packet = None
        self.latest_signature = None
        self.serial_connection = None
        self.serial_connected = False
        self.serial_port_name = None
        self.running = False
        self.lock = threading.Lock()

    @staticmethod
    def find_serial_port():
        candidates = serial.tools.list_ports.comports()
        keywords = ("esp32", "arduino", "ch340", "cp210", "ftdi", "usb serial")
        for port in candidates:
            description = (port.description or "").lower()
            if any(keyword in description for keyword in keywords):
                return port.device
        return None

    @staticmethod
    def parse_packet(line):
        line = line.strip()
        if not line or len(line) > 8192:
            return None
        if line.startswith("<TELEMETRY>"):
            return GroundStationBridge.parse_legacy_cansat(line)
        packet = parse_contract_packet(line, default_source="USB serial")
        if packet is None:
            return None
        # Raw serial readings are real unless the firmware or an emulator says otherwise.
        return packet

    @staticmethod
    def parse_legacy_cansat(line):
        """Best-effort compatibility with the old XML-tagged CanSat packets.

        Only temperature and packet identity map cleanly to this mission.
        GPS, altitude, descent, pressure and IMU values are deliberately
        discarded instead of being relabeled as KU-SIRAJ measurements.
        """
        if not line.startswith("<TELEMETRY>") or not line.endswith("</TELEMETRY>"):
            return None

        def tag(name):
            match = re.search(r"<" + re.escape(name) + r":([^>]+)>", line)
            return match.group(1).strip() if match else None

        packet = {
            "timestamp": now_iso(),
            "telemetry_source": "Legacy CanSat serial (partial mapping)",
            "operating_mode": "LEGACY_PACKET",
            "legacy_format": True,
            "simulated": False,
        }
        packet_id = tag("PacketID")
        temperature = tag("Temp")
        try:
            if packet_id is not None:
                packet["packet_id"] = max(0, int(packet_id))
        except (TypeError, ValueError, OverflowError):
            pass
        try:
            if temperature is not None:
                value = float(temperature)
                if math.isfinite(value):
                    packet["temperature_c"] = value
        except (TypeError, ValueError, OverflowError):
            pass
        return packet if "packet_id" in packet or "temperature_c" in packet else None

    def set_latest(self, packet):
        signature = (packet.get("packet_id"), packet.get("timestamp"))
        with self.lock:
            self.latest_packet = packet
            self.latest_signature = signature

    def serial_reader(self):
        while self.running:
            if self.serial_connection is None:
                port = self.requested_port or self.find_serial_port()
                if not port:
                    time.sleep(2)
                    continue
                try:
                    self.serial_connection = serial.Serial(
                        port, self.baudrate, timeout=1, write_timeout=1
                    )
                    self.serial_port_name = port
                    self.serial_connected = True
                    LOG.info("Serial connected: %s at %s baud", port, self.baudrate)
                except (serial.SerialException, OSError) as exc:
                    self.serial_connected = False
                    self.serial_connection = None
                    LOG.warning("Serial connection unavailable on %s: %s", port, exc)
                    time.sleep(3)
                    continue

            try:
                raw_line = self.serial_connection.readline()
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                packet = self.parse_packet(line)
                if packet:
                    self.set_latest(packet)
                    LOG.info(
                        "Telemetry packet %s received from %s",
                        packet.get("packet_id", "?"),
                        self.serial_port_name,
                    )
                elif line.startswith("<STATUS>") or line.startswith("<SYSTEM>"):
                    LOG.info("Device message: %s", line[:300])
            except (serial.SerialException, OSError) as exc:
                LOG.warning("Serial read failed: %s", exc)
                try:
                    self.serial_connection.close()
                except Exception:
                    pass
                self.serial_connection = None
                self.serial_connected = False
                self.serial_port_name = None
                time.sleep(2)
            except Exception:
                LOG.exception("Unexpected serial reader error")
                time.sleep(1)

    def status_packet(self):
        return {
            "type": "status",
            "serial_connected": bool(self.serial_connected),
            "serial_port": self.serial_port_name,
            "dashboard": "KU-SIRAJ 1",
            "commands_enabled": False,
            "timestamp": now_iso(),
        }

    async def handle_websocket(self, websocket, path=None):
        self.clients.add(websocket)
        LOG.info("Dashboard connected (%d client(s))", len(self.clients))
        try:
            await websocket.send(json.dumps(self.status_packet()))
            async for message in websocket:
                # The dashboard is intentionally read-only. Ignore client messages.
                LOG.debug("Ignored dashboard message (%d bytes)", len(message))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)
            LOG.info("Dashboard disconnected (%d client(s))", len(self.clients))

    async def broadcaster(self):
        last_signature = None
        while self.running:
            with self.lock:
                packet = self.latest_packet
                signature = self.latest_signature
            if packet is not None and signature != last_signature:
                message = json.dumps(packet, allow_nan=False)
                disconnected = []
                for client in tuple(self.clients):
                    try:
                        await client.send(message)
                    except websockets.exceptions.ConnectionClosed:
                        disconnected.append(client)
                    except Exception:
                        LOG.exception("WebSocket delivery failed")
                        disconnected.append(client)
                for client in disconnected:
                    self.clients.discard(client)
                last_signature = signature
            await asyncio.sleep(0.15)

    async def run(self, host, port):
        self.running = True
        serial_thread = threading.Thread(
            target=self.serial_reader, name="ku-siraj-serial", daemon=True
        )
        serial_thread.start()
        LOG.info("Dashboard bridge listening at ws://%s:%s", host, port)
        LOG.info("No telemetry is fabricated by the bridge; missing channels stay absent.")
        async with websockets.serve(self.handle_websocket, host, port, max_size=8192):
            broadcaster_task = asyncio.create_task(self.broadcaster())
            try:
                await asyncio.Future()
            finally:
                self.running = False
                broadcaster_task.cancel()
                if self.serial_connection:
                    self.serial_connection.close()
                serial_thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description="KU-SIRAJ 1 local ground-station bridge")
    parser.add_argument("--port", type=int, default=8000, help="Local WebSocket port (default: 8000)")
    parser.add_argument("--serial-port", default=None, help="ESP32 serial port, e.g. COM3; auto-detect if omitted")
    parser.add_argument("--baudrate", type=int, default=115200, help="ESP32 serial baud rate")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address; loopback only by default")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    bridge = GroundStationBridge(args.serial_port, args.baudrate)
    try:
        asyncio.run(bridge.run(args.host, args.port))
    except KeyboardInterrupt:
        LOG.info("Ground-station bridge stopped.")


if __name__ == "__main__":
    main()

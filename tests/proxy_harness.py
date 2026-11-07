"""Loopback TCP peers for proxy tests. No Growatt host is contacted."""

import socket
import threading
import time

import paho.mqtt.client as mqtt

from tests.conftest import MQTT_HOST, MQTT_PORT


def _listen(host="127.0.0.1"):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, 0))
    sock.listen(1)
    sock.settimeout(0.4)
    return sock


class Upstream:
    """Accepts one proxy connection and records the first payload."""

    def __init__(self):
        self.sock = _listen()
        self.port = self.sock.getsockname()[1]
        self.accepted = threading.Event()
        self.done = threading.Event()
        self.payload = b""
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        conn = None
        deadline = time.time() + 8
        try:
            while time.time() < deadline and not self._stop.is_set():
                if conn is None:
                    try:
                        conn, _ = self.sock.accept()
                        conn.settimeout(0.4)
                        self.accepted.set()
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                else:
                    try:
                        chunk = conn.recv(8192)
                    except socket.timeout:
                        if self.payload:
                            break
                        continue
                    if not chunk:
                        break
                    self.payload += chunk
        finally:
            if conn is not None:
                try:
                    conn.close()
                except OSError:
                    pass
            try:
                self.sock.close()
            except OSError:
                pass
            self.done.set()

    def stop(self):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass
        self.thread.join(timeout=2)


class MqttCatcher:
    def __init__(self, topic):
        self.topic = topic
        self.messages = []
        self.connected = threading.Event()
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="grott-proxy-" + str(time.time_ns()),
        )
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        self.client.loop_start()
        if not self.connected.wait(5):
            raise RuntimeError("MQTT catcher failed to connect")

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        client.subscribe(self.topic, qos=0)
        self.connected.set()

    def _on_message(self, client, userdata, message):
        self.messages.append((message.topic, message.payload, bool(message.retain)))

    def wait(self, timeout=3, count=1):
        deadline = time.time() + timeout
        while time.time() < deadline and len(self.messages) < count:
            time.sleep(0.05)
        return list(self.messages)

    def close(self):
        self.client.loop_stop()
        try:
            self.client.disconnect()
        except Exception:
            pass


def run_proxy(conf, payload, topic, upstream_wait=1.5, gap=0.0, mqtt_count=1):
    """Drive one client record through Proxy against a fake upstream."""
    from grottproxy import Proxy

    Proxy.input_list = []
    Proxy.channel = {}
    upstream = Upstream()
    catcher = MqttCatcher(topic)
    conf.growattip = "127.0.0.1"
    conf.growattport = upstream.port
    conf.grottip = "127.0.0.1"
    conf.grottport = 0
    conf.mqttip = MQTT_HOST
    conf.mqttport = MQTT_PORT
    conf.mqtttopic = topic
    conf.minrecl = 100
    errors = []

    proxy = Proxy(conf)
    listen_port = proxy.server.getsockname()[1]

    def _main():
        try:
            proxy.main(conf)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=_main, daemon=True)
    thread.start()
    client = socket.create_connection(("127.0.0.1", listen_port), timeout=5)
    chunks = payload if isinstance(payload, (list, tuple)) else [payload]
    try:
        for index, chunk in enumerate(chunks):
            if index and gap:
                time.sleep(gap)
            client.sendall(chunk)
        messages = catcher.wait(timeout=upstream_wait, count=mqtt_count)
        time.sleep(0.3)
    finally:
        try:
            client.close()
        except OSError:
            pass
        proxy.stop()
        thread.join(timeout=2)
        upstream.stop()
        catcher.close()
        Proxy.input_list = []
        Proxy.channel = {}
    return {
        "upstream": upstream.payload,
        "accepted": upstream.accepted.is_set(),
        "mqtt": messages,
        "errors": errors,
    }

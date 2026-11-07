#!/usr/bin/env python3
"""Run the isolated Compose profile and a separate MQTT test overlay.

The shipped profile is docker/docker-compose.isolated.yml. It is not modified
by this script. The MQTT overlay is docker/docker-compose.isolated-mqtt-test.yml
and is explicitly not the shipped profile: MQTT is on, noforward stays on, and
the broker is only reachable on an internal Compose network.

Ephemeral files live under /tmp/grott-isolated-verify and are deleted at the
end. Nothing here contacts server.growatt.com, a Home Assistant broker, or a
physical inverter.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKER = ["docker"]
RUNTIME = Path("/tmp/grott-isolated-verify")
SHIPPED = ROOT / "docker" / "docker-compose.isolated.yml"
OVERLAY = ROOT / "docker" / "docker-compose.isolated-mqtt-test.yml"
SAMPLE_HEX_PATH = ROOT / "tests" / "vectors.py"


def ensure_docker():
    global DOCKER
    for prefix in (["docker"], ["sudo", "docker"]):
        probe = subprocess.run(
            [*prefix, "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if probe.returncode == 0:
            DOCKER = prefix
            return
    raise SystemExit("docker daemon is not usable")


def run(cmd, check=True, timeout=180):
    print("+", " ".join(cmd), flush=True)
    completed = subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if completed.stdout:
        sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    if check and completed.returncode != 0:
        raise SystemExit(completed.returncode)
    return completed


def compose(project, filename, *args, check=True, timeout=180):
    return run(
        [*DOCKER, "compose", "-p", project, "-f", str(filename), *args],
        check=check,
        timeout=timeout,
    )


def load_sample():
    namespace = {}
    exec(SAMPLE_HEX_PATH.read_text(encoding="utf-8"), namespace)
    return bytes.fromhex(namespace["UPSTREAM_GROTTTEST_HEX"])


def wait_healthy(container, timeout_s=40):
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        completed = run(
            [*DOCKER, "inspect", "-f", "{{.State.Health.Status}}", container],
            check=False,
            timeout=20,
        )
        last = (completed.stdout or completed.stderr).strip()
        if last == "healthy":
            return last
        time.sleep(1)
    raise SystemExit("container %s health stayed %r" % (container, last))


def published_ports(container):
    """Host bindings only. An image EXPOSE with a null binding is not a publish."""
    completed = run(
        [*DOCKER, "inspect", "-f", "{{json .NetworkSettings.Ports}}", container],
        timeout=20,
    )
    raw = completed.stdout.strip()
    if raw in ("", "null"):
        return {}
    parsed = json.loads(raw) or {}
    return {port: bindings for port, bindings in parsed.items() if bindings}


def host_port_list(container):
    completed = run([*DOCKER, "port", container], check=False, timeout=20)
    return (completed.stdout or "").strip()


def assert_loopback_listen(container):
    completed = exec_python(
        container,
        "print(open('/proc/net/tcp', encoding='utf-8').read())",
        timeout=15,
    )
    text = completed.stdout or ""
    loopback = "0100007F:149F"
    wildcard = "00000000:149F"
    if loopback not in text:
        raise SystemExit("grott is not listening on 127.0.0.1:5279\n%s" % text)
    if wildcard in text:
        raise SystemExit("grott is listening on 0.0.0.0:5279\n%s" % text)
    return loopback


def host_cannot_connect():
    probe = socket.socket()
    probe.settimeout(1)
    try:
        probe.connect(("127.0.0.1", 5279))
    except OSError as exc:
        return type(exc).__name__, getattr(exc, "errno", None), str(exc)
    else:
        raise SystemExit("host reached 127.0.0.1:5279; a port is published or shared")
    finally:
        probe.close()


def exec_python(container, code, stdin=None, timeout=20):
    cmd = [*DOCKER, "exec", "-i", container, "python", "-c", code]
    print("+", " ".join(cmd), flush=True)
    completed = subprocess.run(
        cmd,
        input=stdin,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    print(completed.stdout)
    print(completed.stderr, file=sys.stderr)
    return completed


def egress_from(container):
    code = (
        "import socket\n"
        "s=socket.socket(); s.settimeout(3)\n"
        "try:\n"
        "    s.connect(('1.1.1.1', 443))\n"
        "    print('EGRESS_OPEN')\n"
        "except OSError as exc:\n"
        "    print('EGRESS_BLOCKED %s %s' % (exc.errno, exc.strerror))\n"
        "finally:\n"
        "    s.close()\n"
        "print('ROUTE')\n"
        "print(open('/proc/net/route', encoding='utf-8').read())\n"
    )
    completed = exec_python(container, code, timeout=15)
    text = (completed.stdout or "") + (completed.stderr or "")
    if "EGRESS_OPEN" in text:
        raise SystemExit("egress to 1.1.1.1:443 succeeded from %s" % container)
    if "EGRESS_BLOCKED" not in text:
        raise SystemExit("egress probe produced no result from %s: %s" % (container, text))
    route = text.split("ROUTE", 1)[-1].strip()
    return text.split("ROUTE", 1)[0].strip(), route


def inject_sample(container, sample, sessions=2):
    code = (
        "import socket, sys, time\n"
        "payload = sys.stdin.buffer.read()\n"
        "for n in range(%d):\n"
        "    s=socket.create_connection(('127.0.0.1', 5279), 5)\n"
        "    s.sendall(payload)\n"
        "    time.sleep(0.4)\n"
        "    s.close()\n"
        "    time.sleep(0.4)\n"
        "print('injected', len(payload), 'bytes', %d, 'sessions')\n"
        % (sessions, sessions)
    )
    completed = subprocess.run(
        [*DOCKER, "exec", "-i", container, "python", "-c", code],
        input=sample,
        capture_output=True,
        timeout=20,
        check=False,
    )
    sys.stdout.buffer.write(completed.stdout)
    sys.stderr.buffer.write(completed.stderr)
    if completed.returncode != 0:
        raise SystemExit("sample injection into %s failed" % container)


def logs(container):
    completed = run([*DOCKER, "logs", container], check=False, timeout=20)
    return (completed.stdout or "") + (completed.stderr or "")


def assert_no_secret(text, secret):
    if secret and secret in text:
        raise SystemExit("ephemeral secret appeared in command output or logs")


def prepare_runtime(secret):
    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    RUNTIME.mkdir(mode=0o700)
    password_path = RUNTIME / "mqtt_password"
    password_path.write_text(secret + "\n", encoding="utf-8")
    os.chmod(password_path, 0o600)
    passwd = RUNTIME / "passwd"
    subprocess.check_call(
        ["mosquitto_passwd", "-c", "-b", str(passwd), "grott-test", secret],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.check_call(["sudo", "chown", "1883:1883", str(passwd)])
    subprocess.check_call(["sudo", "chmod", "600", str(passwd)])
    (RUNTIME / "mosquitto.conf").write_text(
        "listener 1883 127.0.0.1\nallow_anonymous false\npassword_file /mosquitto/config/passwd\npersistence false\n",
        encoding="utf-8",
    )
    (RUNTIME / "grott.ini").write_text(
        "\n".join(
            [
                "[Generic]",
                "verbose = True",
                "mode = proxy",
                "ip = 127.0.0.1",
                "port = 5279",
                "blockcmd = True",
                "noforward = True",
                "sendbuf = False",
                "minrecl = 100",
                "[Growatt]",
                "ip = server.growatt.com",
                "port = 5279",
                "[MQTT]",
                "nomqtt = False",
                "ip = 127.0.0.1",
                "port = 1883",
                "topic = energy/growatt",
                "auth = True",
                "user = grott-test",
                "[PVOutput]",
                "pvoutput = False",
                "[influx]",
                "influx = False",
                "influx2 = False",
                "[extension]",
                "extension = False",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (RUNTIME / "watch.py").write_text(
        "\n".join(
            [
                "import time",
                "import paho.mqtt.client as mqtt",
                "password = open('/verify/mqtt_password', encoding='utf-8').read().strip()",
                "def on_connect(client, userdata, flags, reason_code, properties):",
                "    client.subscribe('energy/growatt/#', qos=0)",
                "    open('/verify/watch-ready', 'w', encoding='utf-8').write('ok')",
                "def on_message(client, userdata, message):",
                "    with open('/verify/mqtt-received.jsonl', 'a', encoding='utf-8') as handle:",
                "        handle.write(message.payload.decode('utf-8') + '\\n')",
                "client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='grott-verify-watch')",
                "client.username_pw_set('grott-test', password)",
                "client.on_connect = on_connect",
                "client.on_message = on_message",
                "deadline = time.time() + 30",
                "while True:",
                "    try:",
                "        client.connect('127.0.0.1', 1883, 60)",
                "        break",
                "    except OSError:",
                "        if time.time() > deadline:",
                "            raise",
                "        time.sleep(0.5)",
                "client.loop_forever()",
                "",
            ]
        ),
        encoding="utf-8",
    )
    received = RUNTIME / "mqtt-received.jsonl"
    if received.exists():
        received.unlink()


def down_all():
    compose("grottisolated", SHIPPED, "down", "--remove-orphans", check=False, timeout=60)
    compose("grottmqtttest", OVERLAY, "down", "--remove-orphans", check=False, timeout=60)


def main():
    ensure_docker()
    secret = "grott-ephemeral-%s" % time.time_ns()
    sample = load_sample()
    down_all()
    try:
        run([*DOCKER, "build", "-f", "docker/dockerfile", "-t", "grott:local", "."], timeout=300)
        compose("grottisolated", SHIPPED, "up", "-d", "--wait", "--no-build", timeout=180)
        health = wait_healthy("grott-isolated")
        listen = assert_loopback_listen("grott-isolated")
        ports = published_ports("grott-isolated")
        if ports or host_port_list("grott-isolated"):
            raise SystemExit("shipped container published ports: %s" % ports)
        host_error = host_cannot_connect()
        egress_text, route = egress_from("grott-isolated")
        inject_sample("grott-isolated", sample, sessions=2)
        time.sleep(1)
        shipped_logs = logs("grott-isolated")
        assert_no_secret(shipped_logs, secret)
        if shipped_logs.count("Growatt packet received") < 2:
            raise SystemExit("shipped profile did not receive two TCP sessions")
        if "Growatt data decrypted V2" not in shipped_logs:
            raise SystemExit("decoder did not run on the shipped-profile sample")
        if "MQTT message message sent" in shipped_logs:
            raise SystemExit("shipped profile published MQTT")
        for line in shipped_logs.splitlines():
            if "forward error" in line or ("has connected" in line and "noforward" not in line):
                raise SystemExit("shipped profile opened an upstream socket: %s" % line)
        print("SHIPPED_HEALTH", health)
        print("SHIPPED_LISTEN", listen)
        print("SHIPPED_PORTS", ports)
        print("SHIPPED_HOST_CONNECT", host_error)
        print("SHIPPED_EGRESS", egress_text)
        print("SHIPPED_ROUTE", route.replace("\n", " | "))
        print("SHIPPED_PACKETS", shipped_logs.count("Growatt packet received"))
        print("SHIPPED_DECRYPT", shipped_logs.count("Growatt data decrypted V2"))

        prepare_runtime(secret)
        compose("grottmqtttest", OVERLAY, "up", "-d", "--wait", "--no-build", timeout=300)
        wait_healthy("grott-mqtt-test")
        overlay_listen = assert_loopback_listen("grott-mqtt-test")
        overlay_ports = published_ports("grott-mqtt-test")
        broker_ports = published_ports("grott-mqtt-test-broker")
        broker_host_ports = host_port_list("grott-mqtt-test-broker")
        if overlay_ports or broker_ports or broker_host_ports or host_port_list("grott-mqtt-test"):
            raise SystemExit(
                "test overlay published ports grott=%s broker=%s docker_port=%s"
                % (overlay_ports, broker_ports, broker_host_ports)
            )
        overlay_egress, overlay_route = egress_from("grott-mqtt-test")
        ready_deadline = time.time() + 30
        while time.time() < ready_deadline and not (RUNTIME / "watch-ready").exists():
            time.sleep(0.5)
        if not (RUNTIME / "watch-ready").exists():
            print(logs("grott-mqtt-test-watch"))
            print(logs("grott-mqtt-test-broker"))
            raise SystemExit("MQTT watcher did not subscribe")
        inject_sample("grott-mqtt-test", sample, sessions=2)
        deadline = time.time() + 20
        messages = []
        while time.time() < deadline:
            path = RUNTIME / "mqtt-received.jsonl"
            if path.exists():
                messages = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
                if len(messages) >= 2:
                    break
            time.sleep(0.5)
        if len(messages) < 2:
            print(logs("grott-mqtt-test"))
            print(logs("grott-mqtt-test-watch"))
            print(logs("grott-mqtt-test-broker"))
            raise SystemExit("MQTT overlay delivered %s messages" % len(messages))
        for message in messages[:2]:
            if message.get("device") != "QMB2823261":
                raise SystemExit("unexpected device in MQTT payload")
            if message.get("time") != "2021-02-09T12:14:10":
                raise SystemExit("unexpected time in MQTT payload")
            if message.get("values", {}).get("pvpowerout") != 5051:
                raise SystemExit("unexpected pvpowerout in MQTT payload")
            if message.get("buffered") != "no":
                raise SystemExit("unexpected buffered flag")
        overlay_logs = logs("grott-mqtt-test") + logs("grott-mqtt-test-watch") + logs("grott-mqtt-test-broker")
        assert_no_secret(overlay_logs, secret)
        assert_no_secret(json.dumps(messages), secret)
        if "noforward, no upstream" not in overlay_logs:
            raise SystemExit("MQTT overlay did not stay in noforward mode")
        if overlay_logs.count("Growatt packet received") < 2:
            raise SystemExit("MQTT overlay did not receive two TCP sessions")
        for line in overlay_logs.splitlines():
            if "forward error" in line:
                raise SystemExit("MQTT overlay dialed upstream: %s" % line)
        print("OVERLAY_LISTEN", overlay_listen)
        print("OVERLAY_PORTS", overlay_ports, broker_ports)
        print("OVERLAY_EGRESS", overlay_egress)
        print("OVERLAY_ROUTE", overlay_route.replace("\n", " | "))
        print("OVERLAY_MQTT_COUNT", len(messages))
        print("OVERLAY_MQTT_DEVICE", messages[0]["device"])
        print("OVERLAY_MQTT_TIME", messages[0]["time"])
        print("OVERLAY_MQTT_POWER", messages[0]["values"]["pvpowerout"])
        print("OVERLAY_STILL_NOFORWARD", "noforward" in overlay_logs or "server.growatt.com" not in overlay_logs)
    finally:
        down_all()
        if RUNTIME.exists():
            shutil.rmtree(RUNTIME, ignore_errors=True)


if __name__ == "__main__":
    main()

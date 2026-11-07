"""Isolated Grott test fixtures.

Tests never open server.growatt.com, a LAN inverter, or a user MQTT broker.
A local Mosquitto on 127.0.0.1 is started when it is not already listening.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MQTT_HOST = "127.0.0.1"
MQTT_PORT = 18883

GROTT_ENV = (
    "gmode",
    "gverbose",
    "gminrecl",
    "gdecrypt",
    "gcompat",
    "gincludeall",
    "ginvtype",
    "ginvtypemap",
    "gblockcmd",
    "gnoipf",
    "gtime",
    "gtimezone",
    "gsendbuf",
    "ginverterid",
    "ggrottip",
    "ggrottport",
    "gvalueoffset",
    "ggrowattip",
    "ggrowattport",
    "gnomqtt",
    "gmqttip",
    "gmqttport",
    "gmqtttopic",
    "gmqttinverterintopic",
    "gmqttmtopic",
    "gmqttmtopicname",
    "gmqttretain",
    "gmqttauth",
    "gmqttuser",
    "gmqttpassword",
    "gmqttpassword_file",
    "gpvoutput",
    "gpvtemp",
    "gpvdisv1",
    "gpvapikey",
    "gpvapikey_file",
    "gpvinverters",
    "gpvsystemid",
    "pvuplimit",
    "ginflux",
    "ginflux2",
    "gifdbname",
    "gifip",
    "gifport",
    "gifuser",
    "gifpassword",
    "gifpassword_file",
    "giforg",
    "gifbucket",
    "giftoken",
    "giftoken_file",
    "gextension",
    "gextname",
    "gextvar",
    "gnoforward",
)


def _port_open(host, port):
    probe = socket.socket()
    probe.settimeout(0.2)
    try:
        probe.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


@pytest.fixture(scope="session", autouse=True)
def local_mqtt_broker():
    """Anonymous MQTT broker bound to loopback only."""
    proc = None
    if not _port_open(MQTT_HOST, MQTT_PORT):
        conf_dir = Path("/tmp/grott-mosquitto")
        conf_dir.mkdir(parents=True, exist_ok=True)
        conf_path = conf_dir / "mosquitto.conf"
        conf_path.write_text(
            f"listener {MQTT_PORT} {MQTT_HOST}\nallow_anonymous true\npersistence false\n",
            encoding="utf-8",
        )
        proc = subprocess.Popen(
            ["mosquitto", "-c", str(conf_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 5
        while time.time() < deadline and not _port_open(MQTT_HOST, MQTT_PORT):
            if proc.poll() is not None:
                raise RuntimeError("local mosquitto exited before accepting connections")
            time.sleep(0.05)
        if not _port_open(MQTT_HOST, MQTT_PORT):
            raise RuntimeError("local mosquitto did not listen on 127.0.0.1:%s" % MQTT_PORT)
    yield {"host": MQTT_HOST, "port": MQTT_PORT}
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(autouse=True)
def isolated_process_env(monkeypatch):
    """Drop host Grott settings so tests see program defaults."""
    for name in list(os.environ):
        if name in GROTT_ENV or name.startswith("gpvsystemid") or name.startswith("gpvinverterid"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(ROOT)
    monkeypatch.syspath_prepend(str(ROOT))


@pytest.fixture
def make_conf(tmp_path, monkeypatch):
    """Build Conf from a private ini. Pytest's own argv is hidden from argparse."""

    def _make(extra_ini="", argv=None):
        ini = tmp_path / "grott.ini"
        body = extra_ini or ""
        for section in ("Generic", "Growatt", "MQTT", "PVOutput", "influx", "extension"):
            if "[%s]" % section not in body:
                body += "\n[%s]\n" % section
        ini.write_text(body, encoding="utf-8")
        use_argv = argv if argv is not None else ["grott", "-c", str(ini)]
        monkeypatch.setattr(sys, "argv", use_argv)
        from grottconf import Conf

        conf = Conf("2.8.3")
        conf.pvoutput = False
        conf.influx = False
        conf.influx2 = False
        conf.extension = False
        return conf

    return _make

"""Review gaps: framing, older protocols, env port types, command policy, MQTT errors."""

import json
import socket
import subprocess
import threading
import time
from pathlib import Path

import libscrc
import paho.mqtt.client as mqtt

from grottmqtt import publish_payload, redact_secrets
from grottpolicy import classify_proxy_record, take_frames, validate_record
from grottproxy import Proxy
from tests.conftest import MQTT_HOST
from tests.proxy_harness import run_proxy
from tests.test_proxy_tcp import _conf, shine_configure
from tests.vectors import HA_SCALED, UPSTREAM_GROTTTEST_HEX

MASK = b"Growatt"


def _proto04(record_type=0x18, total=64):
    declared = total - 6
    body = bytearray(total)
    body[3] = 0x04
    body[4] = (declared >> 8) & 0xFF
    body[5] = declared & 0xFF
    body[6] = 0x01
    body[7] = record_type
    # Two bytes, not a 4-byte slice assignment: that would shrink the frame
    # and fail the length check before the command compare runs.
    body[36:38] = bytes.fromhex("001f")
    return bytes(body)


def _proto05(command_hex, record_type=0x18, total=64):
    payload_len = total - 8
    plain = bytearray(total)
    plain[0:8] = bytes(
        [0x00, 0x32, 0x00, 0x05, (payload_len >> 8) & 0xFF, payload_len & 0xFF, 0x01, record_type]
    )
    plain[18:20] = bytes.fromhex(command_hex)
    wire = bytearray(plain[:8])
    for index, byte in enumerate(plain[8:]):
        wire.append(byte ^ MASK[index % len(MASK)])
    body = bytes(wire[:-2])
    return body + libscrc.modbus(body).to_bytes(2, "big")


def test_protocol04_length_match_does_not_raise_and_protocol06_still_checks_crc():
    older = _proto04()
    assert validate_record(older.hex()) == 0
    sample = bytes.fromhex(UPSTREAM_GROTTTEST_HEX)
    assert validate_record(sample.hex()) == 0
    corrupted = bytearray(sample)
    corrupted[-1] ^= 0xFF
    assert validate_record(bytes(corrupted).hex()) == 8
    assert validate_record(sample[:4].hex()) == 8


def test_take_frames_splits_and_joins_without_leaking_payload():
    sample = bytes.fromhex(UPSTREAM_GROTTTEST_HEX)
    frames, rest, error = take_frames(sample[:100])
    assert frames == []
    assert rest == sample[:100]
    assert error is None
    frames, rest, error = take_frames(sample[:100] + sample[100:])
    assert frames == [sample]
    assert rest == b""
    assert error is None
    frames, rest, error = take_frames(sample + sample)
    assert frames == [sample, sample]
    assert rest == b""
    huge = bytearray(8)
    huge[3] = 0x06
    # 65528 fits in the 16-bit length field and makes 8+65528 exceed the cap.
    huge[4:6] = (65528).to_bytes(2, "big")
    frames, rest, error = take_frames(bytes(huge))
    assert frames == []
    assert error == "invalid declared length"
    assert huge.hex() not in error


def test_env_listen_port_and_minrecl_are_ints(make_conf, monkeypatch):
    monkeypatch.setenv("ggrottport", "15279")
    monkeypatch.setenv("gminrecl", "120")
    conf = make_conf()
    assert conf.grottport == 15279
    assert isinstance(conf.grottport, int)
    assert conf.minrecl == 120
    assert isinstance(conf.minrecl, int)
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", conf.grottport))
    finally:
        sock.close()


def test_command_policy_offsets_and_historical_unencrypted_compare(make_conf):
    sample = bytes.fromhex(UPSTREAM_GROTTTEST_HEX)
    allowed = classify_proxy_record(_conf(make_conf, blockcmd=True), sample)
    assert allowed == "forward"

    blocked_type = shine_configure("0000", record_type=0x99, total=128)
    assert classify_proxy_record(_conf(make_conf, blockcmd=True), blocked_type) == "blocked"

    assert classify_proxy_record(_conf(make_conf, blockcmd=True), _proto05("001f")) == "forward"
    assert classify_proxy_record(_conf(make_conf, blockcmd=True), _proto05("00aa")) == "blocked"
    assert classify_proxy_record(_conf(make_conf, blockcmd=True, noipf=False), _proto05("0011")) == "blocked"
    assert classify_proxy_record(_conf(make_conf, blockcmd=True, noipf=True), _proto05("0011")) == "forward"

    # Historical: unencrypted records compare raw bytes to a hex string, so the
    # time-command exception does not apply. Do not silently "fix" that.
    assert classify_proxy_record(_conf(make_conf, blockcmd=True), _proto04()) == "blocked"


def test_redact_configured_secret_from_mqtt_errors():
    class Conf:
        mqttpsw = "ephemeral-test-secret"
        pvapikey = "yourapikey"
        ifpsw = ""
        iftoken = None

    text = redact_secrets(Conf(), "MQTTException: ephemeral-test-secret rejected")
    assert "ephemeral-test-secret" not in text
    assert "**secret**" in text


def test_publish_payload_auth_roundtrip_and_failure_hides_secret(make_conf, tmp_path, capsys):
    passwd = tmp_path / "passwd"
    secret = "ephemeral-mqtt-%s" % time.time_ns()
    subprocess.check_call(
        ["mosquitto_passwd", "-c", "-b", str(passwd), "grott-test", secret],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    conf_path = tmp_path / "mosquitto.conf"
    port = 18884
    conf_path.write_text(
        "listener %s 127.0.0.1\nallow_anonymous false\npassword_file %s\npersistence false\n"
        % (port, passwd),
        encoding="utf-8",
    )
    proc = subprocess.Popen(
        ["mosquitto", "-c", str(conf_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 5
        ready = False
        while time.time() < deadline:
            probe = socket.socket()
            probe.settimeout(0.2)
            try:
                probe.connect((MQTT_HOST, port))
                ready = True
                break
            except OSError:
                time.sleep(0.05)
            finally:
                probe.close()
        assert ready, "password-protected mosquitto did not listen"

        messages = []
        connected = threading.Event()

        def on_connect(client, userdata, flags, reason_code, properties):
            client.subscribe("energy/growatt/auth", qos=0)
            connected.set()

        def on_message(client, userdata, message):
            messages.append(message.payload)

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="grott-auth-sub")
        client.username_pw_set("grott-test", secret)
        client.on_connect = on_connect
        client.on_message = on_message
        client.connect(MQTT_HOST, port, 60)
        client.loop_start()
        assert connected.wait(5)

        conf = make_conf()
        conf.verbose = True
        conf.mqttip = MQTT_HOST
        conf.mqttport = port
        conf.mqttretain = False
        conf.inverterid = "grott-auth-pub"
        conf.mqttauth = True
        conf.mqttuser = "grott-test"
        conf.mqttpsw = secret
        conf.pubauth = {"username": "grott-test", "password": secret}
        publish_payload(conf, "energy/growatt/auth", '{"device":"QMB2823261"}')
        deadline = time.time() + 5
        while time.time() < deadline and not messages:
            time.sleep(0.05)
        assert messages and b"QMB2823261" in messages[0]

        conf.mqttpsw = secret
        conf.pubauth = {"username": "grott-test", "password": secret + "-wrong"}
        # Force the failure text to be the path we redact, without depending on
        # the broker to echo the password. paho's own refusal text does not
        # include it; this still guards our logger.
        publish_payload(conf, "energy/growatt/auth", "ignored")
        logged = capsys.readouterr().out
        assert secret not in logged
        client.loop_stop()
        client.disconnect()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_split_and_concatenated_logger_frames(make_conf):
    sample = bytes.fromhex(UPSTREAM_GROTTTEST_HEX)
    split = run_proxy(
        _conf(make_conf),
        [sample[:100], sample[100:]],
        "energy/growatt/proxy-split",
        gap=0.8,
        upstream_wait=2.5,
    )
    assert split["errors"] == []
    assert split["upstream"] == sample
    assert len(split["mqtt"]) == 1
    body = json.loads(split["mqtt"][0][1].decode("utf-8"))
    assert body["values"]["pvpowerout"] / 10 == HA_SCALED["power_w"]
    assert body["time"] == HA_SCALED["packet_time"]

    both = run_proxy(
        _conf(make_conf),
        sample + sample,
        "energy/growatt/proxy-two",
        mqtt_count=2,
        upstream_wait=2.5,
    )
    assert both["upstream"] == sample + sample
    assert len(both["mqtt"]) == 2


def test_incomplete_frame_is_discarded_without_forwarding(make_conf, capsys):
    sample = bytes.fromhex(UPSTREAM_GROTTTEST_HEX)
    result = run_proxy(_conf(make_conf), sample[:80], "energy/growatt/proxy-partial", upstream_wait=0.6)
    assert result["upstream"] == b""
    assert result["mqtt"] == []
    logged = capsys.readouterr().out
    assert "discarded incomplete frame: length=80" in logged
    assert sample[:80].hex() not in logged


def test_isolated_compose_blocks_egress_and_test_overlay_is_separate():
    root = Path(__file__).resolve().parents[1]
    shipped = (root / "docker" / "docker-compose.isolated.yml").read_text(encoding="utf-8")
    test_overlay = (root / "docker" / "docker-compose.isolated-mqtt-test.yml").read_text(encoding="utf-8")
    profile = (root / "examples" / "profiles" / "isolated.ini").read_text(encoding="utf-8")
    assert "internal: true" in shipped
    assert "ports:" not in shipped
    assert "127.0.0.1" in profile
    assert "noforward = True" in profile
    assert "nomqtt = True" in profile
    assert "gnomqtt=False" in test_overlay
    assert "TEST ONLY" in test_overlay
    assert "ports:" not in test_overlay
    assert "internal: true" in test_overlay


def _listen():
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    sock.settimeout(5)
    return sock


def _start_proxy(conf):
    proxy = Proxy(conf)
    errors = []

    def _main():
        try:
            proxy.main(conf)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=_main, daemon=True)
    thread.start()
    return proxy, thread, errors


def _stop_proxy(proxy, thread):
    proxy.stop()
    thread.join(timeout=3)


def test_upstream_short_reply_is_not_prefixed_onto_the_next_record(make_conf):
    """Server replies stay one recv at a time.

    A short ACK that is not a frame must not be glued to the next upstream
    record. Reassembling that socket would change existing cloud responses.
    """
    sample = bytes.fromhex(UPSTREAM_GROTTTEST_HEX)
    second = shine_configure("001f")
    upstream = _listen()
    conf = _conf(make_conf, nomqtt=True)
    conf.growattip = "127.0.0.1"
    conf.growattport = upstream.getsockname()[1]
    conf.grottip = "127.0.0.1"
    conf.grottport = 0
    conf.minrecl = 100
    accepted = {}

    def _accept():
        conn, _ = upstream.accept()
        conn.settimeout(2)
        accepted["conn"] = conn

    accepter = threading.Thread(target=_accept, daemon=True)
    accepter.start()
    proxy, thread, errors = _start_proxy(conf)
    client = socket.create_connection(("127.0.0.1", proxy.server.getsockname()[1]), timeout=5)
    client.settimeout(2)
    server_conn = None
    try:
        accepter.join(5)
        assert "conn" in accepted
        server_conn = accepted["conn"]
        client.sendall(sample)
        got = b""
        while len(got) < len(sample):
            chunk = server_conn.recv(8192)
            assert chunk
            got += chunk
        assert got == sample
        server_conn.sendall(b"\x00\x04")
        time.sleep(0.6)
        server_conn.sendall(second)
        received = b""
        deadline = time.time() + 2
        while time.time() < deadline and len(received) < len(second):
            try:
                part = client.recv(8192)
            except socket.timeout:
                break
            if not part:
                break
            received += part
        assert received == second
        assert errors == []
    finally:
        client.close()
        if server_conn is not None:
            server_conn.close()
        upstream.close()
        _stop_proxy(proxy, thread)


def test_new_logger_session_dials_upstream_again(make_conf):
    """A dropped upstream closes that pair. The next logger TCP session dials again.

    This is not an in-stream reconnect and it does not invent a logger ACK.
    """
    sample = bytes.fromhex(UPSTREAM_GROTTTEST_HEX)
    upstream = _listen()
    conf = _conf(make_conf, nomqtt=True)
    conf.growattip = "127.0.0.1"
    conf.growattport = upstream.getsockname()[1]
    conf.grottip = "127.0.0.1"
    conf.grottport = 0
    conf.minrecl = 100
    payloads = []
    proxy, thread, errors = _start_proxy(conf)
    try:
        for _ in range(2):
            accepted = {}

            def _accept(box=accepted):
                conn, _ = upstream.accept()
                conn.settimeout(2)
                data = b""
                while len(data) < len(sample):
                    chunk = conn.recv(8192)
                    if not chunk:
                        break
                    data += chunk
                box["data"] = data
                conn.close()

            accepter = threading.Thread(target=_accept, daemon=True)
            accepter.start()
            client = socket.create_connection(
                ("127.0.0.1", proxy.server.getsockname()[1]), timeout=5
            )
            try:
                client.sendall(sample)
                accepter.join(5)
            finally:
                client.close()
            assert "data" in accepted
            payloads.append(accepted["data"])
        assert payloads == [sample, sample]
        assert errors == []
    finally:
        upstream.close()
        _stop_proxy(proxy, thread)

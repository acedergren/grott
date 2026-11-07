"""Baseline decoder and MQTT contract for the upstream grotttest.py packet."""

import json
import threading
import time

import paho.mqtt.client as mqtt

from tests.conftest import MQTT_HOST, MQTT_PORT
from tests.vectors import EXPECTED_T06NNNN, HA_SCALED, UPSTREAM_GROTTTEST_HEX


def _subscribe(topic):
    messages = []
    connected = threading.Event()

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code != 0 and getattr(reason_code, "is_failure", False):
            return
        client.subscribe(topic, qos=0)
        connected.set()

    def on_message(client, userdata, message):
        messages.append((message.topic, message.payload, message.retain))

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="grott-reg-" + topic[-12:])
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    assert connected.wait(5), "local MQTT subscriber did not connect"
    return client, messages


def test_upstream_example_layout_values_and_mqtt_json(make_conf):
    """T06NNNN sample keeps the five HA sensor values and the JSON object shape."""
    from grottdata import procdata

    topic = "energy/growatt"
    client, messages = _subscribe(topic)
    try:
        conf = make_conf()
        conf.nomqtt = False
        conf.verbose = False
        conf.mqttip = MQTT_HOST
        conf.mqttport = MQTT_PORT
        conf.mqtttopic = topic
        conf.mqttretain = False
        conf.sendbuf = True
        conf.compat = False
        conf.invtype = "default"
        conf.blockcmd = False

        data = bytes.fromhex(UPSTREAM_GROTTTEST_HEX)
        procdata(conf, data)

        deadline = time.time() + 5
        while time.time() < deadline and not messages:
            time.sleep(0.05)
        assert messages, "decoder did not publish to the local MQTT broker"
        got_topic, payload, retain = messages[0]
        assert got_topic == "energy/growatt"
        assert retain is False
        message = json.loads(payload.decode("utf-8"))
        assert message["device"] == EXPECTED_T06NNNN["device"]
        assert message["time"] == EXPECTED_T06NNNN["time"]
        assert message["buffered"] == "no"
        assert set(message) == {"device", "time", "buffered", "values"}
        assert message["values"] == EXPECTED_T06NNNN["values"]
        values = message["values"]
        assert values["pvpowerout"] / 10 == HA_SCALED["power_w"]
        assert values["pvgridvoltage"] / 10 == HA_SCALED["grid_voltage_v"]
        assert values["pvtemperature"] / 10 == HA_SCALED["temperature_c"]
        assert values["pvenergytoday"] / 10 == HA_SCALED["energy_today_kwh"]
        assert message["time"] == HA_SCALED["packet_time"]
        assert conf.layout == "T06NNNN"
        assert "homeassistant" not in got_topic
    finally:
        client.loop_stop()
        client.disconnect()


def test_decrypt_preserves_header_and_reveals_sample_serial():
    from grottdata import decrypt

    data = bytes.fromhex(UPSTREAM_GROTTTEST_HEX)
    plain = decrypt(data)
    assert plain[:16] == data[:8].hex()
    mask = b"Growatt"
    revealed = data[8] ^ mask[0]
    assert plain[16:18] == f"{revealed:02x}"
    assert "QMB2823261".encode("ascii").hex() in plain
    assert plain != data.hex()


def test_sample_record_passes_length_and_crc():
    from grottproxy import validate_record

    data = bytes.fromhex(UPSTREAM_GROTTTEST_HEX)
    assert validate_record(data.hex()) == 0
    truncated = data[:40]
    assert validate_record(truncated.hex()) == 8
    corrupted = bytearray(data)
    corrupted[-1] ^= 0xFF
    assert validate_record(bytes(corrupted).hex()) == 8

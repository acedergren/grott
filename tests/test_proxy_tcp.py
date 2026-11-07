"""TCP proxy tests with a fake Growatt peer and local MQTT."""

import json

import libscrc

from tests.proxy_harness import run_proxy
from tests.vectors import EXPECTED_T06NNNN, HA_SCALED, UPSTREAM_GROTTTEST_HEX

MASK = b"Growatt"


def shine_configure(command_hex, record_type=0x18, total=64):
    """Protocol-06 Shine configure record with a valid Modbus CRC.

    Command id sits at decrypted hex index 76, which is plaintext byte 38.
    The proxy decrypts the whole frame, including the trailing CRC bytes.
    total includes the two CRC bytes and must be at least 42.
    """
    payload_len = total - 8
    plain = bytearray(total)
    plain[0:8] = bytes(
        [
            0x00,
            0x32,
            0x00,
            0x06,
            (payload_len >> 8) & 0xFF,
            payload_len & 0xFF,
            0x01,
            record_type,
        ]
    )
    command = bytes.fromhex(command_hex)
    plain[38:40] = command
    wire = bytearray(plain[:8])
    for index, byte in enumerate(plain[8:]):
        wire.append(byte ^ MASK[index % len(MASK)])
    body = bytes(wire[:-2])
    crc = libscrc.modbus(body)
    return body + crc.to_bytes(2, "big")


def _conf(make_conf, **overrides):
    conf = make_conf()
    conf.nomqtt = False
    conf.verbose = False
    conf.compat = False
    conf.invtype = "default"
    conf.blockcmd = False
    conf.noipf = False
    conf.sendbuf = True
    for key, value in overrides.items():
        setattr(conf, key, value)
    return conf


def test_proxy_forwards_sample_and_publishes_mqtt(make_conf):
    sample = bytes.fromhex(UPSTREAM_GROTTTEST_HEX)
    topic = "energy/growatt/proxy-sample"
    result = run_proxy(_conf(make_conf), sample, topic)
    assert result["errors"] == []
    assert result["accepted"] is True
    assert result["upstream"] == sample
    assert result["mqtt"], "proxy path did not publish MQTT"
    topic_got, payload, retain = result["mqtt"][0]
    message = json.loads(payload.decode("utf-8"))
    assert topic_got == topic
    assert retain is False
    assert message["time"] == HA_SCALED["packet_time"]
    assert message["values"]["pvpowerout"] / 10 == HA_SCALED["power_w"]
    assert message["values"]["pvgridvoltage"] / 10 == HA_SCALED["grid_voltage_v"]
    assert message["values"]["pvtemperature"] / 10 == HA_SCALED["temperature_c"]
    assert message["values"]["pvenergytoday"] / 10 == HA_SCALED["energy_today_kwh"]
    assert message["values"] == EXPECTED_T06NNNN["values"]
    assert message["device"] == EXPECTED_T06NNNN["device"]
    assert message["buffered"] == "no"


def test_proxy_blocks_shine_write_and_allows_time_and_whitelist(make_conf):
    blocked = shine_configure("00aa")
    topic = "energy/growatt/proxy-block"
    blocked_result = run_proxy(_conf(make_conf, blockcmd=True), blocked, topic)
    assert blocked_result["accepted"] is True
    assert blocked_result["upstream"] == b""
    assert blocked_result["mqtt"] == []

    allowed_time = shine_configure("001f")
    time_result = run_proxy(
        _conf(make_conf, blockcmd=True),
        allowed_time,
        "energy/growatt/proxy-time",
    )
    assert time_result["upstream"] == allowed_time

    ip_change = shine_configure("0011")
    denied = run_proxy(
        _conf(make_conf, blockcmd=True, noipf=False),
        ip_change,
        "energy/growatt/proxy-ip-deny",
    )
    assert denied["upstream"] == b""
    allowed_ip = run_proxy(
        _conf(make_conf, blockcmd=True, noipf=True),
        ip_change,
        "energy/growatt/proxy-ip-allow",
    )
    assert allowed_ip["upstream"] == ip_change

    sample = bytes.fromhex(UPSTREAM_GROTTTEST_HEX)
    whitelisted = run_proxy(
        _conf(make_conf, blockcmd=True),
        sample,
        "energy/growatt/proxy-whitelist",
    )
    assert whitelisted["upstream"] == sample
    assert whitelisted["mqtt"]
    message = json.loads(whitelisted["mqtt"][0][1].decode("utf-8"))
    assert message["values"]["pvpowerout"] == 5051


def test_proxy_drops_truncated_and_bad_crc_without_forwarding(make_conf, capsys):
    sample = bytes.fromhex(UPSTREAM_GROTTTEST_HEX)
    truncated = sample[:40]
    truncated_result = run_proxy(
        _conf(make_conf),
        truncated,
        "energy/growatt/proxy-trunc",
    )
    assert truncated_result["upstream"] == b""
    assert truncated_result["mqtt"] == []

    corrupted = bytearray(sample)
    corrupted[-1] ^= 0xFF
    corrupted_result = run_proxy(
        _conf(make_conf),
        bytes(corrupted),
        "energy/growatt/proxy-crc",
    )
    assert corrupted_result["upstream"] == b""
    assert corrupted_result["mqtt"] == []
    captured = capsys.readouterr().out
    assert "length mismatch" in captured
    assert "declared_payload=257" in captured
    assert "checksum mismatch" in captured
    assert sample.hex() not in captured
    assert truncated.hex() not in captured
    assert bytes(corrupted).hex() not in captured


def test_unknown_record_is_forwarded_and_not_published(make_conf, capsys):
    """A CRC-valid type the layouts do not know follows the historical proxy path.

    Unknown records are still forwarded. They are not decoded into MQTT.
    """
    unknown = shine_configure("0000", record_type=0x99, total=128)
    result = run_proxy(_conf(make_conf, verbose=False), unknown, "energy/growatt/proxy-unknown")
    assert result["upstream"] == unknown
    assert result["mqtt"] == []
    captured = capsys.readouterr().out
    assert "layout=T060199" in captured
    assert "reason=no matching layout" in captured
    assert unknown.hex() not in captured


def test_noforward_keeps_decode_local_and_does_not_open_upstream(make_conf):
    """Opt-in dev switch. Default proxy tests above still forward."""
    sample = bytes.fromhex(UPSTREAM_GROTTTEST_HEX)
    topic = "energy/growatt/proxy-noforward"
    result = run_proxy(_conf(make_conf, noforward=True), sample, topic)
    assert result["errors"] == []
    assert result["accepted"] is False
    assert result["upstream"] == b""
    assert result["mqtt"], "noforward still decodes and can publish locally"
    message = json.loads(result["mqtt"][0][1].decode("utf-8"))
    assert message["values"]["pvpowerout"] == 5051
    assert message["time"] == "2021-02-09T12:14:10"

"""Isolated profile, secret files, and image recipe checks."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_defaults_still_forward_and_do_not_block(make_conf):
    conf = make_conf()
    assert conf.noforward is False
    assert conf.blockcmd is False
    assert conf.nomqtt is False
    assert conf.mode == "proxy"
    assert conf.growattip == "server.growatt.com"
    assert conf.growattport == 5279
    assert conf.grottip == "default"


def test_isolated_profile_is_loopback_readonly(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["grott", "-c", str(ROOT / "examples/profiles/isolated.ini")])
    from grottconf import Conf

    conf = Conf("2.8.3")
    assert conf.noforward is True
    assert conf.blockcmd is True
    assert conf.nomqtt is True
    assert conf.pvoutput is False
    assert conf.influx is False
    assert conf.influx2 is False
    assert conf.extension is False
    assert conf.sendbuf is False
    assert conf.grottip == "127.0.0.1"
    assert conf.grottport == 5279
    assert conf.mode == "proxy"
    # The cloud hostname remains configured and is not dialed by this test.
    assert conf.growattip == "server.growatt.com"


def test_secret_file_overrides_ini_and_is_not_printed(make_conf, tmp_path, capsys):
    secret = tmp_path / "mqtt_password"
    secret.write_text("local-file-secret\n", encoding="utf-8")
    token = tmp_path / "influx_token"
    token.write_text("local-token-secret\n", encoding="utf-8")
    conf = make_conf(
        "\n".join(
            [
                "[MQTT]",
                "password = ini-password-should-lose",
                "password_file = %s" % secret,
                "[influx]",
                "token = ini-token-should-lose",
                "token_file = %s" % token,
                "",
            ]
        )
    )
    assert conf.mqttpsw == "local-file-secret"
    assert conf.iftoken == "local-token-secret"
    conf.verbose = True
    conf.print()
    printed = capsys.readouterr().out
    assert "local-file-secret" not in printed
    assert "local-token-secret" not in printed
    assert "ini-password-should-lose" not in printed
    assert "**secret**" in printed


def test_missing_secret_file_exits_without_inventing_a_value(make_conf):
    import pytest

    with pytest.raises(SystemExit):
        make_conf("[MQTT]\npassword_file = /tmp/grott-missing-secret-file\n")


def test_image_recipe_replaces_python37_and_isolated_compose_publishes_nothing():
    dockerfile = (ROOT / "docker" / "dockerfile").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    legacy = (ROOT / "docker" / "docker-compose.yml").read_text(encoding="utf-8")
    isolated = (ROOT / "docker" / "docker-compose.isolated.yml").read_text(encoding="utf-8")
    retired = (ROOT / "docker" / "dockerrpi").read_text(encoding="utf-8")
    assert "python:3.7" not in dockerfile
    assert "python:3.12" in dockerfile
    assert "requirements.txt" in dockerfile
    assert "python:3.7" not in retired
    for pin in ("paho-mqtt==", "requests==", "libscrc==", "influxdb==", "influxdb-client=="):
        assert pin in requirements
    assert "5279:5279" in legacy
    assert "ports:" not in isolated
    assert "gnoforward=True" in isolated
    assert "gblockcmd=True" in isolated
    assert "growatt2020" not in isolated

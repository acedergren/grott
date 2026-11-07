# grottmqtt.py
# MQTT publish boundary. Topic selection stays in grottdata so the JSON
# contract and topic rules remain next to the values that feed them.

import paho.mqtt.publish as publish


def publish_payload(conf, topic, payload):
    """Publish one Grott JSON payload. Failures are logged, not raised."""
    if conf.mqttretain:
        if conf.verbose:
            print("\t - " + "Grott MQTT message retain enabled")

    try:
        # v2.7.1 add retain variable
        publish.single(
            topic,
            payload=payload,
            qos=0,
            retain=conf.mqttretain,
            hostname=conf.mqttip,
            port=conf.mqttport,
            client_id=conf.inverterid,
            keepalive=60,
            auth=conf.pubauth,
        )
        if conf.verbose:
            print("\t - " + "MQTT message message sent")
    except TimeoutError:
        if conf.verbose:
            print("\t - " + "MQTT connection time out error")
    except ConnectionRefusedError:
        if conf.verbose:
            print("\t - " + "MQTT connection refused by target")
    except BaseException as error:
        if conf.verbose:
            print("\t - " + "MQTT send failed:", str(error))

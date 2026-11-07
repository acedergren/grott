# Remaining refactoring

The first tranche locks the `examples/grotttest.py` contract, runs the proxy against fake peers, and moves Python off 3.7. It does not make Grott independent of the Growatt cloud. Default `noforward` stays false.

Grottserver and the writable register API stay out of this list until a separate, tested change.

## Order

1. Reconnect the upstream socket with backoff. A dropped upstream still closes that logger pair. The next logger TCP session dials again; that was exercised against a fake upstream. There is still no in-stream reconnect, and `noforward` still does not ACK the logger.
2. The default image still has no healthcheck. `docker/docker-compose.isolated.yml` now has a loopback-only check and an internal network. Do not turn that into a WAN probe or a published host port.
3. Replace the remaining `print` paths in `procdata` with one logger. Verbose frame dumps stay opt-in. Error lines stay free of payload bytes and secrets.
4. Move PVOutput, InfluxDB, and extension calls out of `procdata` behind the same JSON object the MQTT tests already lock. No new output should be enabled by default.
5. Add characterization tests for `compat = True` and for smart-meter / log layouts when a real sample exists. Do not invent a MOD 10KTL3-XH or ShineWiFi-X capture.
6. Sniff mode still needs `AF_PACKET` and a routed Growatt flow. Test it only in an environment that can do that. Do not treat a green proxy suite as sniff coverage.
7. Non-05/06 records are length-checked only, matching the README. Protocol 05/06 still require a Modbus CRC. An explicit protocol table is still open if a capture shows a type this rule misreads.
8. Keep command blocking's allow-list (`001f` time, `0011` only with `noipf`, plus `recwl`) stable until an inverter capture shows a command the current parser misreads.
9. Do not remove cloud forwarding from the default image, the legacy compose file, or `grott.py`.

## Already true, and easy to overclaim

- MQTT discovery is still unnecessary and is not emitted.
- The generic `T06NNNN` sample does not prove MOD 10KTL3-XH, ShineWiFi-X, or battery support.
- `examples/profiles/isolated.ini` disables forwarding on purpose. It is not a substitute for a running proxy.

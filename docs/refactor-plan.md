# Remaining refactoring

The first tranche locks the `examples/grotttest.py` contract, runs the proxy against fake peers, and moves Python off 3.7. It does not make Grott independent of the Growatt cloud. Default `noforward` stays false.

Grottserver and the writable register API stay out of this list until a separate, tested change.

## Order

1. Reconnect the upstream socket with backoff. Today a failed `Forward.start` closes the logger connection. A reconnect must not drop a healthy logger socket blindly, and it must stay off when `noforward` is set.
2. Add a healthcheck that is off by default. It must not open a WAN socket or publish a host port. A loopback TCP accept check, or a local MQTT birth message when MQTT is already enabled, is enough.
3. Replace the remaining `print` paths in `procdata` with one logger. Verbose frame dumps stay opt-in. Error lines stay free of payload bytes and secrets.
4. Move PVOutput, InfluxDB, and extension calls out of `procdata` behind the same JSON object the MQTT tests already lock. No new output should be enabled by default.
5. Add characterization tests for `compat = True` and for smart-meter / log layouts when a real sample exists. Do not invent a MOD 10KTL3-XH or ShineWiFi-X capture.
6. Sniff mode still needs `AF_PACKET` and a routed Growatt flow. Test it only in an environment that can do that. Do not treat a green proxy suite as sniff coverage.
7. Decide whether non-02/05/06 records should keep the new "reject without crashing" behaviour or grow an explicit protocol table. The old code raised `NameError` on some of those frames.
8. Keep command blocking's allow-list (`001f` time, `0011` only with `noipf`, plus `recwl`) stable until an inverter capture shows a command the current parser misreads.
9. Do not remove cloud forwarding from the default image, the legacy compose file, or `grott.py`.

## Already true, and easy to overclaim

- MQTT discovery is still unnecessary and is not emitted.
- The generic `T06NNNN` sample does not prove MOD 10KTL3-XH, ShineWiFi-X, or battery support.
- `examples/profiles/isolated.ini` disables forwarding on purpose. It is not a substitute for a running proxy.

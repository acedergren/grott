"""Public upstream sample from examples/grotttest.py.

The hex is the packet shipped with Grott 2.6.1/2.8.3. It is not a live
inverter capture from this fork. Whitespace in the original literal is
insignificant to bytes.fromhex.
"""

UPSTREAM_GROTTTEST_HEX = (
    "00320006010101040d222c4559454c74412d7761747447726f7761747447726f776174744772"
    "3e3a23464c75415d4150747447726f7761747447726f7761747447726f7774767d4b7c657561"
    "74746b726e776161064e776f6061746135726f7761747447726f7772cf67ce7b2a7774747454"
    "c96f7761747447726f7761747447726f7761747452726fd0d97796a77e6e7a61747447726f77"
    "61747447726f77617474477ce977617474475f6f2e2f547447726f776174624772df41617474"
    "47726f77617474f7446f7761747447726f7761747447726f7761747447726f7761747447786f"
    "776b287d457a9777607eb407066ef46ff376527ce87762747747656f7761747447726f6d03"
)

# Raw register values produced by procdata for layout T06NNNN.
# Home Assistant template sensors scale these, they do not change them:
#   pvpowerout/10 W, pvgridvoltage/10 V, pvtemperature/10 C, pvenergytoday/10 kWh
EXPECTED_T06NNNN = {
    "buffered": "no",
    "device": "QMB2823261",
    "time": "2021-02-09T12:14:10",
    "values": {
        "datalogserial": "JPC281833B",
        "epv1today": 22,
        "epv1total": 45110,
        "epv2today": 0,
        "epv2total": 0,
        "epvtotal": 45110,
        "pv1current": 23,
        "pv1voltage": 2309,
        "pv1watt": 5490,
        "pv2current": 0,
        "pv2voltage": 0,
        "pv2watt": 0,
        "pvenergytoday": 21,
        "pvenergytotal": 42936,
        "pvfrequentie": 5001,
        "pvgridcurrent": 21,
        "pvgridcurrent2": 0,
        "pvgridcurrent3": 0,
        "pvgridpower": 5051,
        "pvgridpower2": 0,
        "pvgridpower3": 0,
        "pvgridvoltage": 2373,
        "pvgridvoltage2": 0,
        "pvgridvoltage3": 0,
        "pvipmtemperature": 0,
        "pvpowerin": 5490,
        "pvpowerout": 5051,
        "pvserial": "QMB2823261",
        "pvstatus": 1,
        "pvtemperature": 269,
        "totworktime": 65200140,
    },
}

HA_SCALED = {
    "power_w": 505.1,
    "grid_voltage_v": 237.3,
    "temperature_c": 26.9,
    "energy_today_kwh": 2.1,
    "packet_time": "2021-02-09T12:14:10",
}

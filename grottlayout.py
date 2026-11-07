# grottlayout.py
# Record-layout selection and field decoding extracted from grottdata.procdata.
# Offsets, types, and the TxxNNNN generic fallback are unchanged.
# Layout tables themselves still live in grottconf.Conf.recorddict.

import codecs


def resolve_layout(conf, header, ndata):
    """Select the layout id for one received frame.

    Returns (layout, novalidrec, buffered) and stores conf.layout.
    A missing layout is reported with protocol, type, and length only.
    """
    is_smart_meter = header[14:16] in ("20", "1b")
    novalidrec = False
    if conf.verbose:
        print("\t - " + "Grott automatic protocol detection")
        print("\t - " + "Grott data record length", ndata)
    layout = "T" + header[6:8] + header[12:14] + header[14:16]
    # v270 add X for extended except for smart monitor records
    if (ndata > 375) and not is_smart_meter:
        layout = layout + "X"

    # v270 no invtype added to layout for smart monitor records
    if (conf.invtype != "default") and not is_smart_meter:
        layout = layout + conf.invtype.upper()

    if header[14:16] == "50":
        buffered = "yes"
    else:
        buffered = "no"

    if conf.verbose:
        print("\t - " + "layout   : ", layout)
    try:
        # does record layout record exists?
        conf.recorddict[layout]
    except Exception:
        # try generic if generic record exist
        if conf.verbose:
            print("\t - " + "no matching record layout found, try generic")
        if header[14:16] in ("04", "50"):
            layout = layout.replace(header[12:16], "NNNN")
            try:
                conf.recorddict[layout]
            except Exception:
                # no valid record fall back on old processing?
                if conf.verbose:
                    print("\t - " + "no matching record layout found, standard processing performed")
                layout = "none"
                novalidrec = True
        else:
            novalidrec = True

    conf.layout = layout
    if conf.verbose:
        print("\t - " + "Record layout used : ", layout)
    if novalidrec:
        print(
            "\t - Grott record not decoded: layout=%s protocol=%s type=%s length=%s reason=no matching layout"
            % (layout, header[6:8], header[12:16], ndata)
        )
    return layout, novalidrec, buffered


def decode_fields(conf, layout, result_string):
    """Decode included layout fields. Returns (definedkey, error).

    error is 8 when a field cannot be read, matching the historical procdata
    return. The plaintext hex string is not included in the error text.
    """
    definedkey = {}
    try:
        # v270 try if logstart and log fields are defined, if yes prepare log fields
        logdict = bytes.fromhex(
            result_string[conf.recorddict[layout]["logstart"]["value"]:len(result_string) - 4]
        ).decode("ASCII").split(",")
    except Exception:
        logdict = {}

    # v270 log data record processing (SDM630 smart monitor with railog)
    for keyword in conf.recorddict[layout].keys():

        if keyword not in ("decrypt", "date", "logstart", "device"):
            # try if keyword should be included
            include = True
            try:
                # try if key type is specified
                if conf.recorddict[layout][keyword]["incl"] == "no":
                    include = False
            except Exception:
                # no include statement keyword should be process, set include to prevent except errors
                include = True
            # process only keyword needs to be included (default):
            try:
                if (include) or (conf.includeall):
                    try:
                        # try if key type is specified
                        keytype = conf.recorddict[layout][keyword]["type"]
                    except Exception:
                        # if not default is num
                        keytype = "num"
                    if keytype == "text":
                        definedkey[keyword] = result_string[
                            conf.recorddict[layout][keyword]["value"]:conf.recorddict[layout][keyword]["value"]
                            + (conf.recorddict[layout][keyword]["length"] * 2)
                        ]
                        definedkey[keyword] = codecs.decode(definedkey[keyword], "hex").decode("utf-8")
                    if keytype == "num":
                        definedkey[keyword] = int(
                            result_string[
                                conf.recorddict[layout][keyword]["value"]:conf.recorddict[layout][keyword]["value"]
                                + (conf.recorddict[layout][keyword]["length"] * 2)
                            ],
                            16,
                        )
                    if keytype == "numx":
                        # process signed integer
                        keybytes = bytes.fromhex(
                            result_string[
                                conf.recorddict[layout][keyword]["value"]:conf.recorddict[layout][keyword]["value"]
                                + (conf.recorddict[layout][keyword]["length"] * 2)
                            ]
                        )
                        definedkey[keyword] = int.from_bytes(keybytes, byteorder="big", signed=True)
                    if keytype == "log":
                        definedkey[keyword] = logdict[conf.recorddict[layout][keyword]["pos"] - 1]
                    if keytype == "logpos":
                        # only display this field if positive
                        if float(logdict[conf.recorddict[layout][keyword]["pos"] - 1]) > 0:
                            definedkey[keyword] = logdict[conf.recorddict[layout][keyword]["pos"] - 1]
                        else:
                            definedkey[keyword] = 0
                    if keytype == "logneg":
                        # only display this field if negative
                        if float(logdict[conf.recorddict[layout][keyword]["pos"] - 1]) < 0:
                            definedkey[keyword] = logdict[conf.recorddict[layout][keyword]["pos"] - 1]
                        else:
                            definedkey[keyword] = 0
            except Exception:
                if conf.verbose:
                    print("\t - grottdata - error in keyword processing : ", keyword + " ,data processing stopped")
                return definedkey, 8

    return definedkey, None

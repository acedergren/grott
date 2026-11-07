# grottpolicy.py
# Record validation and command-block policy extracted from grottproxy.
# Decisions are pure with respect to sockets: the proxy applies them.

try:
    import libscrc
except Exception:
    libscrc = None

from grottcrypto import decrypt


def validate_record(xdata):
    # validata data record on length and CRC (for "05" and "06" records)

    data = bytes.fromhex(xdata)
    ldata = len(data)
    len_orgpayload = int.from_bytes(data[4:6], "big")
    header = "".join("{:02x}".format(n) for n in data[0:8])
    protocol = header[6:8]

    if protocol in ("05", "06"):
        lcrc = 4
        crc = int.from_bytes(data[ldata - 2:ldata], "big")
    else:
        lcrc = 0

    len_realpayload = (ldata * 2 - 12 - lcrc) / 2

    if protocol != "02":

        try:
            crc_calc = libscrc.modbus(data[0:ldata - 2])
        except Exception:
            # libscrc is not installed yet
            crc_calc = crc = 0

    if len_realpayload == len_orgpayload:
        returncc = 0
        if protocol != "02" and crc != crc_calc:
            returncc = 8
    else:
        returncc = 8

    return returncc


def invalid_record_reason(data):
    """Explain a rejected frame without echoing its payload."""
    length = len(data)
    if length < 8:
        return "truncated header: length=%s" % length
    protocol = "%02x" % data[3]
    declared = int.from_bytes(data[4:6], "big")
    if protocol in ("05", "06"):
        actual = length - 8
    else:
        actual = length - 6
    record_type = "%02x%02x" % (data[6], data[7]) if length >= 8 else "none"
    if declared != actual:
        return (
            "length mismatch: protocol=%s type=%s declared_payload=%s actual_payload=%s length=%s"
            % (protocol, record_type, declared, actual, length)
        )
    return (
        "checksum mismatch: protocol=%s type=%s declared_payload=%s length=%s"
        % (protocol, record_type, declared, length)
    )


def classify_proxy_record(conf, data):
    """Return 'invalid', 'blocked', or 'forward'.

    'forward' means the historical proxy would send the original bytes
    upstream. noforward is applied by the socket layer, not here, so tests
    can still see that a record was eligible for cloud forwarding.
    """
    try:
        validatecc = validate_record(data.hex())
    except Exception as exc:
        print(
            "\t - Grott invalid record: validation error %s length=%s"
            % (type(exc).__name__, len(data))
        )
        return "invalid"

    if validatecc != 0:
        print("\t - Grott invalid record: %s" % invalid_record_reason(data))
        return "invalid"

    header = "".join("{:02x}".format(n) for n in data[0:8])
    if conf.blockcmd:
        # standard everything is blocked!
        print("\t - " + "Growatt command block checking started")
        blockflag = True
        confcmd = None
        # partly block configure Shine commands
        if header[14:16] == "18":
            if conf.blockcmd:
                if header[6:8] == "05" or header[6:8] == "06":
                    confdata = decrypt(data)
                else:
                    confdata = data

                # get conf command (location depends on record type), maybe later more flexibility is needed
                if header[6:8] == "06":
                    confcmd = confdata[76:80]
                else:
                    confcmd = confdata[36:40]

                if header[14:16] == "18":
                    # do not block if configure time command of configure IP (if noipf flag set)
                    if conf.verbose:
                        print("\t - Grott: Shine Configure command detected")
                    if confcmd == "001f" or (confcmd == "0011" and conf.noipf):
                        blockflag = False
                        if confcmd == "001f":
                            confcmd = "Time"
                        if confcmd == "0011":
                            confcmd = "Change IP"
                        if conf.verbose:
                            print("\t - Grott: Configure command not blocked : ", confcmd)
                else:
                    # All configure inverter commands will be blocked
                    if conf.verbose:
                        print("\t - Grott: Inverter Configure command detected")

        # allow records:
        if header[12:16] in conf.recwl:
            blockflag = False

        if blockflag:
            shown = confcmd if confcmd else "n/a"
            print("\t - Grott: Record blocked: ", header[12:16], " command=", shown)
            return "blocked"

    return "forward"

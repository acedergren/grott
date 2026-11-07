# grottpolicy.py
# Record validation and command-block policy extracted from grottproxy.
# Decisions are pure with respect to sockets: the proxy applies them.

try:
    import libscrc
except Exception:
    libscrc = None

from grottcrypto import decrypt


# One TCP read is not one Growatt record. The header length field is the
# frame boundary. Protocol 05/06 includes a 2-byte CRC in that length.
# Older protocols are length-checked only, matching the project README.
MAX_FRAME_LENGTH = 65535


def validate_record(xdata):
    # validata data record on length and CRC (for "05" and "06" records)

    data = bytes.fromhex(xdata)
    ldata = len(data)
    if ldata < 8:
        return 8
    len_orgpayload = int.from_bytes(data[4:6], "big")
    protocol = "%02x" % data[3]

    if protocol in ("05", "06"):
        lcrc = 4
        crc = int.from_bytes(data[ldata - 2:ldata], "big")
    else:
        lcrc = 0
        crc = None

    len_realpayload = (ldata * 2 - 12 - lcrc) / 2
    if len_realpayload != len_orgpayload:
        return 8
    # Protocol 02 and older converter types: length only.
    # CRC is defined for 05 and 06. Comparing an unset CRC raised
    # UnboundLocalError and dropped those records.
    if protocol not in ("05", "06"):
        return 0
    try:
        crc_calc = libscrc.modbus(data[0:ldata - 2])
    except Exception:
        # libscrc is not installed yet: keep the historical length-only pass.
        return 0
    if crc != crc_calc:
        return 8
    return 0


def declared_frame_length(header):
    """Return the total frame size implied by an 8-byte header.

    None means the header is incomplete. -1 means the declared size is not
    a usable frame (too small or above MAX_FRAME_LENGTH).
    """
    if len(header) < 8:
        return None
    protocol = header[3]
    declared = int.from_bytes(header[4:6], "big")
    if protocol in (0x05, 0x06):
        total = 8 + declared
    else:
        total = 6 + declared
    if total < 8 or total > MAX_FRAME_LENGTH:
        return -1
    return total


def take_frames(buffer):
    """Split a TCP byte stream into complete Growatt frames.

    Returns (frames, remainder, error). error is a short reason with no
    payload bytes, or None.
    """
    frames = []
    while len(buffer) >= 8:
        total = declared_frame_length(buffer[:8])
        if total is None:
            break
        if total < 0:
            return frames, buffer, "invalid declared length"
        if len(buffer) < total:
            break
        frames.append(bytes(buffer[:total]))
        buffer = buffer[total:]
    return frames, buffer, None


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

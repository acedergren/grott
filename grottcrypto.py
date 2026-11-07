# grottcrypto.py
# XOR mask used by Growatt TCP records since Grott 2.x.
# Extracted from grottdata.py without changing the mask or the header rule.
# The first eight bytes stay clear. This is not authentication.

from itertools import cycle


def decrypt(decdata):
    ndecdata = len(decdata)

    # Create mask and convert to hexadecimal
    mask = "Growatt"
    hex_mask = ['{:02x}'.format(ord(x)) for x in mask]
    nmask = len(hex_mask)

    # start decrypt routine
    unscrambled = list(decdata[0:8])  # take unscramble header

    for i, j in zip(range(0, ndecdata - 8), cycle(range(0, nmask))):
        unscrambled = unscrambled + [decdata[i + 8] ^ int(hex_mask[j], 16)]

    result_string = "".join("{:02x}".format(n) for n in unscrambled)

    print("\t - " + "Growatt data decrypted V2")
    return result_string

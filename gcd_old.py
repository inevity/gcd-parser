#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Thanks to TurboCCC and kunix for all your work!

GCD_SIG = b"GARMINd\00"

from binascii import hexlify
from struct import unpack
from grmn import ChkSum, devices
import sys

FILE = sys.argv[1]

TLV_TYPES = {
    0x0001: "Checksum remainder",
    0x0002: "Skip?",
    0x0003: "Part number",
    0x0005: "Copyright notice",
    0x0006: "Block Type 7 format definition",
    0x0007: "Binary descriptor",
    0x0008: "Binary Region 0C (boot.bin)",
    0x0401: "Binary Component Firmware (SensorHub, ANT_BLE_BT, GPS, WiFi)",
    0x0505: "Binary Region 05",
    0x0555: "Binary Region 55",
    0x0557: "Binary Region 57",
    0x02bd: "Binary Region 0E (fw_all.bin)",
    0xffff: "EOF marker",
}

cksum = ChkSum()
all_cksum_ok = True
last_type6_fids = []
last_type6_format = ""
last_type6_fields = []

def get_tlv_comment(ttype):
    if ttype in TLV_TYPES:
        return TLV_TYPES[ttype]
    else:
        return "Type {:04x} / {:d}".format(ttype, ttype)

print("Opening {}".format(FILE))

def parseTLVheader(hdr):
    (ttype, tlen) = unpack("<HH", hdr)
    return (ttype, tlen)

def parseTLV1(payload):
    global cksum, all_cksum_ok
    if len(payload) != 1:
        print("  ! Checksum has invalid length!")
        all_cksum_ok = False
    expected = cksum.get()
    payload = unpack("B", payload)[0]
    state = "INVALID!"
    if expected == payload:
        state = "valid."
    else:
        all_cksum_ok = False
    print("  - Checksum expected: {:02x} / found: {:02x} - {}".format(expected, payload, state))

def parseTLV3(payload):
    # Part number?
    # 10 d4 5c 13 04 45 0d 14 41  - GPSMAP6x0_370
    # 10 d4 5c 13 04 45 0d 14 41  - fenix5Plus_SensorHub_220
    # 10 d4 5c 13 04 45 0d 14 41  - fenix_D2_tactix_500
    # 10 d4 5c 13 04 45 0d 14 41  - fenix5_1100
    # 10 d4 5c 13 04 45 0d 14 41  - fenix5Plus_420_rollback
    # 10 d4 5c 13 04 45 0d 14 41  - fenix5Plus_420
    # 10 d4 5c 13 04 45 0d 14 41  - fenix5Plus_510
    # 10 d4 5c 13 04 45 0d 14 41  - D2Delta_300
    print("  > " + " ".join("{:02x}".format(c) for c in payload))
    #print(hexlify(payload).decode("utf-8"))
    print("  > " + repr(payload))

def parseTLV6(payload):
    global last_type6_format, last_type6_fields, last_type6_fids
    # Describes following TLV7:
    # http://www.gpspassion.com/forumsen/topic.asp?TOPIC_ID=137838&whichpage=12
    # First nibble might be data type: 0 = B, 1 = H, 2 = L
    FIELD_TYPES = {
        0x000a: ["B", "XOR flag/value"],
        0x000b: ["B", "Reset/Downgrade flag"],
        0x1009: ["H", "Device hw_id"],
        0x100a: ["H", "Block type"],
        0x100d: ["H", "Firmware version"],
        0x1014: ["H", "Field 1014"],
        0x1015: ["H", "Field 1015"],
        0x1016: ["H", "Field 1016 (WiFi fw)"],
        0x2015: ["L", "Block size"],
        0x5003: ["", "End of definition marker"],
    }
    if len(payload) % 2 != 0:
        print("  ! Invalid payload length!")
    
    last_type6_fids = []
    last_type6_format = ""
    last_type6_fields = []

    for i in range(0, len(payload), 2):
        fid = unpack("H", payload[i:i+2])[0]
        fdef = FIELD_TYPES[fid]
        print("  - {:04x}: {}".format(fid, fdef[1]))
        last_type6_fids.append(fid)
        last_type6_format += fdef[0]
        last_type6_fields.append(fdef[1])

def parseTLV7(payload):
    global last_type6_format, last_type6_fields, last_type6_fids
    values = unpack("<" + last_type6_format, payload)
    for i, v in enumerate(values):
        fid = last_type6_fids[i]
        fdesc = last_type6_fields[i]
        if fid == 0x1009:
            print("  - {:>20}: 0x{:04x} / {:d} ({})".format(fdesc, v, v, devices.DEVICES.get(v, "Unknown device")))
        elif fid == 0x2015:
            print("  - {:>20}: {} Bytes".format(fdesc, v))
        else:
            print("  - {:>20}: 0x{:04x} / {:d}".format(fdesc, v, v))

with open(FILE, "rb") as f:
    sig = f.read(8)
    cksum.add(sig)
    if sig == GCD_SIG:
        print("Signature ok.")
    else:
        raise Exception("Signature mismatch ({}, should be {})!".format(repr(sig), repr(GCD_SIG)))

    i = 0
    fw_all_done = False
    cur_ttype = None

    while True:
        hdr = f.read(4)
        cksum.add(hdr)
        (ttype, tlen) = parseTLVheader(hdr)
        print("#{:04} TLV type {:04x} (offset 0x{:x}, length {} Bytes) - {}".format(i, ttype, f.tell(), tlen, get_tlv_comment(ttype)))
        if ttype == 0xFFFF:
            print("End of file reached.")
            break
        payload = f.read(tlen)
        if ttype == 0x0001:
            parseTLV1(payload)
        elif ttype == 0x0003:
            parseTLV3(payload)
        elif ttype == 0x0006:
            parseTLV6(payload)
        elif ttype == 0x0007:
            parseTLV7(payload)
        elif ttype == 0x02bd and not fw_all_done:
            hw_id = unpack("H", payload[0x208:0x20a])[0]
            fw_ver = unpack("H", payload[0x20c:0x20e])[0]
            print("  - Device ID: {:04x} / {:d} ({})".format(hw_id, hw_id, devices.DEVICES.get(hw_id, "Unknown device")))
            print("  - Firmware version: {:04x} / {:d}".format(fw_ver, fw_ver))
            fw_all_done = True
        else:
            payloadshort = payload[:64]
            #print("  > " + " ".join("{:02x}".format(c) for c in payloadshort))
            #print(hexlify(payload).decode("utf-8"))
            #print("  > " + repr(payloadshort))
        cksum.add(payload)
        if ttype in [0x0008, 0x0401, 0x0505, 0x0555, 0x0557, 0x02bd]:
            outname = "{}_{:04x}.bin".format(FILE, ttype)
            if ttype != cur_ttype:
                mode = "wb"
            else:
                mode = "ab"
            cur_ttype = ttype
            with open(outname, mode) as of:
                of.write(payload)
        i = i + 1

if not all_cksum_ok:
    print("There were problems with at least one checksum!")
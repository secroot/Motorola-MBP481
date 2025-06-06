#!/usr/bin/env python3
"""
mbp481_crc_discovery_fuzzer.py – discover the checksum required for ATE 0x0D frames
===================================================================================
This helper fuzzer connects to the Motorola MBP481‑AXL UART, switches it into
ATE mode (answering the boot prompt with "y"), waits until the camera is ready,
dann sends 0x0D‑Frames with Test‑Payloads und verschiedenen 16‑Bit‑Checksummen.
Sobald ein Frame *keinen* Error mehr auslöst, wird "GOOD ★" ausgegeben.

Usage
-----
    python3 mbp481_crc_discovery_fuzzer.py SERIAL [--baud 115200] [--max-len 16]

Dependencies: pyserial (apt package *python3-serial*)
"""
from __future__ import annotations
import argparse
import serial
import sys
import time
from typing import Callable, List, Tuple

# ---------- CRC / checksum helpers ----------

def sum8(data: bytes) -> int:
    return sum(data) & 0xFF

def sum16_le(data: bytes) -> int:
    return sum(data) & 0xFFFF

def sum16_be(data: bytes) -> int:
    s = sum(data) & 0xFFFF
    return ((s & 0xFF) << 8) | (s >> 8)

def crc16_ibm(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else crc >> 1
    return crc & 0xFFFF

def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return crc & 0xFFFF

ALGORITHMS: List[Tuple[str, Callable[[bytes], int]]] = [
    ("SUM8",        sum8),
    ("SUM16-LE",    sum16_le),
    ("SUM16-BE",    sum16_be),
    ("CRC16-IBM",   crc16_ibm),
    ("CRC16-CCITT", crc16_ccitt),
]

ERROR_STRINGS = [b"Error", b"CMD", b"Preamble"]

PATTERN = (b"ABCDEFGHIJKLMNOPQRSTUVWXYZ" +
           b"abcdefghijklmnopqrstuvwxyz" +
           b"0123456789")

# ---------- serial helpers ----------

def read_until(ser: serial.Serial, substr: bytes, timeout: float = 10.0) -> bool:
    """Read until *substr* appears or timeout expires. Returns True if found."""
    deadline = time.monotonic() + timeout
    buf = b""
    while time.monotonic() < deadline:
        buf += ser.read(ser.in_waiting or 1)
        if substr in buf:
            return True
    return False

# ---------- main fuzz logic ----------

def main() -> None:
    ap = argparse.ArgumentParser(description="Discover ATE CRC for opcode 0x0D")
    ap.add_argument("serial", help="/dev/ttyUSBx")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--max-len", type=int, default=32)
    args = ap.parse_args()

    try:
        ser = serial.Serial(args.serial, args.baud, timeout=0.05)
    except serial.SerialException as e:
        sys.exit(f"[!] cannot open serial: {e}")

    print(f"[*] Connected {args.serial} at {args.baud} bps")

    # ---------- BootSync ----------
    print("[*] Waiting for boot prompt ('y'/'Y') …")
    if not read_until(ser, b"Please key 'y'", 20.0):
        sys.exit("[!] Boot prompt not detected – aborting")

    ser.write(b"y\r")
    ser.flush()
    print("[*] Sent 'y' for ATE mode, waiting for ATE ready …")

    # Accept any of the observed ready strings
    if not (read_until(ser, b"Start ATE", 6.0) or
            read_until(ser, b"Start ATE Test", 4.0) or
            read_until(ser, b"eATE_INIT", 4.0)):
        print("[!] No Start ATE*/eATE_INIT seen, continuing anyway …")

    # ---------- Fuzz loop ----------
    for length in range(1, args.max_len + 1):
        payload = PATTERN[:length]
        print(f"[LEN {length}] …")
        accepted = False

        for name, func in ALGORITHMS:
            frame_wo_crc = bytes([0x55, 0x0D, length & 0xFF, (length >> 8) & 0xFF]) + payload
            crc = func(payload) if name.startswith("SUM") else func(frame_wo_crc)
            frame = frame_wo_crc + bytes([crc & 0xFF, (crc >> 8) & 0xFF]) + b"\r"

            ser.reset_input_buffer()
            ser.write(frame)
            ser.flush()
            time.sleep(0.1)
            resp = ser.read(ser.in_waiting or 1)
            ok = not any(err in resp for err in ERROR_STRINGS)
            status = "GOOD ★" if ok else "error"
            print(f"  {name:11s} 0x{crc:04X}  →  {status}")
            if ok:
                accepted = True

        # Brute‑force CRC only if nothing worked
        if not accepted:
            print("  brute‑forcing CRC …", end="", flush=True)
            ser.reset_input_buffer()
            found = False
            for crc in range(0x0000, 0x10000):
                frame = (bytes([0x55, 0x0D, length & 0xFF, (length >> 8) & 0xFF]) +
                         payload + bytes([crc & 0xFF, crc >> 8]) + b"\r")
                ser.write(frame)
                ser.flush()
                time.sleep(0.02)
                resp = ser.read(ser.in_waiting or 1)
                if not any(err in resp for err in ERROR_STRINGS):
                    print(f" found 0x{crc:04X} ★")
                    found = True
                    break
            if not found:
                print(" none")

    print("[*] Done. Closing serial.")
    ser.close()

if __name__ == "__main__":
    main()

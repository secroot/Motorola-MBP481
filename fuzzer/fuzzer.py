#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sehr einfacher Fuzzer: betritt einen Parser, sendet n Random-Pakete und
kehrt zum Root-Prompt zurück.  Fokus liegt auf 'telemetry' (d) u. Loader.

Usage:
    python3 fuzzer.py /dev/ttyUSB0 [telemetry|loader] [--count 100]
"""

import sys, time, argparse, os, random, serial

ROOT_PROMPT = b"mode."
ESC_SAFE_EXIT = b"\x1b"        # funktioniert für unsere Firmware
BAUD_DEFAULT  = 115200
LOGFILE       = "uart_fuzz.log"

def open_port(dev, baud):
    return serial.Serial(dev, baudrate=baud, bytesize=8, parity='N',
                         stopbits=1, timeout=0.05)

def wait_root(ser, to=3.0):
    buf=b""; t0=time.time()
    while time.time()-t0<to:
        buf+=ser.read(128)
        if ROOT_PROMPT in buf:
            return True
    return False

def tx(ser, data, sleep=0.02):
    ser.write(data); ser.flush(); time.sleep(sleep)

def rand_packet():
    ln = random.randint(4, 16)
    return os.urandom(ln)

def enter_parser(ser, mode):
    if mode=="telemetry":
        tx(ser, b"d\r")
        return wait_root(ser, 0.5) is False   # prompt verschwindet -> angenommen
    elif mode=="loader":
        tx(ser, b"\x1b\x1b\x1bR\x00\x00\x00\x00\x20\x00")
        return True
    else:
        raise ValueError("unknown mode")

def exit_parser(ser):
    tx(ser, ESC_SAFE_EXIT)
    wait_root(ser, 1.0)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port")
    ap.add_argument("mode", choices=["telemetry", "loader"])
    ap.add_argument("--count", type=int, default=300)
    ap.add_argument("--baud",  type=int, default=BAUD_DEFAULT)
    args = ap.parse_args()

    ser = open_port(args.port, args.baud)
    with open(LOGFILE, "wb") as lf:
        if not wait_root(ser, 5.0):
            print("[!] Kein Root-Prompt – Board erst neu booten!")
            sys.exit(1)

        print(f"[i] entering '{args.mode}' fuzzer …")
        lf.write(f"> entering {args.mode}\n".encode())

        if not enter_parser(ser, args.mode):
            print("[!] Einstieg fehlgeschlagen")
            sys.exit(1)

        for _ in range(args.count):
            pkt = rand_packet()
            tx(ser, pkt)
            lf.write(b"> " + pkt.hex(sep=" ").encode() + b"\n")
            lf.write(b"< " + ser.read(256).hex(sep=" ").encode() + b"\n")

        exit_parser(ser)
        print("[+] fuzzing finished – see", LOGFILE)

if __name__ == "__main__":
    main()

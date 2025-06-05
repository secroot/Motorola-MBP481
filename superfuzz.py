#!/usr/bin/env python3
"""
mbp481_superfuzz.py – Targeted Opcode/Chain Fuzzer für MBP481AXL UART ATE-Mode
Features: Length/Overflow-Test, Payload-Fuzz, Kombinationsangriffe

Nutzung:
  python mbp481_superfuzz.py /dev/ttyUSB0 08        # Nur Op 0x08 intensiv fuzz'n
  python mbp481_superfuzz.py /dev/ttyUSB0 0D        # Nur Op 0x0D Fehlerfuzzing
  python mbp481_superfuzz.py /dev/ttyUSB0 combo     # Chained Fuzz (0x72→08 etc.)
"""
import sys, time, serial, random

if len(sys.argv) < 3:
    sys.exit("Usage: mbp481_superfuzz.py <serial_dev> [08|0D|combo]")

DEV  = sys.argv[1]
MODE = sys.argv[2].lower()
BAUD = 115200

ser = serial.Serial(DEV, BAUD, timeout=0.3)
log = open("uart_superfuzz.log", "wb", buffering=0)

def hexdump(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)

def send(frame: bytes, note="") -> bytes:
    ser.write(frame)
    time.sleep(0.12)
    resp = ser.read(512)
    log.write(f"> {note} {hexdump(frame)}\n".encode())
    if resp:
        log.write(f"< {hexdump(resp)}\n".encode())
    return resp

def wait_prompt():
    # Warte auf ATE-Prompt ("Please key 'y'")
    print("[i] Waiting for UART ATE prompt …")
    buf = b""
    while b"Please key 'y'" not in buf:
        buf += ser.read(256)
    print("[i] Prompt detected. Entering ATE mode!")
    ser.write(b"y")
    time.sleep(0.25)
    ser.reset_input_buffer()

# --------- Hauptlogik ---------

wait_prompt()

# Fuzz-Szenarien festlegen
if MODE == "08":
    op = 0x08
    for ln in [0, 1, 2, 4, 8, 16, 32, 64, 128]:
        for test in range(8):
            # Payload random, Länge = ln
            payload = bytes(random.getrandbits(8) for _ in range(ln))
            frame = b"\x55\xAA" + bytes([op, ln & 0xFF, (ln >> 8) & 0xFF]) + payload
            note = f"08-Len{ln:02d}-Test{test}"
            resp = send(frame, note)
            if b"Preamble Error" in resp:
                print(f"\n[!] Preamble Error on 0x08 with len={ln}, payload={hexdump(payload)}")

elif MODE == "0d":
    op = 0x0D
    for ln in [0, 1, 2, 4, 8, 16, 32, 64, 128]:
        for test in range(8):
            payload = bytes(random.getrandbits(8) for _ in range(ln))
            frame = b"\x55\xAA" + bytes([op, ln & 0xFF, (ln >> 8) & 0xFF]) + payload
            note = f"0D-Len{ln:02d}-Test{test}"
            resp = send(frame, note)
            if b"Preamble Error" in resp:
                print(f"\n[!] Preamble Error on 0x0D with len={ln}, payload={hexdump(payload)}")

elif MODE == "combo":
    # Kombinierte Ketten: Erst 0x72, dann 0x08 und 0x0D mit Payload
    # Reihenfolge lässt sich beliebig erweitern
    op_trigger = 0x72
    op_targets = [0x08, 0x0D, 0xD8, 0xD9]
    for op in op_targets:
        # Trigger
        trigger = b"\x55\xAA" + bytes([op_trigger, 0, 0])
        send(trigger, f"TRIGGER-72")
        time.sleep(0.12)
        # Dann Fuzzen
        for ln in [0, 1, 2, 4, 8, 16, 32]:
            for test in range(6):
                payload = bytes(random.getrandbits(8) for _ in range(ln))
                frame = b"\x55\xAA" + bytes([op, ln & 0xFF, (ln >> 8) & 0xFF]) + payload
                note = f"Chain72-Op{op:02X}-Len{ln:02d}-Test{test}"
                resp = send(frame, note)
                if b"Preamble Error" in resp:
                    print(f"\n[!] Chain: Preamble Error on {op:02X} with len={ln}, payload={hexdump(payload)}")

else:
    sys.exit("Unknown mode: use 08, 0D, or combo.")

print("\n[+] Superfuzz run finished. Check uart_superfuzz.log!")
ser.close()
log.close()

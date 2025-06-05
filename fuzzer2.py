#!/usr/bin/env python3
"""
mbp481_fuzzer.py – UART-Fuzzer für Motorola MBP481AXL

• Fuzzing direkt nach Prompt ("Please key 'y' ..."), typisches 5s-Zeitfenster!
• Zwei Hauptmodi:
    - loader  → Bootloader-Kommandos, Escaping, Frame-Varianten
    - ate     → ATE-Protokoll (Header 0x55AA + Opcode + ...)
• Recovery-Mechanismen und Logging optimiert auf validierte Erkenntnisse

Usage:
    python3 mbp481_fuzzer.py /dev/ttyUSB0 loader
    python3 mbp481_fuzzer.py /dev/ttyUSB0 ate
    python3 mbp481_fuzzer.py /dev/ttyUSB0 raw

Logfile:
    • uart_fuzz.log – Klartext & Hex-Dump von TX/RX

Autor: ChatGPT x hazardcore, 2025
"""
import sys, time, struct, serial
from functools import reduce

if len(sys.argv) < 2:
    sys.exit("Usage: mbp481_fuzzer.py <serial_dev> [raw|ate|loader]")

DEV  = sys.argv[1]
MODE = sys.argv[2].lower() if len(sys.argv) > 2 else "raw"
BAUD = 115200

def hexdump(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)

def crc8_xor(buf: bytes) -> int:
    return reduce(lambda a, b: a ^ b, buf, 0) & 0xFF

ser = serial.Serial(DEV, BAUD, timeout=0.3)
log = open("uart_fuzz.log", "wb", buffering=0)

def send(frame: bytes, info: str = "") -> bytes:
    ser.write(frame)
    time.sleep(0.15)
    resp = ser.read(512)
    log.write(f"> {info} {hexdump(frame)}\n".encode())
    if resp:
        log.write(f"< {hexdump(resp)}\n".encode())
    return resp

print(f"[i] waiting for prompt on {DEV} …")
buf = b""
# Prompt-Varianten laut Canvas: "Please key 'y'", "Debug Info", "Day mode CMOS", etc.
PROMPTS = [b"Please key", b"Debug Info", b"CMOS", b"execute ATE"]
while not any(p in buf for p in PROMPTS):
    buf += ser.read(256)
print("[i] prompt seen – entering 5-s window")

# Boot-Modus aktivieren, falls notwendig
if MODE == "loader":
    print("[*] Entering loader mode: Sending ESC ESC …")
    ser.write(b"\x1B\x1B")
    time.sleep(0.1)
elif MODE == "ate":
    print("[*] Entering ATE mode: Sending 'y' …")
    ser.write(b"y")
    time.sleep(0.1)

freeze = 0

for val in range(256):
    if MODE == "loader":
        # Loader-Frame: ESC 'R' addr(4B) len(2B), ggf. mit/ohne CRC – alle Varianten rotieren
        addr = 0
        length = 0x20
        frame = b"\x1B\x52" + struct.pack("<I", addr) + struct.pack("<H", length)
        # CRC8-Variante (experimentell, viele Bootloader mögen so was):
        crc = crc8_xor(frame)
        frame_crc = frame + bytes([crc])
        # Teste beide Frames: mit & ohne CRC
        if val % 2 == 0:
            test_frame = frame
            info = "ESC R noCRC"
        else:
            test_frame = frame_crc
            info = "ESC R +CRC"
    elif MODE == "ate":
        # ATE-Protokoll: 0x55AA + Opcode + Len_L + Len_H (Len=0 für reine OpCodes)
        header = b"\x55\xAA"
        opcode = val
        frame = header + bytes([opcode, 0x00, 0x00])
        info = f"ATE-Op {opcode:02X}"
        test_frame = frame
    else:
        # Roher Byte-Sweep (single byte), kann abweichende Prompts triggern
        test_frame = bytes([val])
        info = "RAW"

    response = send(test_frame, info=info)

    if val % 0x10 == 0:
        print(".", end="", flush=True)

    # Freeze-Watchdog: 3x keine Antwort = Recovery-Frame
    if response:
        freeze = 0
    else:
        freeze += 1
        if freeze == 3:
            print("\n[!] no response – sending ESC NUL for recovery")
            ser.write(b"\x1B\x00")
            time.sleep(0.5)
            freeze = 0

print("\n[+] fuzzing finished – see uart_fuzz.log")
ser.close()
log.close()

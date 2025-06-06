#!/usr/bin/env python3
"""
Tweak and Scan (rev-final_analysis)
====================================
Aktiviert einen vermuteten Funktions-Switch (Register 0xfd) und führt
danach einen vollständigen Register-Scan durch, um die Auswirkungen
zu kartieren und versteckte Funktionen aufzudecken.
"""

import asyncio, sys, time, logging, argparse, json, re

# --- Setup (Logging, UART-Session, enter_cmos_mode, write_register bleiben gleich) ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-4s [%(name)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("Tweak-and-Scan")

class UARTSession:
    def __init__(self, port: str, baud: int = 115200): self.port, self.baud, self.reader, self.writer = port, baud, None, None
    async def open(self): import serial_asyncio; self.reader, self.writer = await serial_asyncio.open_serial_connection(url=self.port, baudrate=self.baud); log.info(f"[UART] Connected to {self.port}")
    async def close(self): 
        if self.writer: self.writer.close(); await self.writer.wait_closed(); log.info("[UART] Closed")
    async def write(self, data: bytes): self.writer.write(data); await self.writer.drain()
    async def read_raw(self, timeout=0.2, n_bytes=2048) -> bytes | None:
        try: return await asyncio.wait_for(self.reader.read(n_bytes), timeout=timeout)
        except asyncio.TimeoutError: return None

async def enter_cmos_mode(sess: UARTSession):
    log.info("[i] Waiting for device prompt...")
    buf = b""; deadline = time.time() + 20; prompt_found = False
    while time.time() < deadline:
        data = await sess.read_raw(timeout=0.1)
        if data:
            buf += data
            if b"Please key" in buf and not prompt_found:
                prompt_found = True; log.info("[i] Prompt detected! Sending 'c'..."); await sess.write(b"c\r"); break
    if not prompt_found: log.error("Device prompt not found."); return False
    log.info("[i] Waiting for 'Example:' confirmation prompt...")
    confirmation_buf = b""; deadline = time.time() + 10
    while time.time() < deadline:
        data = await sess.read_raw()
        if data:
            confirmation_buf += data
            if b"Example:" in confirmation_buf:
                log.info("[SUCCESS] CMOS write mode confirmed and ready.")
                await asyncio.sleep(0.2); await sess.read_raw(timeout=0.5)
                return True
    log.error("[FAIL] Did not receive CMOS confirmation prompt."); return False

async def write_register(sess: UARTSession, addr: int, value: int):
    log.info(f"--- Writing 0x{value:02x} to Register 0x{addr:02x} ---")
    command_str = f"01{addr:02x}{value:02x}\r"
    await sess.write(command_str.encode())
    await asyncio.sleep(0.2)
    await sess.read_raw() # Echo und Antwort verwerfen, da wir den Erfolg nicht prüfen

# --- Scan-Funktion aus dem Mapper ---
async def scan_and_save(sess: UARTSession, output_file: str):
    log.info(f"--- Starting Full Register Scan. Output will be saved to {output_file} ---")
    register_map = {}
    for addr in range(256):
        hex_addr = f"{addr:02x}"
        command_str = f"00{hex_addr}00\r"
        await sess.write(command_str.encode())
        await sess.read_raw(timeout=0.1)
        await asyncio.sleep(0.1)
        response_bytes = await sess.read_raw(timeout=0.2)
        if response_bytes:
            response_str = response_bytes.decode('utf-8', 'ignore').strip()
            register_map[f"0x{hex_addr}"] = response_str
        else:
            register_map[f"0x{hex_addr}"] = "NO_RESPONSE"
        if addr % 16 == 15:
            log.info(f"Scan progress: {addr+1}/256...")
    log.info(f"--- Scan finished. Saving results to {output_file} ---")
    with open(output_file, 'w') as f:
        json.dump(register_map, f, indent=4, sort_keys=True)
    log.info("Save successful.")

# --- Hauptprogramm ---
async def main():
    parser = argparse.ArgumentParser(description="Tweak-and-Scan: Find hidden functions.", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("port", help="Serial port, e.g., /dev/ttyUSB0")
    parser.add_argument("--output", required=True, help="Output JSON file for the tweaked state (e.g., tweaked_dump.json).")
    args = parser.parse_args()

    sess = UARTSession(args.port)
    try:
        await sess.open()
        if not await enter_cmos_mode(sess): return
            
        # Schritt 1: Den Schalter umlegen
        log.info(">>> Activating tweak-mode by writing 0x01 to register 0xfd...")
        await write_register(sess, addr=0xfd, value=0x01)
        log.info(">>> Tweak activated. Pausing for 1 second before scanning...")
        await asyncio.sleep(1.0)

        # Schritt 2: Das System im neuen Zustand scannen
        await scan_and_save(sess, args.output)

    finally:
        await sess.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("\nScan terminated by user.")

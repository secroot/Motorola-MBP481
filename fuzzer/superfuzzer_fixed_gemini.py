#!/usr/bin/env python3
"""
SuperFuzz rev-d3 (2025-06-07)
=============================
Target       : Motorola Babyphone **MBP481-AXL** – UART ATE mode
Purpose      : Debugging "Preamble Errors" by testing timing and endianness.
Author       : Babyphone PWN / ChatGPT / Coding-Assistent
License      : MIT
"""

import asyncio, os, sys, time, argparse, logging

# ... (Logging und UARTSession Klasse bleiben unverändert) ...
############################ Logging ########################################
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-4s [%(name)s] %(message)s",
    handlers=[
        logging.FileHandler("uart_superfuzz.log", "w"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("root")

############################ UART ###########################################
class UARTSession:
    def __init__(self, port: str, baud: int = 115200):
        self.port = port
        self.baud = baud
        self.reader = self.writer = None
        self.last = time.time()

    async def open(self):
        import serial_asyncio
        self.reader, self.writer = await serial_asyncio.open_serial_connection(
            url=self.port, baudrate=self.baud
        )
        log.info("[UART] connected %s %d bps", self.port, self.baud)

    async def close(self):
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
            log.info("[UART] closed")

    async def write(self, data: bytes):
        self.writer.write(data)
        await self.writer.drain()
        self.last = time.time()

    async def read(self, n: int = 1024) -> bytes:
        try:
            data = await asyncio.wait_for(self.reader.read(n), timeout=0.2)
            if data:
                self.last = time.time()
            return data
        except asyncio.TimeoutError:
            return b''

############################ Boot‑Sync ######################################
async def boot_sync(sess: UARTSession):
    PROMPT = b"Please key 'y'"
    READY  = (b"Start ATE", b"Start ATE Test", b"eATE_INIT")

    log.info("[i] Waiting for UART ATE prompt …")
    buf = b""
    deadline = time.time() + 15 # Timeout für den Prompt
    while PROMPT not in buf and time.time() < deadline:
        buf += await sess.read()
    
    if PROMPT not in buf:
        log.error("[!!!] ATE prompt not detected. Exiting.")
        sys.exit(1)

    await sess.write(b"y\r")
    log.info("[i] Prompt detected. Entering ATE mode!")

    buf = b""; deadline = time.time() + 10
    while time.time() < deadline:
        buf += await sess.read()
        if any(m in buf for m in READY):
            log.info("[i] ATE ready marker seen.")
            return
    log.warning("[!] No explicit ATE ready marker – continuing anyway …")


############################ Frame Builder ##################################
CR = b"\x0D"

def build_frame(op: int, payload: bytes) -> bytes:
    """Assemble ATE frame. Includes test for endianness."""
    pre = b"\x55" if op == 0x0D else b"\x55\xAA"
    
    # <<< TEST: Byte-Reihenfolge (Endianness) der Längenangabe >>>
    # Standard ist "little". Entferne das '#' bei der zweiten Zeile, um "big" zu testen.
    # ln  = len(payload).to_bytes(2, "little")
    ln  = len(payload).to_bytes(2, "big") 
    
    frame = pre + bytes([op]) + ln + payload
    if op == 0x0D:
        frame += CR
    return frame

############################ Fuzz Logic #####################################
async def fuzz_opcode(sess: UARTSession, op: int):
    log.info("[FZ] Fuzzing opcode 0x%02X...", op)
    lengths = [0, 1, 2, 4, 8, 16] if op == 0x0D else [0, 1, 2, 4, 8, 16, 32]
    for ln in lengths:
        # Wir testen jede Länge nur 2 mal, um schneller Feedback zu bekommen
        for _ in range(2):
            payload = os.urandom(ln)
            frame = build_frame(op, payload)
            
            await sess.write(frame)
            echo = await sess.read()

            if echo and b"Preamble Error" in echo:
                hex_frame = ' '.join(f'{b:02x}' for b in frame)
                log.warning("[!] Preamble Error on 0x%02X len=%d. Sent: %s", op, ln, hex_frame)
            elif echo:
                log.info(f"[OK] Response on 0x{op:02X} len={ln}: {echo.strip()}")

            await asyncio.sleep(0.1) # Etwas längere Pause zwischen den Paketen

async def fuzz_combo(sess: UARTSession):
    log.info("[FZ] Starting combo fuzz for opcodes: 0x08, 0x0D, 0xD8, 0xD9")
    for op in (0x08, 0x0D, 0xD8, 0xD9):
        await fuzz_opcode(sess, op)
    log.info("[FZ] Combo fuzz finished.")

############################ Main ###########################################
async def main():
    ap = argparse.ArgumentParser("SuperFuzz rev-d3")
    ap.add_argument("port")
    ap.add_argument(
        "opcode",
        nargs="?",
        default="combo",
        choices=["08", "0D", "D8", "D9", "combo"],
        help="single opcode or 'combo' (default)",
    )
    args = ap.parse_args()

    sess = UARTSession(args.port)
    await sess.open()
    try:
        await boot_sync(sess)
        
        # <<< TEST: Füge eine Verzögerung nach dem Sync hinzu >>>
        log.info("[i] Waiting 0.5s for device to settle after sync...")
        await asyncio.sleep(0.5)

        if args.opcode == "combo":
            await fuzz_combo(sess)
        else:
            await fuzz_opcode(sess, int(args.opcode, 16))
    finally:
        await sess.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("[i] Fuzzing by user aborted.")
    except Exception as e:
        log.error(f"[!!!] An unexpected error occurred: {e}", exc_info=True)

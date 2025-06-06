#!/usr/bin/env python3
"""
SuperFuzz rev-d6 (2025-06-07)
=============================
Target       : Motorola Babyphone **MBP481-AXL** – UART ATE mode
Purpose      : Targeted 2-byte payload fuzzing for Opcode 0x0D to find
               valid command structures.
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
            data = await asyncio.wait_for(self.reader.read(n), timeout=1.0)
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
    deadline = time.time() + 15
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
    pre = b"\x55" if op == 0x0D else b"\x55\xAA"
    endianness = "big" if op == 0x0D else "little"
    ln = len(payload).to_bytes(2, endianness)
    frame = pre + bytes([op]) + ln + payload
    if op == 0x0D:
        frame += CR
    return frame

############################ Fuzz Logic #####################################
async def fuzz_random_payload(sess: UARTSession, op: int):
    # Diese Funktion bleibt für die anderen Opcodes nützlich
    log.info("[FZ-RAND] Fuzzing opcode 0x%02X with random data...", op)
    lengths = [0, 1, 2, 4, 8]
    for ln in lengths:
        for _ in range(2):
            payload = os.urandom(ln)
            frame = build_frame(op, payload)
            await sess.write(frame)
            await asyncio.sleep(1.1)
            echo = await sess.read()
            hex_frame = ' '.join(f'{b:02x}' for b in frame)
            if echo:
                log.info(f"[OK] Response on 0x{op:02X} (len={ln}, sent: {hex_frame}): {echo.strip()}")
            else:
                log.info(f"[SILENCE] No response for 0x{op:02X} (len={ln}, sent: {hex_frame})")

async def fuzz_opcode_0D_2_bytes(sess: UARTSession):
    """Sucht gezielt nach gültigen 2-Byte-Payloads für Opcode 0x0D."""
    log.info("[FZ-0D-2B] Searching for valid 2-byte commands for opcode 0x0D...")
    # Wir iterieren durch alle 65536 Möglichkeiten (0x0000 bis 0xFFFF)
    for i in range(65536):
        # Wandle die Zahl i in zwei Bytes um (big-endian)
        payload = i.to_bytes(2, "big")
        frame = build_frame(0x0D, payload)
        
        await sess.write(frame)
        await asyncio.sleep(1.1)
        echo = await sess.read()

        if echo:
            response_text = echo.strip()
            hex_frame = ' '.join(f'{b:02x}' for b in frame)
            if b"Preamble Error" in response_text:
                # Diese können wir jetzt ignorieren, wenn wir wollen
                pass # log.info(f"[Preamble Error] on {hex_frame}")
            elif b"CMD Error" in response_text:
                log.warning(f"[CMD Error] on {hex_frame} -> Response: {response_text}")
            else:
                # DAS IST ES!
                log.critical(f"[!!! SUCCESS !!!] on {hex_frame} -> Response: {response_text}")

async def fuzz_combo(sess: UARTSession):
    log.info("[FZ] Starting combo fuzz...")
    await fuzz_opcode_0D_2_bytes(sess)
    for op in (0x08, 0xD8, 0xD9):
        await fuzz_random_payload(sess, op)
    log.info("[FZ] Combo fuzz finished.")

############################ Main ###########################################
async def main():
    ap = argparse.ArgumentParser("SuperFuzz rev-d6")
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
        log.info("[i] Waiting 0.5s for device to settle after sync...")
        await asyncio.sleep(0.5)

        op_val = args.opcode
        if op_val == "combo":
            await fuzz_combo(sess)
        elif op_val == "0D":
            await fuzz_opcode_0D_2_bytes(sess)
        else: # 08, D8, D9
            await fuzz_random_payload(sess, int(op_val, 16))
    finally:
        await sess.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("[i] Fuzzing by user aborted.")
    except Exception as e:
        log.error(f"[!!!] An unexpected error occurred: {e}", exc_info=True)

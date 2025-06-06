#!/usr/bin/env python3
"""
SuperFuzz rev‑d2 (2025‑06‑07)
=============================
Target       : Motorola Babyphone **MBP481‑AXL** – UART ATE mode
Purpose      : Minimal‑yet‑correct opcode fuzzer for 0x08, 0x0D, 0xD8, 0xD9 — now
               with the empirically verified frame layout per opcode and **no
               CRC bytes at all**.
Author       : Babyphone PWN / ChatGPT
License      : MIT

Quick Usage
-----------
    python3 superfuzz_fixed.py /dev/ttyUSB0           # fuzz 08,0D,D8,D9 (combo)
    python3 superfuzz_fixed.py /dev/ttyUSB0 08        # fuzz only opcode 0x08
    python3 superfuzz_fixed.py /dev/ttyUSB0 0D        # fuzz only opcode 0x0D

Frame Layout
------------
```
<PRE> <OP> <LEN_lo> <LEN_hi> [PAYLOAD] [CR]
```
* **0x08 / 0xD8 / 0xD9**
  * preamble `55 AA`
  * **kein** CRC, **kein** Terminator → Roh‑Echo beweist: Cam akzeptiert so.
* **0x0D**
  * preamble `55` (ein Byte!)
  * abschließendes **CR 0x0D** zwingend, sonst „Preamble Error“

Boot Sync
---------
Nach Eingabe `y` auf den Boot‑Prompt wartet das Skript auf beliebige Marker:
`Start ATE` | `Start ATE Test` | `eATE_INIT` (max. 10 s).
"""

import asyncio, os, sys, time, argparse, logging

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
        import serial_asyncio  # pip install pyserial‑asyncio
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
        data = await self.reader.read(n)
        if data:
            self.last = time.time()
        return data

############################ Boot‑Sync ######################################
async def boot_sync(sess: UARTSession):
    PROMPT = b"Please key 'y'"
    READY  = (b"Start ATE", b"Start ATE Test", b"eATE_INIT")

    log.info("[i] Waiting for UART ATE prompt …")
    buf = b""
    while PROMPT not in buf:
        buf += await sess.read()
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
    """Assemble ATE frame with the minimal valid structure."""
    pre = b"\x55" if op == 0x0D else b"\x55\xAA"
    ln  = len(payload).to_bytes(2, "little")
    frame = pre + bytes([op]) + ln + payload
    if op == 0x0D:
        frame += CR
    return frame

############################ Fuzz Logic #####################################
async def fuzz_opcode(sess: UARTSession, op: int):
    log.info("[FZ] opcode 0x%02X", op)
    lengths = [0, 1, 2, 4, 8, 16] if op == 0x0D else [0, 1, 2, 4, 8, 16, 32]
    for ln in lengths:
        for _ in range(6):
            payload = os.urandom(ln)
            frame = build_frame(op, payload)
            await sess.write(frame)
            echo = await sess.read()
            if b"Preamble Error" in echo:
                log.warning("[!] Preamble Error on 0x%02X len=%d", op, ln)
            await asyncio.sleep(0.02)

async def fuzz_combo(sess: UARTSession):
    for op in (0x08, 0x0D, 0xD8, 0xD9):
        await fuzz_opcode(sess, op)

############################ Main ###########################################
async def main():
    ap = argparse.ArgumentParser("SuperFuzz rev‑d2")
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
        if args.opcode == "combo":
            await fuzz_combo(sess)
        else:
            await fuzz_opcode(sess, int(args.opcode, 16))
    finally:
        await sess.close()

if __name__ == "__main__":
    asyncio.run(main())

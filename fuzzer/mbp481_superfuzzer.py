#!/usr/bin/env python3
"""
mbp481_superfuzzer.py  —  UART fuzzer for Motorola MBP481‑AXL (rev‑7)
====================================================================
Author : ChatGPT · Babyphone PWN
Date   : 2025‑06‑06 rev‑7  (fix concurrent read())
License: MIT

rev‑7 Patch Notes
-----------------
* **Fix:** RuntimeError "read() called while another coroutine is already
  waiting for incoming data".
  * `printer()` now *waits* for `boot_ready` before starting its RX loop,
    so BootSync is the only reader during boot‑detection.
* Minor: corrected logging format string.

Usage unchanged:
    python3 mbp481_superfuzzer.py /dev/ttyUSB0 --mode ate    --strategy memdump
    python3 mbp481_superfuzzer.py /dev/ttyUSB0 --mode loader --strategy overflow0d
"""
import asyncio
import logging
import re
import serial
import serial_asyncio
import sys
import time
from typing import Optional

###########################################################################
# Configuration constants
###########################################################################
BOOTSYNC_TIMEOUT = 20.0              # seconds to wait for boot banner
BOOTSYNC_RETRY_DELAY = 2.0           # wait before a second key‑press
FREEZE_TIMEOUT    = 5.0              # seconds with no RX/TX
INTER_FRAME_DELAY = 0.05             # 50 ms minimal gap

ATE_BANNER_RE   = re.compile(rb"Start ATE|eATE_INIT", re.I)
KEY_PROMPT_RE   = re.compile(rb"Please key '([yd])'", re.I)
DEBUG_OK_RE     = re.compile(rb"display Debug Info", re.I)

###########################################################################
# UART session helpers
###########################################################################
class UARTSession:
    def __init__(self, port: str, baud: int = 115200):
        self.port = port
        self.baud = baud
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.last_activity = time.monotonic()

    async def open(self):
        self.reader, self.writer = await serial_asyncio.open_serial_connection(
            url=self.port, baudrate=self.baud
        )
        logging.info("[UART] connected %s %d bps", self.port, self.baud)

    async def close(self):
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()

    async def write(self, data: bytes):
        self.writer.write(data)
        await self.writer.drain()
        self.last_activity = time.monotonic()

    async def read(self, n: int = 128) -> bytes:
        data = await self.reader.read(n)
        if data:
            self.last_activity = time.monotonic()
        return data

###########################################################################
# BootSync coroutine
###########################################################################
async def bootsync(sess: UARTSession, mode: str, boot_ready: asyncio.Event):
    """Waits for key prompt, sends y/d and waits for confirmation."""
    await sess.open()
    buf = b""
    key_sent = False
    deadline = time.monotonic() + BOOTSYNC_TIMEOUT
    confirm_re = ATE_BANNER_RE if mode == "ate" else DEBUG_OK_RE
    send_key = b"y\r" if mode == "ate" else b"d\r"

    while time.monotonic() < deadline:
        chunk = await sess.read()
        if chunk:
            buf += chunk
            logging.info("[RX] %s", chunk.hex())
            if not key_sent and KEY_PROMPT_RE.search(buf):
                await sess.write(send_key)
                key_sent = True
                logging.info("[BootSync] sent %s", send_key.rstrip())
                deadline = time.monotonic() + BOOTSYNC_TIMEOUT
            if key_sent and confirm_re.search(buf):
                logging.info("[BootSync] confirmed – entering %s", mode)
                boot_ready.set()
                return
        await asyncio.sleep(0.01)

    logging.error("[BootSync] timeout waiting for boot banner")
    boot_ready.set()  # let fuzzer proceed anyway

###########################################################################
# Printer coroutine (RX logger) – starts *after* BootSync
###########################################################################
async def printer(sess: UARTSession, boot_ready: asyncio.Event):
    await boot_ready.wait()
    while True:
        data = await sess.read()
        if data:
            logging.info("[RX] %s", data.hex())

###########################################################################
# Freeze monitor
###########################################################################
async def freeze_monitor(sess: UARTSession, boot_ready: asyncio.Event):
    await boot_ready.wait()
    while True:
        await asyncio.sleep(1.0)
        if time.monotonic() - sess.last_activity > FREEZE_TIMEOUT:
            logging.warning("[FREEZE] no UART activity for %.1fs", FREEZE_TIMEOUT)
            # simplistic recover – toggle DTR via pyserial
            sess.writer.transport.serial.dtr = False
            await asyncio.sleep(0.2)
            sess.writer.transport.serial.dtr = True
            sess.last_activity = time.monotonic()

###########################################################################
# Strategy skeletons
###########################################################################
class BaseStrategy:
    def __init__(self, sess: UARTSession, boot_ready: asyncio.Event):
        self.sess = sess
        self.boot_ready = boot_ready

    async def run(self):
        raise NotImplementedError

class MemDumpStrategy(BaseStrategy):
    async def run(self):
        await self.boot_ready.wait()
        await asyncio.sleep(0.1)  # give prompt a breath
        frame = b"\x1B" + b"R" + b"\x00\x00\x00\x00" + b"\x00\x01" + b"\r"
        await self.sess.write(frame)
        logging.info("[MEMDUMP] sent ESC R frame (0x0000, 0x100)")

class Overflow0DStrategy(BaseStrategy):
    async def run(self):
        await self.boot_ready.wait()
        pattern = gen_de_bruijn(4096)
        off = 0
        while off < len(pattern):
            chunk = pattern[off:off+0xFE]
            frame = b"\x02\x0D" + bytes([len(chunk)]) + chunk + b"\x03"
            await self.sess.write(frame)
            off += len(chunk)
            await asyncio.sleep(INTER_FRAME_DELAY)

###########################################################################
# Helper: De‑Bruijn pattern generator
###########################################################################
def gen_de_bruijn(length: int) -> bytes:
    charset = b"abcdefghijklmnopqrstuvwxyz"
    k = len(charset)
    a = [0] * k * 2
    seq = []
    def db(t, p):
        if t > k:
            if k % p == 0:
                seq.extend(a[1:p+1])
        else:
            a[t] = a[t-p]
            db(t+1, p)
            for j in range(a[t-p]+1, k):
                a[t] = j
                db(t+1, t)
    db(1,1)
    pattern = bytes([charset[i] for i in seq])
    while len(pattern) < length:
        pattern += pattern
    return pattern[:length]

###########################################################################
# Main
###########################################################################
async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("serial")
    parser.add_argument("--mode", choices=["ate", "loader"], required=True)
    parser.add_argument("--strategy", choices=["memdump", "overflow0d"], required=True)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(message)s]")

    sess = UARTSession(args.serial)
    boot_ready = asyncio.Event()

    strat_cls = MemDumpStrategy if args.strategy == "memdump" else Overflow0DStrategy
    strategy = strat_cls(sess, boot_ready)

    tasks = [bootsync(sess, args.mode, boot_ready),
             printer(sess, boot_ready),
             freeze_monitor(sess, boot_ready),
             strategy.run()]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())

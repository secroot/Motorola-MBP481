#!/usr/bin/env python3
"""
ATE Command Sender (rev-crc)
============================
Gezieltes Senden von Befehlen mit korrekter CRC-16-Modbus Prüfsumme
für den kritischen Opcode 0x0D.
"""

import asyncio, sys, time, logging

# ... Logging, UARTSession und boot_sync bleiben unverändert ...
############################ Logging ########################################
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-4s [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("root")
############################ UART ###########################################
class UARTSession:
    def __init__(self, port: str, baud: int = 115200):
        self.port = port
        self.baud = baud
        self.reader = self.writer = None

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

    async def read(self, n: int = 1024) -> bytes:
        try:
            return await asyncio.wait_for(self.reader.read(n), timeout=1.5)
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


################### CRC-16/MODBUS Implementation ###################
def crc16_modbus(data: bytes) -> int:
    """Berechnet die CRC-16-Modbus Prüfsumme."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc

############################ Frame Builder ##################################
CR = b"\x0D"

def build_frame(op: int, payload: bytes) -> bytes:
    """Baut einen Frame mit korrekter Endianness und CRC für Opcode 0x0D."""
    pre = b"\x55" if op == 0x0D else b"\x55\xAA"
    
    if op == 0x0D:
        # Für Opcode 0x0D berechnen wir das CRC
        len_bytes = len(payload).to_bytes(2, "big")
        
        # CRC wird über Opcode, Länge und Payload berechnet
        data_for_crc = bytes([op]) + len_bytes + payload
        crc_val = crc16_modbus(data_for_crc)
        crc_bytes = crc_val.to_bytes(2, "little") # CRC selbst ist meist little-endian
        
        # Frame zusammensetzen
        frame = pre + data_for_crc + crc_bytes + CR
    else:
        # Für andere Opcodes: kein CRC
        len_bytes = len(payload).to_bytes(2, "little")
        frame = pre + bytes([op]) + len_bytes + payload
        
    return frame

############################ Command Sender #################################
async def send_and_get_response(sess: UARTSession, frame: bytes):
    hex_frame = ' '.join(f'{b:02x}' for b in frame)
    log.info(f"[SEND] Sending frame: {hex_frame}")
    await sess.write(frame)
    await asyncio.sleep(1.1)
    response = await sess.read()
    if response:
        log.info(f"[RECV] Response: {response.strip()}")
    else:
        log.info("[RECV] No response (Silence is a valid success indicator!)")
    return response

async def main():
    if len(sys.argv) < 2:
        log.error(f"Usage: {sys.argv[0]} /dev/ttyUSB0")
        return
    
    port = sys.argv[1]
    sess = UARTSession(port)

    try:
        await sess.open()
        await boot_sync(sess)
        log.info("[i] Waiting 0.5s for device to settle...")
        await asyncio.sleep(0.5)

        log.info(">>> Testing Opcode 0x0D with 3-byte payload AND CRC-16-Modbus...")
        payload_to_test = b'\x00\x41\x01' # Gruppe 0, Parameter 'A', Wert 1
        frame = build_frame(0x0D, payload_to_test)
        await send_and_get_response(sess, frame)

    finally:
        await sess.close()


if __name__ == "__main__":
    asyncio.run(main())

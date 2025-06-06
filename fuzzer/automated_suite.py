#!/usr/bin/env python3
"""
ATE Automated Test Suite (rev-auto-fixed)
=========================================
Ein vollautomatischer, modularer Fuzzer, der alle definierten Test-Szenarien
für Opcode 0x0D nacheinander ausführt, bis ein Erfolg gefunden wird.
"""

import asyncio, sys, time, logging

############################ Logging ########################################
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-4s %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("ATE-Suite")

############################ UART & Co. #####################################
class UARTSession:
    def __init__(self, port: str, baud: int = 115200):
        self.port = port
        self.baud = baud
        self.reader = self.writer = None

    async def open(self):
        import serial_asyncio
        self.reader, self.writer = await serial_asyncio.open_serial_connection(url=self.port, baudrate=self.baud)
        log.info(f"[UART] connected {self.port}")

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

async def boot_sync(sess: UARTSession):
    PROMPT = b"Please key 'y'"
    READY = (b"Start ATE", b"Start ATE Test", b"eATE_INIT")
    
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
    
    buf = b""
    deadline = time.time() + 10
    
    # --- HIER WAR DER FEHLER ---
    # Die Einrückung ist jetzt korrekt.
    while time.time() < deadline:
        buf += await sess.read()
        if any(m in buf for m in READY):
            log.info("[i] ATE ready marker seen.")
            return
            
    log.warning("[!] No explicit ATE ready marker – continuing anyway …")

CR = b"\x0D"
def build_frame(op: int, payload: bytes) -> bytes:
    pre = b"\x55" if op == 0x0D else b"\x55\xAA"
    endianness = "big" if op == 0x0D else "little"
    ln = len(payload).to_bytes(2, endianness)
    frame = pre + bytes([op]) + ln + payload
    if op == 0x0D:
        frame += CR
    return frame

################### Automatisierte Test-Module ##############################

async def run_test(sess: UARTSession, payload: bytes) -> bool:
    """Führt einen einzelnen Test durch und gibt True bei Erfolg zurück."""
    frame = build_frame(0x0D, payload)
    await sess.write(frame)
    await asyncio.sleep(1.1)
    echo = await sess.read()
    
    if echo:
        response_text = echo.strip()
        hex_frame = ' '.join(f'{b:02x}' for b in frame)
        if b"Preamble Error" not in response_text and b"CMD Error" not in response_text:
            log.critical(f"[!!! SUCCESS !!!] on {hex_frame} -> Response: {response_text}")
            return True # Erfolg!
    return False

# --- Die Test-Module bleiben unverändert ---
async def test_payload_length(sess: UARTSession) -> bool:
    log.info("--- Starting Module 1: Payload Length Test ---")
    base_payload = b'\x00\x41' # Gruppe 0, Parameter 'A'
    for i in range(15): # Teste Längen 2, 3, 4, ... 16
        payload = base_payload + (b'\x00' * i)
        log.info(f"[TEST-LENGTH] Trying payload length {len(payload)}...")
        if await run_test(sess, payload): return True
    return False

async def test_parameter_values(sess: UARTSession) -> bool:
    log.info("--- Starting Module 2: Parameter Value Test ---")
    base_payload = b'\x00\x41' # Gruppe 0, Parameter 'A'
    for i in range(256):
        payload = base_payload + bytes([i]) # 3-Byte Payload
        if (i % 32 == 0): log.info(f"[TEST-VALUE] Testing value range 0x{i:02x}...")
        if await run_test(sess, payload): return True
    return False

async def test_parameter_names(sess: UARTSession) -> bool:
    log.info("--- Starting Module 3: Parameter Name Test ---")
    base_payload = b'\x00' # Gruppe 0
    value = b'\x01' # Fester Wert
    for i in range(0x20, 0x7F):
        payload = base_payload + bytes([i]) + value # 3-Byte Payload
        if (i % 16 == 0): log.info(f"[TEST-PARAM] Testing param range '{chr(i)}' (0x{i:02x})...")
        if await run_test(sess, payload): return True
    return False

async def test_group_ids(sess: UARTSession) -> bool:
    log.info("--- Starting Module 4: Group ID Test ---")
    param = b'\x41' # Parameter 'A'
    value = b'\x01' # Fester Wert
    for i in range(256):
        payload = bytes([i]) + param + value # 3-Byte Payload
        if (i % 32 == 0): log.info(f"[TEST-GROUP] Testing group ID range 0x{i:02x}...")
        if await run_test(sess, payload): return True
    return False

############################ Main Test Orchestrator #########################
async def main():
    if len(sys.argv) < 2:
        log.error(f"Usage: {sys.argv[0]} /dev/ttyUSB0")
        return

    port = sys.argv[1]
    sess = UARTSession(port)
    try:
        await sess.open()
        await boot_sync(sess)
        await asyncio.sleep(0.5)
        await sess.read() # Puffer leeren

        log.info("======== STARTING AUTOMATED TEST SUITE FOR OPCODE 0x0D ========")

        if await test_payload_length(sess):
            log.info("[!!! SUITE FINISHED !!!] Success found in Module 1: Length Test.")
            return

        log.info("--- Module 1 finished without success. ---")
        
        if await test_parameter_values(sess):
            log.info("[!!! SUITE FINISHED !!!] Success found in Module 2: Value Test.")
            return
            
        log.info("--- Module 2 finished without success. ---")

        if await test_parameter_names(sess):
            log.info("[!!! SUITE FINISHED !!!] Success found in Module 3: Parameter Test.")
            return

        log.info("--- Module 3 finished without success. ---")

        if await test_group_ids(sess):
            log.info("[!!! SUITE FINISHED !!!] Success found in Module 4: Group ID Test.")
            return
            
        log.info("--- Module 4 finished without success. ---")

        log.critical("======== All automated tests completed without finding a valid command. ========")

    finally:
        await sess.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("\n[i] Program aborted by user.")
    except Exception as e:
        log.error(f"[!!!] An unexpected error occurred: {e}", exc_info=True)

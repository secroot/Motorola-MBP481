import serial
import sys
import time

# ---- Konfiguration ----
PROMPTS = {
    "telemetry":    b'\x1bT',
    "cmos_day":     b'\x1bD',
    "cmos_night":   b'\x1bN',
    "ate_mode":     b'\x1bA',
    "boot_loader":  b'\x1bR'
}
LOGFILE = "entry_validate.log"

# ---- Logging-Helpers ----
def log(msg, fh=None, end='\n'):
    # msg als str
    if fh:
        fh.write(msg + end)
        fh.flush()
    print(msg, end=end)

def log_bin(data, fh=None):
    # data als bytes -> hexlog
    hexstr = ' '.join(f"{b:02X}" for b in data)
    log(hexstr, fh)

# ---- Serielle Helfer ----
def send_and_read(ser, sequence, timeout=1.0, readlen=256):
    ser.write(sequence)
    ser.flush()
    time.sleep(0.2)
    start = time.time()
    rx = b''
    while time.time() - start < timeout:
        n = ser.in_waiting
        if n:
            rx += ser.read(n)
            if len(rx) >= readlen:
                break
        else:
            time.sleep(0.05)
    return rx

def sync_on_boot(ser, logfile):
    log("[*] Warte auf Boot-Prompt …", logfile)
    # Simpler Wait-for-Data
    for _ in range(50):
        time.sleep(0.2)
        if ser.in_waiting:
            _ = ser.read(ser.in_waiting)
            log("[*] UART prompt erkannt!", logfile)
            return True
    log("[!] Kein UART prompt nach Boot.", logfile)
    return False

# ---- Hauptlogik ----
def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} /dev/ttyUSBx")
        sys.exit(1)
    port = sys.argv[1]
    with serial.Serial(port, baudrate=115200, timeout=0.5) as ser, open(LOGFILE, "w", encoding="utf-8") as lf:
        lf.write("=== UART VALIDATOR LOG ===\n")
        lf.flush()
        sync_on_boot(ser, lf)
        results = {}
        for name, seq in PROMPTS.items():
            log(f"[TEST] {name:12s}: ", lf, end='')
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            rx = send_and_read(ser, seq)
            if rx:
                log("OK", lf)
                log(f"  Rx: {rx!r}", lf)
                results[name] = "OK"
            else:
                log("FAIL", lf)
                results[name] = "FAIL"
        # Summary
        log("\n=== VALIDATION SUMMARY ===", lf)
        for k, v in results.items():
            log(f"{k:12s}: {v}", lf)
        log(f"\nLogfile → {LOGFILE} – viel Erfolg!")

if __name__ == "__main__":
    main()

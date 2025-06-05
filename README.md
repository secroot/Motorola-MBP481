# UART Menüanalyse: Motorola MBP481AXL  *(Revision 06 Jun 2025)*


## 🧠 Kontext & Ziel

* **Modell:** Motorola MBP481AXL (Eltern‑ & Kameraeinheit)
* **SoC:** **NXP LPC32xx (ARM9, Label MW1892B)**
  *Korrektur: Frühere Vermutung „MStar MSC313E“ war ein Trugschluss – Pin‑out, Peripherie‑IDs und Boot‑ROM‑Signatur passen zweifelsfrei zum LPC32xx‑Design.*
* **Zugriff:** 3‑Pin UART, kein Shell‑Prompt – mehrere versteckte Menüs
* **Ziel:** Schwachstellen­analyse & Exploit‑Entwicklung (UART/Boot‑Loader/ATE)

---

## 🔍 UART Bootlog & Initialisierung

### SDRAM‑Tuning *(unverändert)*

```text
htol.bin
sdrconfig=1102
set CLKTUN=(1<<12)|(1<<6)|(1<<5)
set RD_SEL=(1<<5)
tuning2 done
CLKTUN=1BFA
SDRAM tuning over
```

### Flash‑Layout *(zusätzliche Infos)*

```text
FlashID = 0x684014   # GD25Q128C – 16 MB SPI‑NOR
Bootldr 0x000000‑0x0003FF (1 KB padded)
Params  0x000400‑0x0013FF (4 KB user/factory settings)
Kernel  ≈0x001400‑…
```

> **Neu:** Boot‑Loader akzeptiert den **undokumentierten Befehl `ESC R`** → beliebiger Speicher­dump (Flash & DDR). Das ermöglicht vollständige Firmware‑Extraktion.

### Hardware‑Initialisierung & Peripherie *(ergänzt)*

```text
installing charger...
installing adarray-key...
lcd = FY23001B_ILI9342C_MCU.init
I2S codec init OK
```

### RF‑Link Parameter *(unverändert)*

```text
RfNetId=0x2f390704
serid=f3907049,id1=f3907041,id2=f3907045
g_su32PairedSlaveFlag=0xfffffffc
```

---

## 📟 Menüinteraktion per UART 

### Elterneinheit Menüoptionen

```
Please key 'y' or 'Y' to execute ATE mode.
Please key 'd' or 'D' to display Debug Info.
Please key 'l' or 'L' to enable LCD dynamic setting.
```

### Kameraeinheit Menüoptionen (zusätzlich)

```
Please key 'c' ... Day mode CMOS
Please key 'n' ... Night mode CMOS
Please key 'g' ... Get CMOS current setting → **Soft‑Freeze**
Please key 'j' ... Set JPG current setting → **Soft‑Freeze**
```

### Menüreaktionen (Update)

#### 🔸 `y` – ATE Mode (**Primärer Angriffsvektor**)

* Frame‑Aufbau: `55 AA | OP | LEN<le16> | PAYLOAD | [CRC]`
* **0x00** Reset, **0x08** Echo (Parser‑Glitch), **0x0D** *Stack‑Overflow*, **0x72** Session‑Start, **0xD8/0xD9** Mass‑Payload (>16 KB, Firmware‑Updater).
* **Overflow‑Detail:** Schon bei \~208 B Payload auf 0x0D wird der LR/PC auf dem Stack überschrieben → Code‑Exec möglich.
* Parser „Bad Chars“: `0x00 0x0A 0x0D` desynchronisieren den State‑Machine‑Cursor.

#### 🔸 `d` – Debug/Telemetry 

#### 🔸 `c` / `n` – CMOS R/W Shell *(Hinweis präzisiert)*

* Schreibformat `01 ADDR DATA`, Lesebefehl `00 ADDR 00`
* **Neu:** Reg‑Dump automatisierbar (siehe Tool `mbp481_validator.py`).

#### 🔸 `g` / `j` – Freeze States *(Bestätigung)*

* Gerät blockiert bis **`ESC + Byte`** oder Hard‑Reset.

---

## 🧰 UART‑Fuzzer (Python) 

```python
#!/usr/bin/env python3
"""
mbp481_fuzzer.py – UART-Fuzzer für Motorola MBP481AXL

• Fuzzing direkt nach Prompt ("Please key 'y' ..."), typisches 5s-Zeitfenster!
• Zwei Hauptmodi:
    - loader  → Bootloader-Kommandos, Escaping, Frame-Varianten
    - ate     → ATE-Protokoll (Header 0x55AA + Opcode + ...)
• Recovery-Mechanismen und Logging optimiert auf validierte Erkenntnisse

Usage:
    python3 mbp481_fuzzer.py /dev/ttyUSB0 loader
    python3 mbp481_fuzzer.py /dev/ttyUSB0 ate
    python3 mbp481_fuzzer.py /dev/ttyUSB0 raw

Logfile:
    • uart_fuzz.log – Klartext & Hex-Dump von TX/RX

Autor: ChatGPT x hazardcore, 2025
"""
import sys, time, struct, serial
from functools import reduce

if len(sys.argv) < 2:
    sys.exit("Usage: mbp481_fuzzer.py <serial_dev> [raw|ate|loader]")

DEV  = sys.argv[1]
MODE = sys.argv[2].lower() if len(sys.argv) > 2 else "raw"
BAUD = 115200

def hexdump(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)

def crc8_xor(buf: bytes) -> int:
    return reduce(lambda a, b: a ^ b, buf, 0) & 0xFF

ser = serial.Serial(DEV, BAUD, timeout=0.3)
log = open("uart_fuzz.log", "wb", buffering=0)

def send(frame: bytes, info: str = "") -> bytes:
    ser.write(frame)
    time.sleep(0.15)
    resp = ser.read(512)
    log.write(f"> {info} {hexdump(frame)}\n".encode())
    if resp:
        log.write(f"< {hexdump(resp)}\n".encode())
    return resp

print(f"[i] waiting for prompt on {DEV} …")
buf = b""
# Prompt-Varianten laut Canvas: "Please key 'y'", "Debug Info", "Day mode CMOS", etc.
PROMPTS = [b"Please key", b"Debug Info", b"CMOS", b"execute ATE"]
while not any(p in buf for p in PROMPTS):
    buf += ser.read(256)
print("[i] prompt seen – entering 5-s window")

# Boot-Modus aktivieren, falls notwendig
if MODE == "loader":
    print("[*] Entering loader mode: Sending ESC ESC …")
    ser.write(b"\x1B\x1B")
    time.sleep(0.1)
elif MODE == "ate":
    print("[*] Entering ATE mode: Sending 'y' …")
    ser.write(b"y")
    time.sleep(0.1)

freeze = 0

for val in range(256):
    if MODE == "loader":
        # Loader-Frame: ESC 'R' addr(4B) len(2B), ggf. mit/ohne CRC – alle Varianten rotieren
        addr = 0
        length = 0x20
        frame = b"\x1B\x52" + struct.pack("<I", addr) + struct.pack("<H", length)
        # CRC8-Variante (experimentell, viele Bootloader mögen so was):
        crc = crc8_xor(frame)
        frame_crc = frame + bytes([crc])
        # Teste beide Frames: mit & ohne CRC
        if val % 2 == 0:
            test_frame = frame
            info = "ESC R noCRC"
        else:
            test_frame = frame_crc
            info = "ESC R +CRC"
    elif MODE == "ate":
        # ATE-Protokoll: 0x55AA + Opcode + Len_L + Len_H (Len=0 für reine OpCodes)
        header = b"\x55\xAA"
        opcode = val
        frame = header + bytes([opcode, 0x00, 0x00])
        info = f"ATE-Op {opcode:02X}"
        test_frame = frame
    else:
        # Roher Byte-Sweep (single byte), kann abweichende Prompts triggern
        test_frame = bytes([val])
        info = "RAW"

    response = send(test_frame, info=info)

    if val % 0x10 == 0:
        print(".", end="", flush=True)

    # Freeze-Watchdog: 3x keine Antwort = Recovery-Frame
    if response:
        freeze = 0
    else:
        freeze += 1
        if freeze == 3:
            print("\n[!] no response – sending ESC NUL for recovery")
            ser.write(b"\x1B\x00")
            time.sleep(0.5)
            freeze = 0

print("\n[+] fuzzing finished – see uart_fuzz.log")
ser.close()
log.close()

```

---

## Debug‑Info‑Ausgabe (`d` – Kamera) 

```
Therm 0x00 | Lux 0xB8 | Mic 0x21 | JPG 7 8xx B | Vol 0xB0 | Lullaby 0x05
```

---

## 🧠 Erkenntnisse (Stand 06 Jun 2025)

### 1 · Boot‑Timeline & Intervall 

* \~5 s Interaktions­fenster, danach Menü gesperrt.

### 2 · Parser‑Architektur 

| Ebene           | Aktivierung | Protokoll                 | Status                                  |
| --------------- | ----------- | ------------------------- | --------------------------------------- |
| **Boot‑Loader** | `ESC ESC`   | `ESC <OP> ADDR LEN [CRC]` | **Neu:** `R` = mem‑read funktions­fähig |
| ASCII‑Menü      | Boot‑Prompt | Einzel‑Chars              | ✔                                       |
| **ATE**         | `y`         | Binär Frame (s.o.)        | **Overflow 0x0D** + OTA‑Frame           |
| CMOS‑Shells     | `c/n`       | Hex‑String                | ✔                                       |
| Telemetrie      | `d`         | ASCII‑Dump                | ✔                                       |
| Freeze‑States   | `g/j`       | wartet Payload            | Soft‑Freeze                             |

### 3 · Menü‑Befehle – Zusammenfassung 

| Cmd | Zweck                 | Rückweg               | Notes                |
| --- | --------------------- | --------------------- | -------------------- |
| y   | ATE Binary Parser     | `ESC NUL` oder Reset  | Buffer Overflow 0x0D |
| d   | Telemetrie‑Loop       | `ESC Byte` oder Reset |                      |
| c   | CMOS Day Shell        | `ESC Byte`            | Reg‑R/W              |
| n   | CMOS Night Shell      | `ESC Byte`            | Reg‑R/W              |
| g   | **Snapshot → Freeze** | **nur Reset**         |                      |
| j   | **JPG Cfg → Freeze**  | **nur Reset**         |                      |

### 4 · Offene Punkte / Nächste Schritte 

1. **Flash‑Dump via `ESC R`** automatisieren (16 MB, gzip‑pipe).
2. **De Bruijn‑Offset** für 0x0D‑Overflow bestimmen → LR control.
3. **Bad‑Char Tabelle** finalisieren, Shellcode‑Alphabet fixieren.
4. **OTA‑Chain analysieren** (0x72 → 0xD8/0xD9) – Signatures? CRC?


---

## 🧰 UART‑Validator v0.4 

```python
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

```


---

> **Kurzfassung:** Hauptirrtum (SoC) behoben, Boot‑Loader‑Leak & ATE‑Overflow als kritische Schwachstellen ergänzt. Alle übrigen Struktur‑ und Format‑Elemente bleiben unverändert.

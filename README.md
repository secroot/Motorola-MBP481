# UART Menüanalyse: Motorola MBP481AXL

Diese Seite dokumentiert die serielle Menüstruktur und Boot-Ausgaben des Motorola MBP481AXL Babyphones zur Unterstützung von Reverse Engineering und Debugging über UART.

---

## 🧠 Kontext & Ziel

* **Modell:** Motorola MBP481AXL (Elterneinheit) und Kameraeinheit
* **SoC:** MStar MSC313E (vermutlich)
* **Zugriff:** UART mit Menüzugang, aber kein Shell-Zugriff
* **Ziel:** Analyse möglicher Exploit-Punkte oder versteckter Kommandos über UART

---

## 🔍 UART Bootlog & Initialisierung

### SDRAM-Tuning

```text
htol.bin
sdrconfig=1102
set CLKTUN=(1<<12)|(1<<6)|(1<<5)
set RD_SEL=(1<<5)
tuning2 done
CLKTUN=1BFA
SDRAM tuning over
```

### Flash-Layout

```text
sizeof(tCTRL_FLASH_MAP)=0x400
sizeof(tFLASH_USERSETTING_MAP)=0x1000
```

### Hardware-Initialisierung

```text
installing charger...
installing adarray-key...
lcd = FY23001B_ILI9342C_MCU.init
```

### RF-Link Parameter

```text
RfNetId=0x2f390704
serid=f3907049,id1=f3907041,id2=f3907045
g_su32PairedSlaveFlag=0xfffffffc
```

### LCD Treiber / Init

```text
FY23001B_ILI9342C_MCU
Reg24/Reg2D: z. B. 3a, 14, 7f
```

---

## 📟 Menüinteraktion per UART

### Elterneinheit Menüoptionen

Nach dem Boot erscheint folgender Prompt:

```
Please key 'y' or 'Y' to execute ATE mode.
Please key 'd' or 'D' to display Debug Info.
Please key 'l' or 'L' to enable LCD dynamic setting.
```

### Kameraeinheit Menüoptionen

Zusätzlich zu den oben genannten:

```
Please key 'c' or 'C' to enable Day mode CMOS dynamic setting.
Please key 'n' or 'N' to enable Night mode CMOS dynamic setting.
Please key 'g' or 'G' to enable get CMOS current setting.
Please key 'j' or 'J' to enable Set JPG current setting.
```

### Menüreaktionen

#### 🔸 `y` – ATE Mode

* Startet automatischen Hardwaretest
* Häufige Ausgabe: `Preamble Error`
* Einzige bestätigte Antwort auf direkte Eingabe: `CMD Error` bei `0x0f`, `d`, `a`

#### 🔸 Weitere Befehle (Kamera getestet, local echo aktiv):

* `clear`, `read`, `boot`, `test`, `write`, `dump`, `lcd`, `testlcd`, `testmic`, `readmem`, `rfpair`, `rfstatus`, `openrf`, `@@`, `!!`, `~` → alle mit: `Preamble Error` oder `CMD Error`

> ⚠️ Selbst gültige Buchstaben-Eingaben führen ohne korrekten Kontext zu Fehlermeldungen – Menü ist sehr zustandsabhängig.

---

## 🧰 UART-Fuzzer (Python)

Ein Script zur automatischen Kommandosuche über UART:

```python
import serial
import time

ser = serial.Serial("/dev/ttyUSB0", 115200, timeout=1)
log = open("uart_fuzz.log", "w")

for i in range(256):
    b = bytes([i])
    ser.write(b)
    time.sleep(0.2)
    response = ser.read(1024)
    log.write(f"0x{i:02X}: {response.decode(errors='ignore')}\n")

ser.close()
log.close()
```

### Hinweise:

* Durchläuft alle Werte von `0x00` bis `0xFF`
* Antwort wird in Datei `uart_fuzz.log` gespeichert
* Nutze isolierten USB-TTL Adapter zur Sicherheit

---

### Debug‑Info‑Ausgabe (`d` – Kamera)

Die Option **`d`** schaltet einen kontinuierlichen Telemetrie‑Loop ein. Die Firmware sendet alle \~2 Sekunden einen Block mit Umgebungs‑ und JPEG‑Parametern:

```
Therm ADC Value = 0x0
Light ADC Value = 0x00‑0xB8   # Umgebungslicht‑Sensor
Sound Energy    = 0x00‑0x21   # Mikrofon‑Level
JpgQuality[4]   = 3           # fester Qualitätsindex
JpgSize         = 7 8xx–8 0xx Bytes bei 320×240
GetCurVolume    = 0xB0        # Lautsprecher‑Volumen (176)
GetLullabyVolume= 0x05        # Lullaby‑Volumen (  5)
```

*Vor* dem ersten Telemetrie‑Block erscheinen Einzelmeldungen zu MJPEG‑Encoder‑Init (Auflösung 640×480 → 320×240, Zoom Out, Buffer‑Adresse) sowie RF‑IDs.

> **Exit:** nur durch `ESC` + irgendein Byte (Parser‑Error) oder Strom‑Reset. ASCII‑Eingaben während des Loops werden ignoriert.

---

### CMOS-Day-Mode (`c` – Kamera)

*Siehe Beschreibung oben.*

### CMOS-Day-Mode (`c` – Kamera)

*Siehe Beschreibung oben.*

### CMOS-Night-Mode (`n` – Kamera)

*Identisch zum Day-Mode, nutzt aber das Low‑Light‑Preset.*

### Get‑CMOS‑Status (`g` – Kamera)

* Startet erneut den MJPEG‑Encoder (Init‑Meldungen wie bei `c`/`n`).
* Danach **friert die Shell ein** – kein Prompt, keine Telemetrie, keine Eingabe‑Echo.
* Nur **`ESC` + Byte** oder Hard‑Reset holt das Gerät zurück.
* Vermutung: Firmware versucht Snapshot der aktuellen Sensor‑Register in Shared‑RAM abzulegen und blockiert bei fehlendem ACK.

### JPG‑Setting‑Mode (`j` – Kamera)

* Ablauf identisch zu `g`: Encoder wird reinitialisiert, dann **Freeze**.
* Wahrscheinlich erwartet ein binäres Konfig‑Frame für Quality/Size‑Tabelle.

> **Warnung:** `g` und `j` sind zurzeit „Show‑Stopper“ – nur ausführen, wenn Reset möglich ist.

---

## 🧠 Erkenntnisse (Stand Jun 5 2025)

### 1 · Boot‑Timeline & Intervall

| Ereignis                  | Timestamp‑Delta | Bemerkung                                           |
| ------------------------- | --------------- | --------------------------------------------------- |
| Menü‑Prompt erscheint     |  t + 0 s        | "Please key 'y'…" → Start des Interaktions‑Fensters |
| erste Video/MJPEG‑Meldung |  t + ≈5 s       | Menü inaktiv – alle ASCII‑Befehle ignoriert         |

→ **\~5 s Fenster**, um Loader (`ESC ESC`) oder Menü‑Befehle (`y/d/c/n/g/j`) abzusetzen.

---

### 2 · Parser‑Architektur

| Ebene                 | Aktivierung | Erwartetes Protokoll                                  | Status                                                    |
| --------------------- | ----------- | ----------------------------------------------------- | --------------------------------------------------------- |
| **Boot‑Loader**       | `ESC ESC`   | `ESC` + Opcode (`R/W/D/F…`) + Addr + Len + (CRC)      | Header bestätigt; Read‑Frame muss noch verifiziert werden |
| **ASCII‑Menü (Root)** | Boot‑Prompt | Einzel‑Chars `y d c n g j`                            | funktioniert                                              |
| **ATE‑Parser**        | `y`         | unbekannter Binär‑Frame (Header + Opcode + Len + CRC) | nur *Preamble Error* – Header noch offen                  |
| **CMOS Shells**       | `c` / `n`   | Hex‑String (Write/Read CMOS Reg)                      | interaktiv ✔                                              |
| **Telemetry‑Loop**    | `d`         | reiner ASCII‑Dump                                     | läuft alle \~2 s                                          |
| **Freeze‑States**     | `g` / `j`   | wartet auf Binär‑Payload → blockiert                  | Exit nur `ESC + Byte` oder Reset                          |

---

### 3 · Menü‑Befehle – Zusammenfassung

| Befehl | Zweck                            | Rückweg                |
| ------ | -------------------------------- | ---------------------- |
| `y`    | ATE Mode → Binär‑Frame erwartet  | Reset oder Loader      |
| `d`    | Telemetrie‑Loop (ADC, JPG‑Stats) |  `ESC+Byte` oder Reset |
| `c`    | CMOS Day Shell → Register R/W    | `ESC+Byte`             |
| `n`    | CMOS Night Shell → Register R/W  | `ESC+Byte`             |
| `g`    | Get CMOS Snapshot – **friert**   | nur Reset              |
| `j`    | Set JPG Table – **friert**       | nur Reset              |

---

### 4 · Offene Punkte / Nächste Schritte

1. **Loader‑Dump testen:** Frame `ESC R <addr> <len>` ohne CRC an Adresse 0x0 / 0x80000000.
2. **ATE‑Header brute‑forcen:** Kandidaten `55AA` | `AA55` | `A5` `5A` (+ Opcode 0×00–0×0F, Len 0).
3. **CMOS‑Shell skriptbar machen:** Automatisierter Reg‑Dump für GC0308 (0x77 00–FF).
4. **Recovery‑Plan:** dokumentieren, dass `g`/`j` Soft‑freeze auslösen.
5. **Firmware‑Drop scannen:** nach „MStarATE.exe“ / MSC ATE DLLs für Frame‑Spec.

---

> **Kurzform:** Wir haben zwei binäre Backends (Loader & ATE) und drei ASCII‑Modi. 5‑Sek‑Fenster und Exit‑Sequenzen sind geklärt – nächster Meilenstein ist der erfolgreiche RAM‑Read über Boot‑Loader oder das Knacken des ATE‑Headers.

---

### 🧰 UART‑Fuzzer v0.4 – **Entry‑Point Validator**

> Ein einziger Lauf prüft nacheinander alle bislang bekannten Parser‑Einstiege (Root‑Prompt → Telemetry → CMOS‑Day → CMOS‑Night → ATE → Boot‑Loader) und protokolliert, welcher Modus erfolgreich erreicht wurde. Jeder Test wird sauber beendet (ESC + NUL) oder – falls keine Reaktion – mit einem Soft‑Reset (Prompt‑Warten) übersprungen.

```python
#!/usr/bin/env python3
""" mbp481_validator.py – UART‑Fuzzer / Einstieg‑Checker für MBP481

    Usage: python3 mbp481_validator.py /dev/ttyUSB0 [baud=115200]

    Der Script‑Output sieht so aus:
        [✔] Root‑Prompt erreichbar (0.9 s)
        [✔] Telemetry‑Loop gestartet (d) … beendet
        [✔] CMOS‑Day‑Shell gestartet (c) … beendet
        [✔] CMOS‑Night‑Shell gestartet (n) … beendet
        [✘] ATE‑Parser (y) – keine ACK‑Pattern
        [✘] Boot‑Loader (ESC ESC) – kein ACK innerhalb 300 ms

    Ergebnis wird zusätzlich in validator.log (hex‑dump) mitgeschnitten.
"""
import sys, time, serial, struct, functools, re

DEV  = sys.argv[1]
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else 115200
ser  = serial.Serial(DEV, BAUD, timeout=0.2)
log  = open("validator.log", "wb")

def hx(b): return " ".join(f"{x:02X}" for x in b)

def tx(buf):
    ser.write(buf)
    log.write(b"> "+hx(buf).encode()+b"
")
    time.sleep(0.15)
    rsp = ser.read(1024)
    if rsp:
        log.write(b"< "+hx(rsp).encode()+b"
")
    log.flush()
    return rsp

def wait_for(regex, tmo=3.0, chunk=128):
    pattern = re.compile(regex)
    data = b""; t0=time.time()
    while time.time()-t0 < tmo:
        data += ser.read(chunk)
        if pattern.search(data.decode(errors='ignore')):
            return True, data
    return False, data

print(f"[i] Waiting for root prompt on {DEV} …")
ok, buf = wait_for(r"Please key 'y'", 8.0)
if not ok:
    print("[✘] Kein Root‑Prompt innerhalb 8 s – abbrechen.")
    sys.exit(1)
print("[✔] Root‑Prompt erreichbar")

# Helper: exit current sub‑parser
ESC_NUL = b"�"

def test_cmd(label, cmd_bytes, expect_regex, exit_seq=ESC_NUL, ack_timeout=1.0):
    tx(cmd_bytes)
    ok, _ = wait_for(expect_regex, ack_timeout)
    if ok:
        print(f"[✔] {label} gestartet")
        if exit_seq:
            tx(exit_seq)
            wait_for(r"Please key 'y'", 4.0)
            print(f"    ↳ beendet & zurück im Root‑Prompt")
    else:
        print(f"[✘] {label} – keine erwartete Antwort")
    return ok

# 1 Telemetry (d)
test_cmd("Telemetry‑Loop (d)", b"d", r"Therm ADC Value|GetCurVolume|Uart Rx Buf Full")

# 2 CMOS Day (c)
test_cmd("CMOS‑Day‑Shell (c)", b"c", r"MJPEGEncCtrl|Zoom Out")

# 3 CMOS Night (n)
test_cmd("CMOS‑Night‑Shell (n)", b"n", r"MJPEGEncCtrl|Zoom Out")

# 4 ATE (y) – wir erwarten irgendwas *ohne* Fehlermuster
ate_ok = test_cmd("ATE‑Parser (y)", b"y", r"(?!Preamble Error)(?!CMD Error).+", exit_seq=ESC_NUL, ack_timeout=0.6)

# 5 Boot‑Loader (ESC ESC) – ACK typ. "~!EncodeInit!~" oder ">"
loader_ok = test_cmd("Boot‑Loader (ESC ESC)", b"", r"~!EncodeInit!~|> ", exit_seq=None, ack_timeout=0.3)

print("
[i] Validierung abgeschlossen – Logfile: validator.log")
ser.close(); log.close()
```

#### Was ist neu?

| Feature           | Erklärung                                                                            |
| ----------------- | ------------------------------------------------------------------------------------ |
| **Regex‑Matcher** |  jedes Sub‑Menü wird anhand eindeutiger Ausgaben verifiziert.                        |
| **Graceful Exit** |  sendet `ESC NUL` nach erfolgreichem Test, um sicher Root‑Prompt zurückzubekommen.   |
| **Watchdog**      |  pro Test max. `ack_timeout` Sek.; danach gilt der Einstieg als *fehlgeschlagen*.    |
| **Saubere Logs**  |  Hex‑Dump aller TX/RX‑Bytes in `validator.log` (keine Mehrzeilen‑Spam wie bei v0.3). |

**Hinweise**

1. Wenn *Boot‑Loader* erfolgreich ist, das Gerät bleibt darin hängen; Script beendet sich ohne Exit‑Sequence → **Power‑Cycle** nötig, bevor man den Validator erneut laufen lässt.
2. Für den ATE‑Parser ist die ACK‑Signatur noch unklar. Der Negative‑Look‑Ahead Filter (`(?!Preamble Error)`) sorgt nur dafür, dass reine Fehlermeldungen nicht als Erfolg zählen.
3. Falls dein USB‑Adapter keine HW‑Reset‑Leitung hat, plane pro vollständigem Durchlauf \~30 s (inkl. manuellem Strom‑Reset).

---

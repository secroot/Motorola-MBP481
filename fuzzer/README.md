Mapping und Differenzanalyse ergaben vollständige Klarheit über die undokumentierte Schnittstelle zur direkten Steuerung des GC0308 CMOS-Bildsensors im Motorola MBP481AXL Babyphone.

### Zusammenfassung der Ergebnisse:

Die UART-Schnittstelle bietet direkten Zugriff auf die Register des GalaxyCore GC0308-Sensors. Sie erlaubt das gezielte Lesen und Schreiben der CMOS-Register zur unmittelbaren Hardware-Steuerung der Kamera. Ein Zugriff auf das Betriebssystem oder eine allgemeine Shell-Funktionalität existiert nicht über diese spezifische Schnittstelle.

### Kategorisierung der CMOS-Register:

#### 1. Globale System-Register (Hauptsteuerung)

| Register | Day-Wert | Funktion (Hypothese) & Bedeutung                                                        |
| -------- | -------- | --------------------------------------------------------------------------------------- |
| 0x00     | 0x9b     | Chip-ID: Identifiziert den GC0308 Sensor                                                |
| 0xfd     | 0x00     | Standby-Schalter (0x01 = Standby; 0x00 = aktiv)                                         |
| 0xfe     | 0x00     | Page-Select (0x00 Standardseite, andere Werte öffnen potentiell weitere Registerseiten) |

#### 2. Dynamische Register (Bildsteuerung Tag/Nacht)

| Register    | Day-Wert    | Night-Wert  | Funktion (Hypothese)                       |
| ----------- | ----------- | ----------- | ------------------------------------------ |
| 0x73        | 0x80        | 0x00        | IR-Cut-Filter-Schalter                     |
| 0x02 / 0x03 | 0x70 / 0x02 | 0xbc / 0x06 | Analog Gain (Verstärkung)                  |
| 0x04        | 0x58        | 0xe4        | AEC/AGC Control (Belichtung & Verstärkung) |
| 0x10        | 0x26        | 0x26        | Exposure (Belichtung, stabil)              |
| Diverse     | ...         | ...         | Weißabgleich, Sättigung, Kontrast          |

#### 3. Statische Register (Werkseinstellungen)

* Gamma-Kurven (0xa0–0xab)
* Lens Shading Correction (0xc0–0xd0)
* Sensor-Timings und Initialisierungswerte
* Test-Pattern-Konfiguration

Diese Register beeinflussen direkt die Bildqualität. Modifikationen führen nicht zu versteckten Betriebssystem- oder Shell-Funktionen, sondern beeinflussen nur grundlegende Bild-Parameter.

### Fazit:

Die Schnittstelle ermöglicht umfassende Hardwaresteuerung der Kamera, bietet jedoch keinen Zugang zu tieferliegenden Systemebenen oder einer Shell.

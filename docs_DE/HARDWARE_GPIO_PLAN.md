# Hardware- und GPIO-Plan

Stand: `2026-08-18`

English version: [Hardware and GPIO Plan](../docs/HARDWARE_GPIO_PLAN.md)

## Ziel

Dieses Dokument beschreibt den aktuellen Hardwareaufbau des ABR-Zielgeräts
und die GPIO-Belegung am `Raspberry Pi 5`.

Der Bedienpfad verwendet wenige, taktil klar unterscheidbare Elemente:

- `1 x EC11`-Drehencoder für die Lautstärke
- `1 x` Drucktaster im Encoder
- `3 x` separate Haupttaster

## Bedienkonzept

1. `Lautstärke`
   - Encoder links/rechts für leiser/lauter
   - Encoder-Drucktaster als zusätzliche Taste
2. `Start / Stop / NFC`
   - startet NFC-Abfrage, Scan und Audioausgabe
   - stoppt einen laufenden Job oder die Audioausgabe
3. `Buch-Zusammenfassung`
   - erzeugt und liest die bisherige Buchzusammenfassung
4. `Kapitel-/Letzte-Seiten-Zusammenfassung`
   - fasst den letzten relevanten Abschnitt einschließlich offener Seiten
     zusammen

Alle Taster werden `active-low` gegen `GND` betrieben und verwenden interne
Pull-ups des Pi. Der Starttaster soll mechanisch am größten und leicht
auffindbar sein; die beiden Zusammenfassungstaster sollen sich taktil
unterscheiden.

## Aktuelle Hardware

- Hauptrechner: `Raspberry Pi 5`
- NFC-Gateway: `Raspberry Pi Pico`/`RP2040`, per UART mit dem Pi verbunden
- NFC-Reader: `PN5180` oder `PN532`, ausschließlich am Pico angeschlossen
- Audio: `MAX98357A` über `I2S`
- Bedienung: `EC11` mit Drucktaster und drei Funktionstaster
- Kameras: `2 x Arducam IMX519 16 MP` mit 140-Grad-M12-Weitwinkelobjektiv
- Kameraanschluss: die beiden CSI-Ports des Pi 5
- Licht: zwei getrennte LED-Kanäle, jeweils über einen MOSFET geschaltet

Aktuelle Hardware-Arbeitsstände im Repository:

- Pi-Hauptverdrahtung: [hardware/electronics/abr_pi5_header](../hardware/electronics/abr_pi5_header)
- Bedienpanel: [hardware/electronics/control_panel](../hardware/electronics/control_panel)
- LED-Leiste: [hardware/electronics/LED_bar_long](../hardware/electronics/LED_bar_long)
- Mechanik: [hardware/mechanics](../hardware/mechanics)

`LED_bar_short` ist nur noch historisch und nicht der aktive Elektronikpfad.

Logische Kamerazuordnung:

- linke Kamera an `CAM0`
- rechte Kamera an `CAM1`

Die Kameras verwenden die CSI-Ports und belegen keine GPIOs. Die aktuellen
Remaps liegen unter `calibration/out/cam0_planar.npz` und
`calibration/out/cam1_planar.npz`.

## NFC-Architektur

Es gibt **keine direkte Kommunikation** zwischen dem Raspberry Pi 5 und einem
`PN5180`- oder `PN532`-Reader. Der Pi kommuniziert ausschließlich mit dem
Raspberry Pi Pico. Der Pico übernimmt Reader-Initialisierung,
Protokollzugriff, Tag-Erkennung und Statushaltung.

Die Verbindung zwischen Pi und Pico ist ein UART mit `115200 8N1` und
3,3-V-Logikpegeln:

| Raspberry Pi 5 | Physisch | Richtung | Raspberry Pi Pico | Funktion |
| --- | --- | --- | --- | --- |
| `BCM14 / TXD` | `8` | Pi → Pico | `GP1 / RX` | Kommandos an das Gateway |
| `BCM15 / RXD` | `10` | Pico → Pi | `GP0 / TX` | Antworten des Gateways |
| `GND` | beliebiger GND-Pin | gemeinsam | `GND` | gemeinsames Bezugspotential |

Auf dem Pi verwendet die Software standardmäßig `/dev/ttyAMA0`. Das Gateway
spricht ein zeilenbasiertes ASCII-Protokoll; der gemeinsame Client liegt in
[abr/hardware/pico_gateway_client.py](../abr/hardware/pico_gateway_client.py).

### Aktueller PN5180-Gateway-Pfad

Der bevorzugte aktuelle Pfad verwendet bis zu zwei PN5180 am gemeinsamen
`SPI0`-Bus des Pico. Beide Reader sind im aktuellen Zwei-Reader-Firmwarepfad
aktiv, werden jedoch strikt nacheinander freigegeben. Im Leerlauf bleiben sie
im Reset.

Pico-Belegung:

- UART zum Pi: `GP0` = TX, `GP1` = RX
- gemeinsamer SPI0-Bus:
  - `GP16` = MISO
  - `GP18` = SCK
  - `GP19` = MOSI
- PN5180 #1:
  - `GP2` = NSS
  - `GP3` = BUSY
  - `GP4` = RESET
  - `GP5` = IRQ
- PN5180 #2:
  - `GP6` = NSS
  - `GP7` = BUSY
  - `GP8` = RESET
  - `GP9` = IRQ

Firmware und vollständige Verdrahtung:
[hardware/pn5180_gateway/README.md](../hardware/pn5180_gateway/README.md).

### Alternativer PN532-Gateway-Pfad

Der alternative Pico-Pfad verwendet zwei getrennte I²C-Busse. Dadurch dürfen
beide PN532 dieselbe Adresse `0x24` verwenden:

- PN532 #1: `GP4` = SDA, `GP5` = SCL
- PN532 #2: `GP6` = SDA, `GP7` = SCL
- UART zum Pi unverändert über `GP0/GP1`

Im aktuellen PN532-Firmwarestandard ist Reader 1 aktiv und Reader 2
vorbereitet, aber deaktiviert. Details stehen in
[hardware/pn532_gateway/README.md](../hardware/pn532_gateway/README.md).

## Finale GPIO-Belegung am Raspberry Pi 5

| BCM | Physisch | Richtung/Bus | Funktion | Bemerkung |
| --- | --- | --- | --- | --- |
| `BCM4` | `7` | Out | `MAX98357A SD_MODE` | optional, für das Zielgerät vorgesehen |
| `BCM5` | `29` | In | `EC11 A` | Encoderkanal A |
| `BCM6` | `31` | In | `EC11 B` | Encoderkanal B |
| `BCM12` | `32` | Out | `LED-left` | Logiksignal zum MOSFET, PWM-tauglich |
| `BCM13` | `33` | Out | `LED-right` | Logiksignal zum MOSFET, PWM-tauglich |
| `BCM14 / TXD` | `8` | UART Out | Pico `GP1 / RX` | Pi sendet Gateway-Kommandos |
| `BCM15 / RXD` | `10` | UART In | Pico `GP0 / TX` | Pi empfängt Gateway-Antworten |
| `BCM16` | `36` | In | `EC11-Taster` | Druckfunktion des Lautstärkeknopfs |
| `BCM17` | `11` | In | `Start / Stop / NFC` | Haupttaster |
| `BCM18` | `12` | I2S BCLK | `MAX98357A BCLK` | fest belegt |
| `BCM19` | `35` | I2S LRCLK | `MAX98357A LRC / WS` | fest belegt |
| `BCM21` | `40` | I2S DIN | `MAX98357A DIN` | fest belegt |
| `BCM22` | `15` | In | `Buch-Zusammenfassung` | separater Taster |
| `BCM24` | `18` | In | `Kapitel-/Letzte-Seiten-Zusammenfassung` | separater Taster |

Am Pi gibt es keine NFC-spezifischen SPI-, I²C-, `NSS`-, `BUSY`-, `IRQ`- oder
`RESET`-Leitungen. Insbesondere sind die früher für einen direkten PN5180-Pfad
genannten Pins `BCM7`, `BCM8`, `BCM9`, `BCM10`, `BCM11`, `BCM23` und `BCM25`
nicht mehr für NFC reserviert.

## Reservierte und freie Pins

| BCM | Physisch | Status | Grund |
| --- | --- | --- | --- |
| `BCM0` | `27` | reserviert | EEPROM-/HAT-Sonderfall |
| `BCM1` | `28` | reserviert | EEPROM-/HAT-Sonderfall |
| `BCM2` | `3` | frei halten | I²C-Reserve für spätere Pi-Erweiterungen |
| `BCM3` | `5` | frei halten | I²C-Reserve für spätere Pi-Erweiterungen |
| `BCM7`–`BCM11` | `26, 24, 21, 19, 23` | frei | kein direkter NFC-SPI-Pfad mehr |
| `BCM14` | `8` | belegt | UART TXD zum Pico |
| `BCM15` | `10` | belegt | UART RXD vom Pico |
| `BCM20` | `38` | frei | spätere Erweiterung |
| `BCM23` | `16` | frei | kein direkter NFC-IRQ mehr |
| `BCM25` | `22` | frei | kein direkter NFC-BUSY mehr |
| `BCM26` | `37` | frei | spätere Erweiterung |
| `BCM27` | `13` | frei | spätere Erweiterung |

## Elektrische und betriebliche Hinweise

### Pico und NFC

- Pi und Pico benötigen eine gemeinsame Masse.
- Die UART-Leitungen arbeiten mit 3,3-V-Pegeln; keine 5-V-UART-Signale
  anschließen.
- `TXD` und `RXD` werden gekreuzt: Pi-TX an Pico-RX, Pico-TX an Pi-RX.
- PN5180 und PN532 werden ausschließlich nach der jeweiligen Gateway-README
  am Pico verdrahtet.
- Ein Wechsel zwischen PN5180- und PN532-Gateway ändert die Pi-Verdrahtung
  nicht.

### Audio und Licht

- `BCM18`, `BCM19` und `BCM21` sind durch I²S belegt.
- `BCM12` und `BCM13` liefern nur Logiksignale für die MOSFET-Treiber.
- LED-Lasten dürfen nicht direkt aus einem GPIO versorgt werden.
- Für Hardwaretests steht
  [hardware/led_light_test.py](../hardware/led_light_test.py) bereit.

### Taster und Encoder

- Alle vier Tastereingänge können `active-low` mit internen Pull-ups betrieben
  werden.
- Taster werden softwareseitig entprellt.
- Der EC11 wird im produktiven GPIO-Backend über Flankeninterrupts dekodiert;
  ein Polling-Fallback bleibt vorhanden.

## Softwarefolgen

Die Hardwareaufteilung wird in der Software durch folgende Bausteine
abgebildet:

- GPIO-Abstraktion für Taster, Encoder und Licht
- ein gemeinsamer UART-Gateway-Client für den Pico
- Gateway-Firmware für PN5180 beziehungsweise PN532
- Capture-Orchestrierung für NFC-Abfrage, Licht, Kameras, OCR und TTS
- Zustandslogik für Start, Stop, Wiedergabe und Zusammenfassungen

Der Raspberry Pi enthält keinen PN5180- oder PN532-Treiberpfad. Änderungen an
der Reader-Kommunikation gehören in die jeweilige Pico-Firmware; die
Pi-Anwendung bleibt auf das UART-Protokoll beschränkt.

## Kurzfazit

Der Raspberry Pi 5 steuert Bedienpanel, Licht, Kameras und Audio direkt. Die
gesamte NFC-Hardware ist hinter dem Raspberry Pi Pico gekapselt. Zwischen Pi
und Pico existieren neben gemeinsamer Masse nur die UART-Leitungen
`BCM14/TXD` und `BCM15/RXD`.

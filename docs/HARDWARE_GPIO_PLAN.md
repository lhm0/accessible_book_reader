# Hardware And GPIO Plan

Stand: `2026-06-30`

## Ziel

Dieses Dokument beschreibt den aktuell geplanten Hardwareaufbau des ABR-Zielgeraets und die dazugehoerige GPIO-Belegung auf dem `Raspberry Pi 5`.

Der Bedienpfad ist bewusst auf sehr wenige, klar unterscheidbare Bedienelemente fuer sehbehinderte Nutzer ausgelegt.

## Bedienkonzept

Die geplante Bedienoberflaeche besteht aus:

- `1 x EC11` Drehencoder fuer Lautstaerke
- `1 x` Druckfunktion am Drehencoder
- `3 x` separate Haupttaster

Damit ergeben sich funktional vier Bedienelemente:

1. `Lautstaerke`
   - Drehencoder links/rechts fuer leiser/lauter
   - Druck auf den Encoder als zusaetzliche Taste
2. `Start / Stop / NFC`
   - startet Scan und anschliessende Audioausgabe
   - liest dabei einen eventuell im Buch vorhandenen NFC-Tag
   - beendet laufende Audioausgabe bei erneutem Druck
3. `Buch-Zusammenfassung`
   - sendet den bisher eingelesenen Buchtext an eine KI
   - gibt anschliessend eine Audio-Zusammenfassung aus
4. `Kapitel-/Letzte-Seiten-Zusammenfassung`
   - fasst den letzten relevanten Abschnitt zusammen

Empfohlene physische Ausfuehrung:

- alle Taster als `active-low` gegen `GND`
- interne Pull-ups im Pi verwenden
- Start-Taster mechanisch am groessten und am einfachsten auffindbar ausfuehren
- die beiden Zusammenfassungs-Taster taktil klar unterscheidbar ausfuehren

## Geplante Hardware

- Hauptrechner: `Raspberry Pi 5`
- Audio: `MAX98357A` ueber `I2S`
- Lautstaerke: `EC11` Drehencoder mit Drucktaster
- NFC: entweder `PN5180` direkt am Pi oder `2 x PN532` ueber ein `RP2040`-Gateway
- Kameras: `2 x Arducam 16 MP IMX519` mit `140 Grad` M12-Weitwinkelobjektiv
- Kameraanschluss: direkt an die beiden Kameraanschluesse des Pi 5
- Licht: zwei getrennt schaltbare LED-Kanaele ueber je einen MOSFET

Aktuelle Hardware-Arbeitsstaende im Repo:

- Pi-Hauptverdrahtung: [hardware/electronics/abr_pi5_header](../hardware/electronics/abr_pi5_header)
- Bedienpanel: [hardware/electronics/control_panel](../hardware/electronics/control_panel)
- LED-Leiste: [hardware/electronics/LED_bar_long](../hardware/electronics/LED_bar_long)
- Mechanik: [hardware/mechanics](../hardware/mechanics)

Historischer Hinweis:

- `LED_bar_short` ist nicht mehr der aktive Elektronikpfad

Logische Kamerazuordnung:

- `left` Kamera an `CAM0`
- `right` Kamera an `CAM1`

Die Kameras belegen keine GPIOs, sondern die beiden CSI-Kameraports des Pi 5.

Aktuelle Software-Arbeitsbasis fuer die Bildentzerrung:

- `calibration/out/cam0_planar.npz` fuer `CAM0`
- `calibration/out/cam1_planar.npz` fuer `CAM1`

## NFC-Varianten: Softwarepfad Und GPIO-Randbedingungen

### Variante A: PN5180

Der `PN5180` verwendet laut NXP eine `SPI`-Hostschnittstelle und zusaetzlich mindestens weitere Steuersignale:

- `NSS`
- `BUSY`
- `IRQ`
- `RESET`

NXP dokumentiert fuer Linux explizit einen Raspberry-Pi-Pfad. In `AN11802` ist fuer den `PN5180` auf Raspberry Pi folgende Verdrahtung als Referenz hinterlegt:

- `SPI0 MOSI` -> `GPIO10`
- `SPI0 MISO` -> `GPIO9`
- `SPI0 SCLK` -> `GPIO11`
- `NSS / CE0` -> `GPIO8`
- `nRESET` -> `GPIO7`
- `BUSY` -> `GPIO25`
- `IRQ` -> `GPIO23`

Diese Belegung ist fuer ABR die beste Ausgangsbasis, weil sie mit der offiziellen NXP-Raspberry-Pi-Referenz uebereinstimmt.

### Variante B: RP2040-Gateway Mit Zwei PN532

Die direkte PN532-Anbindung am Raspberry Pi wurde fuer ABR wieder verworfen. Der aktuelle Zielpfad ist:

- `2 x PN532` jeweils per `I2C` an einem eigenen Bus des `RP2040`
- `RP2040` als Gateway
- `Raspberry Pi 5` fragt das Gateway per `UART` ab

Auf dem Pi werden dafuer nur diese Leitungen benoetigt:

- `GPIO14` -> `RP2040 GP1 / RX`
- `GPIO15` <- `RP2040 GP0 / TX`

Auf dem RP2040 sind die beiden Reader so vorgesehen:

- Reader 1: `GP4` = `SDA`, `GP5` = `SCL`
- Reader 2: `GP6` = `SDA`, `GP7` = `SCL`

Beide PN532 duerfen dabei dieselbe I2C-Adresse `0x24` verwenden, weil sie auf getrennten Bussen des Gateways haengen.

Wichtiger aktueller Firmwarehinweis:

- in [hardware/pn532_gateway/src/pico_gateway.cpp](../hardware/pn532_gateway/src/pico_gateway.cpp) ist Reader `1` standardmaessig aktiv
- Reader `2` ist vorbereitet, aber derzeit per `kEnableReader2 = false` deaktiviert

### Variante C: RP2040-Gateway Mit Einem Oder Zwei PN5180

Als implementierter Alternativpfad liegt jetzt ein eigener Pico-Gateway fuer `PN5180` vor:

- gemeinsamer `SPI0`-Bus des Pico
- unveraenderte UART-Hostschnittstelle zum Pi
- pro Reader eigene Leitungen fuer `NSS`, `BUSY`, `RESET`, `IRQ`

Aktuell vorgesehene Pico-Belegung:

- gemeinsamer Bus:
  - `GP16` = `MISO`
  - `GP18` = `SCK`
  - `GP19` = `MOSI`
- Reader 1:
  - `GP2` = `NSS`
  - `GP3` = `BUSY`
  - `GP4` = `RESET`
  - `GP5` = `IRQ`
- Reader 2:
  - `GP6` = `NSS`
  - `GP7` = `BUSY`
  - `GP8` = `RESET`
  - `GP9` = `IRQ`

Wichtiger aktueller Firmwarehinweis:

- in [hardware/pn5180_gateway/src/pico_gateway.cpp](../hardware/pn5180_gateway/src/pico_gateway.cpp) ist Reader `1` standardmaessig aktiv
- Reader `2` ist vorbereitet, aber derzeit per `kEnableReader2 = false` deaktiviert
- der stabile Default arbeitet `ISO15693`-only fuer die Buchkennung
- `ISO14443A` und der LED-Heartbeat bleiben als Compile-Time-Debugoptionen im Code
- der Pico setzt den UART nach dem Boot einmal neu auf, um Stoerzeichen aus der gemeinsamen Einschaltphase mit dem Pi abzuraeumen

### Bibliotheksentscheidung

#### PN5180

Fuer den Pi existiert zwar das Python-Paket `pn5180pi`, aber dieser Pfad ist fuer ABR auf dem `Raspberry Pi 5` nicht die richtige Basis:

- `pn5180pi` wurde auf PyPI zuletzt am `2022-07-27` veroeffentlicht
- es verwendet `pigpio`
- es unterstuetzt laut Projektbeschreibung nur `ISO15693`

Raspberry Pi dokumentiert fuer den Pi 5 dagegen, dass der alte direkte Hardwarezugriff von `pigpio` bzw. klassischen Altbibliotheken kein guter Zielpfad mehr ist; fuer Pi-5-taugliche GPIO-Zugriffe wird `lgpio` bzw. `rpi-lgpio` empfohlen.

Deshalb ist fuer ABR der bevorzugte Softwarepfad:

- `spidev` fuer die SPI-Transfers zum `PN5180`
- `rpi-lgpio` oder `gpiozero` mit `LGPIOFactory` fuer `BUSY`, `IRQ`, `RESET` und die lokalen Taster

Falls spaeter mehr PN5180-Funktionalitaet als ein einfacher Tag-Read benoetigt wird, ist die groessere offizielle Eskalationsoption die `NXP NFC Reader Library for Linux` in `C`. Fuer die ABR-Anwendung ist das aber erst dann sinnvoll, wenn der einfachere Userspace-Pfad funktional nicht mehr ausreicht.

#### PN532

Der bevorzugte Softwarepfad ist jetzt nicht mehr direkte Pi-zu-PN532-Kommunikation, sondern:

- `RP2040`-Firmware unter [hardware/pn532_gateway/src/pico_gateway.cpp](../hardware/pn532_gateway/src/pico_gateway.cpp)
- zeilenbasiertes UART-Protokoll zwischen Pi und Gateway
- schlanker RP5-Client unter [abr/hardware/pico_gateway_client.py](../abr/hardware/pico_gateway_client.py)

### GPIO-Auswahlregeln Fuer Dieses Projekt

Bei der Pinwahl gelten zusaetzlich diese Regeln:

- `GPIO0` und `GPIO1` nicht verwenden
  - diese Pins sind fuer EEPROM/HAT-Sonderfaelle reserviert
- `GPIO2` und `GPIO3` moeglichst frei halten
  - Reserve fuer spaetere I2C-Erweiterungen am Pi
- `GPIO14` und `GPIO15` fuer den UART-Pfad des RP2040-Gateways reservieren
- fuer Lichttrigger moeglichst Pins waehlen, die spaeter auch PWM-reserviert nutzbar bleiben

## Finale GPIO-Belegung

### Immer Belegte Pins

| BCM | Physisch | Richtung | Funktion | Bemerkung |
| --- | --- | --- | --- | --- |
| `GPIO4` | `7` | Out | `MAX98357A SD_MODE` | optional, aber fuer das Zielgeraet vorgesehen |
| `GPIO5` | `29` | In | `EC11 A` | Encoder Kanal A |
| `GPIO6` | `31` | In | `EC11 B` | Encoder Kanal B |
| `GPIO12` | `32` | Out | `LED-left` | linker LED-Kanal, PWM-tauglich |
| `GPIO13` | `33` | Out | `LED-right` | rechter LED-Kanal, PWM-tauglich |
| `GPIO16` | `36` | In | `EC11 Taster` | Druckfunktion des Lautstaerkeknopfs |
| `GPIO17` | `11` | In | `Start / Stop / NFC` | Haupttaster |
| `GPIO18` | `12` | I2S BCLK | `MAX98357A BCLK` | bereits festgelegt |
| `GPIO19` | `35` | I2S LRCLK | `MAX98357A LRC / WS` | bereits festgelegt |
| `GPIO21` | `40` | I2S DIN | `MAX98357A DIN` | bereits festgelegt |
| `GPIO22` | `15` | In | `Buch-Zusammenfassung` | separater Taster |
| `GPIO24` | `18` | In | `Kapitel-/Letzte-Seiten-Zusammenfassung` | separater Taster |

### NFC-Variante A: PN5180

| BCM | Physisch | Richtung | Funktion | Bemerkung |
| --- | --- | --- | --- | --- |
| `GPIO7` | `26` | Out | `PN5180 RESET` | gem. NXP-Raspberry-Pi-Referenz |
| `GPIO8` | `24` | SPI CE0 | `PN5180 NSS` | offizieller SPI0-CS-Pfad |
| `GPIO9` | `21` | SPI MISO | `PN5180 MISO` | SPI0 |
| `GPIO10` | `19` | SPI MOSI | `PN5180 MOSI` | SPI0 |
| `GPIO11` | `23` | SPI SCLK | `PN5180 SCLK` | SPI0 |
| `GPIO23` | `16` | In | `PN5180 IRQ` | gem. NXP-Raspberry-Pi-Referenz |
| `GPIO25` | `22` | In | `PN5180 BUSY` | gem. NXP-Raspberry-Pi-Referenz |

### NFC-Variante B: RP2040-PN532-Gateway

| BCM | Physisch | Richtung | Funktion | Bemerkung |
| --- | --- | --- | --- | --- |
| `GPIO14` | `8` | UART TX | `RP2040 GP1 RX` | Pi sendet Kommandos an das Gateway |
| `GPIO15` | `10` | UART RX | `RP2040 GP0 TX` | Pi empfaengt Gateway-Antworten |

### Reservierte Oder Freie Pins

| BCM | Physisch | Status | Grund |
| --- | --- | --- | --- |
| `GPIO0` | `27` | reserviert | EEPROM/HAT-Sonderfall |
| `GPIO1` | `28` | reserviert | EEPROM/HAT-Sonderfall |
| `GPIO2` | `3` | frei halten | I2C-Reserve fuer spaetere Erweiterungen |
| `GPIO3` | `5` | frei halten | I2C-Reserve fuer spaetere Erweiterungen |
| `GPIO14` | `8` | reserviert | RP2040-Gateway UART TX |
| `GPIO15` | `10` | reserviert | RP2040-Gateway UART RX |
| `GPIO20` | `38` | frei | spaetere Erweiterung |
| `GPIO26` | `37` | frei | spaetere Erweiterung |
| `GPIO27` | `13` | frei | spaetere Erweiterung |

## Wechselwirkungen Und Hinweise

### NFC allgemein

- Es wird immer nur `eine` NFC-Variante verdrahtet: entweder `PN5180` direkt am Pi oder das `RP2040-PN532-Gateway`.
- `GPIO23` und `GPIO25` bleiben fuer den direkten `PN5180`-Pfad vorgesehen und sind beim Gateway-Pfad frei.
- Wenn das `RP2040-PN532-Gateway` verwendet wird, bleiben die `SPI0`-Pins `GPIO7/8/9/10/11` frei.
- Wenn `PN5180` verwendet wird, bleiben `GPIO14/15` fuer spaetere Service- oder UART-Erweiterungen verfuegbar.

### PN5180

- Die PN5180-Leitungen sind bewusst auf `SPI0 + GPIO7/23/25` gelegt, damit ein spaeterer Wechsel auf die offizielle `NXP NFC Reader Library for Linux` ohne Umverdrahtung moeglich bleibt.
- `BUSY` und `IRQ` sind Eingangsleitungen vom Reader zum Pi.
- `RESET` und `NSS` gehen vom Pi zum Reader.

### RP2040-PN532-Gateway

- Der Pi spricht nicht direkt mit den PN532-Modulen, sondern nur mit dem Gateway.
- Die eigentlichen PN532-I2C-Busse liegen auf dem RP2040 und nicht auf dem Pi.
- Der Pi braucht dafuer nur den Header-UART auf `GPIO14/15`.

### Audio Und Licht

- `GPIO18`, `GPIO19` und `GPIO21` sind durch `I2S` belegt und duerfen nicht fuer andere Funktionen eingeplant werden.
- `GPIO12` und `GPIO13` sind nur Logiksignale fuer die beiden MOSFET-Treiber von `LED-left` und `LED-right`.
- Die eigentliche LED-Leistung muss ueber Treiberstufen wie MOSFETs oder dedizierte LED-Treiber geschaltet werden.
- LED-Lasten duerfen nicht direkt aus dem GPIO versorgt werden.
- Fuer schnelle Hardwaretests liegt ein einfaches Schaltskript unter [hardware/led_light_test.py](../hardware/led_light_test.py).

### Taster Und Encoder

- Alle vier lokalen Tasteringaben koennen als `active-low` mit internen Pull-ups betrieben werden.
- Der Encoder sollte softwareseitig entprellt werden.
- Fuer den Start-Taster ist eine robuste Entprellung besonders wichtig, damit Start/Stop/NFC nicht versehentlich doppelt ausloesen.

## Software-Folgen Fuer ABR

Die Hardwareplanung zieht diese spaeteren Softwarebausteine nach sich:

- GPIO-Abstraktion fuer Taster, Encoder und Licht
- NFC-Gateway-Client fuer den RP2040-PN532-Pfad bzw. spaetere PN5180-Komponente
- Capture-Orchestrierung fuer:
  - `NFC lesen`
  - `LED-left ein/aus`
  - `LED-right ein/aus`
  - `linke Kamera`
  - `rechte Kamera`
  - `OCR/TTS`
- klare Zustandslogik fuer den Start-Taster:
  - `idle` -> NFC lesen, Scan starten, Audio erzeugen
  - `playing` -> Audio stoppen

## Kurzfazit

Die Belegung priorisiert:

- einfache Bedienung mit sehr wenigen Bedienelementen
- Pi-5-kompatible GPIO-/NFC-Software
- minimale Kollisionen mit reservierten Pi-Funktionen
- Anschlusskompatibilitaet zum von NXP dokumentierten PN5180-Raspberry-Pi-Pfad

# PN532 Pico Gateway

Dieses Unterprojekt enthaelt die aktuelle NFC-Hardwareanbindung fuer `abr`:

- ein Raspberry Pi Pico als Gateway
- zwei PN532-Module, jeweils an einem eigenen I2C-Bus des Pico
- ein Raspberry Pi 5, der den Pico per UART abfragt

Der aktuelle Firmware-Stand aktiviert standardmaessig nur `PN532 #1`. `PN532 #2`
ist vorbereitet, aber in der Firmware per `kEnableReader2 = false` abgeschaltet.

Auf dem derzeitigen Stand ist also:

- Reader `1` der aktive Referenzpfad
- Reader `2` elektrisch und softwareseitig vorbereitet
- die Freischaltung des zweiten Readers noch bewusst nicht Default

## Konzept

Die Architektur ist:

- `PN532 #1` an Pico-I2C-Bus auf `GP4/GP5`
- `PN532 #2` an Pico-I2C-Bus auf `GP6/GP7`
- UART zwischen Pico und RP5 ueber `GP0/GP1` bzw. `GPIO15/GPIO14`
- der Pico uebernimmt Initialisierung, Reconnect, Tag-Polling und Statushaltung
- der RP5 fragt den Pico nur noch per Textkommando ab

Beide PN532 duerfen dieselbe I2C-Adresse `0x24` haben, weil sie auf getrennten Bussen liegen.

## Firmware

- PlatformIO-Environment: `pico`
- Quelle: [src/pico_gateway.cpp](../../hardware/pn532_gateway/src/pico_gateway.cpp)

Build:

```bash
pio run -e pico
```

Die erzeugte UF2-Datei liegt danach unter:

```bash
.pio/build/pico/firmware.uf2
```

## Verdrahtung

### UART zum Raspberry Pi 5

Pico:

- `GP0` = TX zum RP5
- `GP1` = RX vom RP5
- `GND` gemeinsam

RP5:

- `GPIO15 / RXD` <- Pico `GP0 / TX`
- `GPIO14 / TXD` -> Pico `GP1 / RX`
- `GND` gemeinsam

Wichtig: nur 3,3-V-Pegel verwenden.

### PN532 #1

- `GP4` -> `SDA`
- `GP5` -> `SCL`
- `3V3` -> `VCC`
- `GND` -> `GND`

### PN532 #2

- `GP6` -> `SDA`
- `GP7` -> `SCL`
- `3V3` -> `VCC`
- `GND` -> `GND`

## UART Protokoll

Der Pico akzeptiert zeilenbasierte ASCII-Kommandos mit Newline.

Befehle:

- `PING`
- `STATUS`
- `STATUS 1`
- `STATUS 2`
- `REINIT`
- `REINIT 1`
- `REINIT 2`
- `DIAG`
- `HELP`

Beispielantwort auf `STATUS`:

```text
OK uptime_ms=12345
READER id=1 label=PN532-1 enabled=1 online=1 fw=0x32010607 tag=0 uid=- irq_mode=1 last_error=none
READER id=2 label=PN532-2 enabled=0 online=0 fw=0x00000000 tag=0 uid=- irq_mode=-1 last_error=boot
END
```

## Flashen

Die Datei `.pio/build/pico/firmware.uf2` auf den Pico im Bootloader-Modus kopieren.

Serieller Monitor waehrend der Entwicklung:

```bash
pio device monitor -b 115200
```

## RP5 Client

Das integrierte Clientmodul fuer `abr` liegt unter:

- [abr/hardware/pico_gateway_client.py](../../abr/hardware/pico_gateway_client.py)

Terminal-Wrapper im Projekt:

- [hardware/pn532_gateway_client.py](../../hardware/pn532_gateway_client.py)

Kompatibilitaets-Wrapper an der urspruenglichen Unterprojekt-Stelle:

- [rp5/pico_gateway_client.py](../../hardware/pn532_gateway/rp5/pico_gateway_client.py)

Beispiele:

```bash
python3 hardware/pn532_gateway_client.py
python3 hardware/pn532_gateway_client.py STATUS 1
python3 hardware/pn532_gateway_client.py DIAG
python3 hardware/pn532_gateway_client.py PING
python3 hardware/pn532_gateway_client.py REINIT 2
```

Abweichendes UART-Geraet oder Timeout:

```bash
python3 hardware/pn532_gateway_client.py --device /dev/ttyAMA0 --timeout 2.0 STATUS
```

Auf dem aktuell eingerichteten Pi ist `ttyAMA0` der relevante Header-UART. `serial0` kann auf anderen Pi-Setups abweichend gemappt sein.

## RP5 Test

UART auf dem Raspberry Pi 5 z. B. mit `115200 8N1` konfigurieren:

```bash
stty -F /dev/ttyAMA0 115200 raw -echo
```

Status anfordern:

```bash
printf 'STATUS\n' > /dev/ttyAMA0
timeout 1 cat /dev/ttyAMA0
```

Diagnose anfordern:

```bash
printf 'DIAG\n' > /dev/ttyAMA0
timeout 1 cat /dev/ttyAMA0
```

Clientskript verwenden:

```bash
cd /pfad/zu/abr
python3 hardware/pn532_gateway_client.py PING
python3 hardware/pn532_gateway_client.py STATUS
```

## Projektinhalt

- [src/pico_gateway.cpp](../../hardware/pn532_gateway/src/pico_gateway.cpp): Gateway-Firmware
- [lib/Seeed_Arduino_NFC_Minimal](../../hardware/pn532_gateway/lib/Seeed_Arduino_NFC_Minimal/src/PN532/PN532/PN532.h): lokaler PN532-I2C-Minimalteil
- [platformio.ini](../../hardware/pn532_gateway/platformio.ini): Build-Konfiguration

## Lokale PN532 Bibliothek

Die fuer dieses Projekt benoetigte PN532-I2C-Teilmenge liegt lokal unter:

- [lib/Seeed_Arduino_NFC_Minimal/src/PN532/PN532/PN532.h](../../hardware/pn532_gateway/lib/Seeed_Arduino_NFC_Minimal/src/PN532/PN532/PN532.h)
- [lib/Seeed_Arduino_NFC_Minimal/src/PN532/PN532/PN532.cpp](../../hardware/pn532_gateway/lib/Seeed_Arduino_NFC_Minimal/src/PN532/PN532/PN532.cpp)
- [lib/Seeed_Arduino_NFC_Minimal/src/PN532/PN532_I2C/PN532_I2C.cpp](../../hardware/pn532_gateway/lib/Seeed_Arduino_NFC_Minimal/src/PN532/PN532_I2C/PN532_I2C.cpp)

Der Grund ist pragmatisch: fuer den Pico wird nur der I2C-Pfad benoetigt, waehrend die komplette Seeed-Library auf dem verwendeten RP2040-Mbed-Core an unbenutzten SPI- und SoftwareSerial-Backends scheitert.

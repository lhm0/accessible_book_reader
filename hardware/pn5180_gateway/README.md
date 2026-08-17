# PN5180 Pico Gateway

Dieses Unterprojekt ist der aktuelle PN5180-NFC-Gateway-Pfad fuer `abr`:

- ein Raspberry Pi Pico als Gateway
- bis zu zwei PN5180-Reader am gemeinsamen `SPI0`-Bus des Pico
- ein Raspberry Pi 5, der den Pico unveraendert per UART abfragt

Die Host-Schnittstelle zum Raspberry Pi bleibt bewusst dieselbe wie beim
`pn532_gateway`:

- gleiche ASCII-Kommandos
- gleiche `PING`-/`STATUS`-/`REINIT`-/`DIAG`-Struktur
- gleiche UART-Baudrate `115200`

Der aktuelle Firmware-Stand am `2026-07-30` ist auf den realen
Zwei-Reader-Aufbau mit Relaisumschaltung abgestimmt:

- `PN5180 #1` und `PN5180 #2` sind aktiv
- beide Reader teilen sich weiterhin denselben `SPI0`-Bus
- beide Reader werden aber nie gleichzeitig freigegeben
- im Leerlauf bleiben beide PN5180 in `RESET`
- ein Reader wird nur fuer einen expliziten Befehl kurz freigegeben
- die Freigabe erfolgt strikt nacheinander, so dass immer nur ein
  Antennen-/Relaispfad aktiv ist
- die Statuslogik prueft aktuell wieder `ISO14443A` und `ISO15693`
- der feste Default fuer `RX_WAIT_CONFIG` ist `0x00000878`

## Konzept

Die Architektur ist:

- UART zwischen Pico und RP5 ueber `GP0/GP1` bzw. `GPIO15/GPIO14`
- gemeinsamer `SPI0`-Bus auf dem Pico fuer beide PN5180
- pro PN5180 eigene Leitungen fuer:
  - `NSS`
  - `BUSY`
  - `RESET`
  - `IRQ`
- kein permanentes Reader-Polling
- textbasierte Statusabfrage vom Raspberry Pi

Der normale Firmware-Stand verwendet aktuell fuer `STATUS`
einen on-demand-Lesepfad:

- harter Reader-Reset
- RF-Neuaufbau
- zuerst `ISO14443A`
- danach `ISO15693`
- danach Rueckkehr in `RESET`

Bei fruehen Reader- oder Kommunikationsfehlern wird derselbe Status-Probe
mehrfach wiederholt, bevor die Firmware aufgibt.

## Firmware

- PlatformIO-Environment: `pico`
- Quelle: [src/pico_gateway.cpp](../../hardware/pn5180_gateway/src/pico_gateway.cpp)

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

Wichtig: nur `3,3 V`-Pegel verwenden.

### Gemeinsamer SPI0-Bus

- `GP16` -> `MISO`
- `GP18` -> `SCK`
- `GP19` -> `MOSI`
- `3V3` -> `VCC`
- `GND` -> `GND`

### PN5180 #1

- `GP2` -> `NSS`
- `GP3` <- `BUSY`
- `GP4` -> `RESET`
- `GP5` <- `IRQ`

### PN5180 #2

- `GP6` -> `NSS`
- `GP7` <- `BUSY`
- `GP8` -> `RESET`
- `GP9` <- `IRQ`

### Nicht Verwendete Breakout-Pins

Die typischen zusaetzlichen Breakout-Signale wie `GPIO`, `AUX` oder `REQ`
werden fuer diesen Gateway-Stand nicht benoetigt.

## Pinwahl Am Pico

Die Belegung ist bewusst so gewaehlt:

- `GP0/GP1` bleiben exklusiv fuer den UART-Pfad zum Pi reserviert
- `GP2..GP9` bilden zwei leicht merkbare Reader-Gruppen
- `SPI0` bleibt auf der Standardbelegung `GP16/GP18/GP19`
- damit ist keine Sonderkonfiguration eines alternativen SPI-Routings noetig
- `GP10..GP15` und `GP17` bleiben als Reserve frei

## UART Protokoll

Der Pico akzeptiert zeilenbasierte ASCII-Kommandos mit Newline.

Befehle:

- `PING`
- `STATUS`
- `STATUS 1`
- `STATUS 2`
- `STATUS_START`
- `STATUS_START 1`
- `STATUS_START 2`
- `STATUS_FETCH`
- `REINIT`
- `REINIT 1`
- `REINIT 2`
- `DIAG`
- `TYPEA_DIAG`
- `TYPEA_TUNE`
- `TYPEA_TUNE 1`
- `TYPEA_TUNE 1 RXWAIT 0x00000878`
- `TYPEA_SWEEP`
- `TYPEA_SWEEP 1`
- `TYPEA_SWEEP 1 20`
- `HELP`

Hinweise:

- `STATUS` ist synchron und liefert das Ergebnis direkt
- `STATUS_START` startet die Statusermittlung asynchron und kehrt sofort zurueck
- `STATUS_FETCH` holt das zuletzt angestossene Ergebnis ab und wartet bei
  Bedarf bis zum Abschluss
- `TYPEA_DIAG` fuehrt denselben Pfad explizit fuer `REQA` und `WUPA` mit
  Detailausgabe aus
- `TYPEA_SWEEP` testet mehrere `RXWAIT`-Werte nacheinander und kann deutlich
  laenger laufen als ein normaler `STATUS`

Beispielantwort auf `STATUS`:

```text
OK uptime_ms=12345
READER id=1 label=PN5180-1 enabled=1 online=1 fw=0x04000400 tag=1 uid=53:33:B1:6D:22:00:01 tech=ISO14443A len=7 agc=99 rf_status=0x00060063 rx_status=0x00000001 rx_len=1 tag15693=0 uid15693=- len15693=- tag14443a=1 uid14443a=53:33:B1:6D:22:00:01 len14443a=7 last_error=none
READER id=2 label=PN5180-2 enabled=1 online=1 fw=0x04000400 tag=1 uid=E0:04:01:09:16:F0:5F:A7 tech=ISO15693 len=8 agc=152 rf_status=0x01060098 rx_status=0x0000000A rx_len=10 tag15693=1 uid15693=E0:04:01:09:16:F0:5F:A7 len15693=8 tag14443a=0 uid14443a=- len14443a=- last_error=none
END
```

Hinweise zur PN5180-spezifischen Bedeutung:

- `fw` packt `product_major`, `product_minor`, `firmware_major`, `firmware_minor`
  in ein `uint32`-Hexfeld
- `agc` ist der aktuelle `RF_STATUS.AGC_VALUE` des PN5180
- `rf_status` ist der komplette rohe Registerwert `RF_STATUS`
- `rx_status` ist der komplette rohe Registerwert `RX_STATUS`
- `rx_len` ist die aus `RX_STATUS[8:0]` abgeleitete empfangene Nutzdatenlaenge

Wichtig:

- `tech` zeigt den bevorzugten Snapshot des Readers
- wenn sowohl `ISO14443A` als auch `ISO15693` gefunden werden, sind die
  protokollspezifischen Felder massgeblich
- `RX_STATUS` ist fuer die weitere Bewertung der Empfangsqualitaet oft
  aussagekraeftiger als die intern geregelte AGC-Groesse allein
- `TYPEA_TUNE` zeigt im Normalfall `override_rxwait=off`; das ist korrekt, weil
  `0x00000878` als fester Default in der Firmware hinterlegt ist

## Flashen

Die Datei `.pio/build/pico/firmware.uf2` auf den Pico im Bootloader-Modus kopieren.

Serieller Monitor waehrend der Entwicklung:

```bash
pio device monitor -b 115200
```

Die Firmware wartet beim Boot aktuell etwa `3 s`, bevor die ersten
USB-Debugmeldungen gesendet werden. Das soll sicherstellen, dass ein frisch
geoeffneter Monitor die Startmeldungen zuverlaessiger sieht.

Wichtig: Die UART-Schnittstelle zum Raspberry Pi wird dabei bereits sofort
aktiviert und waehrend dieser Wartezeit schon bedient. `PING`, `STATUS` und
`STATUS_START` muessen also auch waehrend des Startfensters antworten.

Zusätzlich setzt die Firmware den Pico-UART etwa `1 s` nach dem Boot einmal
gezielt neu auf und leert den RX-Puffer. Das soll Stoerzeichen oder
Fragmentbytes aus der gemeinsamen Einschaltphase zwischen `RP5` und `Pico`
abraeumen.

Zusätzlich wartet der normale Firmware-Stand nach dem Einschalten noch einige
Sekunden, bevor die PN5180-Initialisierung startet. Dadurch wird ein kalter
Gesamtstart robuster, wenn `Raspberry Pi 5`, `Pico` und Reader gleichzeitig
hochfahren und die Versorgung bzw. das Reader-Startup noch nicht stabil sind.

Im aktuellen on-demand-Stand bleiben die PN5180 auch nach der Startphase im
Leerlauf in `RESET` und werden erst fuer einen konkreten Readerzugriff
freigegeben.

Im Normalbetrieb ist das USB-Log jetzt bewusst knapp:

- Bootmeldungen
- `Tag erkannt` inklusive `UID`, `AGC`, `RF_STATUS` und `RX_STATUS`
- `Tag entfernt` inklusive letzter `UID`, `AGC`, `RF_STATUS` und `RX_STATUS`
- bei `Return` im USB-Seriellmonitor: aktuelle Statusausgabe pro Reader
  inklusive `UID`, `Tech`, `Len`, `AGC`, `RF_STATUS` und `RX_STATUS`
- per USB steuerbare `TYPEA`-Diagnose
- per USB steuerbarer `RXWAIT`-Sweep
- per USB steuerbarer Signal-Scan und RF-Profil-Scan fuer weitere Margin-Tests

USB-Befehle:

- `HELP`
- `STATUS`
- `STATUS_START`
- `STATUS_START 1`
- `STATUS_START 2`
- `STATUS_FETCH`
- `TYPEA_DIAG`
- `TYPEA_TUNE`
- `TYPEA_TUNE 1`
- `TYPEA_TUNE 1 RXWAIT 0x00000878`
- `TYPEA_SWEEP`
- `TYPEA_SWEEP 1`
- `TYPEA_SWEEP 1 20`
- `SCAN`
- `SCAN 1`
- `SCAN 1 16`
- `PROFILESCAN`
- `PROFILESCAN 1`
- `PROFILESCAN 1 8`

Optional kann die Pico-Onboard-LED einen Heartbeat anzeigen. Standardmaessig
ist diese Debug-Funktion aktuell abgeschaltet und kann ueber
`kEnableHeartbeatDebug` in der Firmware wieder aktiviert werden.

- schnelles Blinken: Reader-Fehler, aktuell kein Reader online
- langsames Blinken: Startwartephase vor der ersten PN5180-Initialisierung
- kurzer Puls etwa alle 2 Sekunden: Firmware laeuft, Reader online, kein Tag erkannt
- dauerhaft an: Tag aktuell erkannt

Im aktuellen Stand ist `ISO14443A` bereits der aktive Hauptpfad. Fuer weitere
Grenztests dienen deshalb vor allem `TYPEA_DIAG`, `TYPEA_TUNE` und
`TYPEA_SWEEP`.

## RP5 Client

Das integrierte Clientmodul fuer `abr` bleibt dasselbe wie beim PN532-Gateway:

- [abr/hardware/pico_gateway_client.py](../../abr/hardware/pico_gateway_client.py)

Terminal-Wrapper im Projekt:

- [hardware/pn5180_gateway_client.py](../../hardware/pn5180_gateway_client.py)

Kompatibilitaets-Wrapper an der Unterprojekt-Stelle:

- [rp5/pico_gateway_client.py](../../hardware/pn5180_gateway/rp5/pico_gateway_client.py)

Beispiele:

```bash
python3 hardware/pn5180_gateway_client.py
python3 hardware/pn5180_gateway_client.py STATUS 1
python3 hardware/pn5180_gateway_client.py STATUS_START
python3 hardware/pn5180_gateway_client.py STATUS_FETCH
python3 hardware/pn5180_gateway_client.py TYPEA_DIAG
python3 hardware/pn5180_gateway_client.py PING
python3 hardware/pn5180_gateway_client.py REINIT 1
python3 hardware/pn5180_gateway_client.py --timeout 90 TYPEA_SWEEP 1 20
```

Abweichendes UART-Geraet oder Timeout:

```bash
python3 hardware/pn5180_gateway_client.py --device /dev/ttyAMA0 --timeout 10 STATUS
```

## Aktueller Testablauf

Empfohlene Kurzsequenz auf dem Pi:

```bash
python3 hardware/pn5180_gateway_client.py --timeout 10 STATUS
python3 hardware/pn5180_gateway_client.py STATUS_START
python3 hardware/pn5180_gateway_client.py STATUS_FETCH
python3 hardware/pn5180_gateway_client.py --timeout 10 TYPEA_DIAG
```

Asynchroner Pfad fuer ein Hauptprogramm:

```bash
python3 hardware/pn5180_gateway_client.py STATUS_START
# hier kann das Hauptprogramm andere Arbeit erledigen
python3 hardware/pn5180_gateway_client.py STATUS_FETCH
```

Fuer `RXWAIT`-Vergleiche:

```bash
python3 hardware/pn5180_gateway_client.py --timeout 90 TYPEA_SWEEP 1 20
```

Wichtig:

- bei `TYPEA_SWEEP` erst dann den naechsten Befehl senden, wenn wirklich
  `END` erschienen ist
- sonst liest der naechste Clientaufruf leicht Restzeilen eines noch laufenden
  Sweeps ein
- der bisher beste feste `RXWAIT`-Standardwert ist `0x00000878`

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
printf 'TYPEA_DIAG\n' > /dev/ttyAMA0
timeout 10 cat /dev/ttyAMA0
```

Clientskript verwenden:

```bash
cd /pfad/zu/abr
python3 hardware/pn5180_gateway_client.py PING
python3 hardware/pn5180_gateway_client.py STATUS
python3 hardware/pn5180_gateway_client.py TYPEA_DIAG
```

## Projektinhalt

- [src/pico_gateway.cpp](../../hardware/pn5180_gateway/src/pico_gateway.cpp): Gateway-Firmware
- [platformio.ini](../../hardware/pn5180_gateway/platformio.ini): Build-Konfiguration
- [lib/PN5180_Library_Minimal](../../hardware/pn5180_gateway/lib/PN5180_Library_Minimal/src/PN5180.h): lokaler PN5180-Minimalteil

## Lokale PN5180 Bibliothek

Das Unterprojekt fuehrt die benoetigte Teilmenge der `PN5180-Library` lokal mit:

- [lib/PN5180_Library_Minimal/src/PN5180.h](../../hardware/pn5180_gateway/lib/PN5180_Library_Minimal/src/PN5180.h)
- [lib/PN5180_Library_Minimal/src/PN5180.cpp](../../hardware/pn5180_gateway/lib/PN5180_Library_Minimal/src/PN5180.cpp)
- [lib/PN5180_Library_Minimal/src/PN5180ISO14443.h](../../hardware/pn5180_gateway/lib/PN5180_Library_Minimal/src/PN5180ISO14443.h)
- [lib/PN5180_Library_Minimal/src/PN5180ISO14443.cpp](../../hardware/pn5180_gateway/lib/PN5180_Library_Minimal/src/PN5180ISO14443.cpp)
- [lib/PN5180_Library_Minimal/src/PN5180ISO15693.h](../../hardware/pn5180_gateway/lib/PN5180_Library_Minimal/src/PN5180ISO15693.h)
- [lib/PN5180_Library_Minimal/src/PN5180ISO15693.cpp](../../hardware/pn5180_gateway/lib/PN5180_Library_Minimal/src/PN5180ISO15693.cpp)

Grund fuer die lokale Mitfuehrung:

- reproduzierbarer Build ohne Registry-Zwang
- dieselbe Repo-Strategie wie beim `pn532_gateway`
- nur die fuer das Gateway benoetigte Arduino-Teilmenge liegt im Projekt

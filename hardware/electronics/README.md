# Electronics Uebersicht

Dieses Verzeichnis enthaelt die aktuellen KiCad-Hardwareprojekte des ABR-Aufbaus.

## Aktive Teilprojekte

- [abr_pi5_header](../../hardware/electronics/abr_pi5_header/abr_pi5_header.kicad_sch)
  - Hauptverdrahtung rund um den `Raspberry Pi 5`
  - Audio (`MAX98357A`), NFC-Anbindung, Bedien- und Lichtsignale

- [control_panel](../../hardware/electronics/control_panel/control_panel.kicad_sch)
  - separates Bedienpanel
  - `EC11` Drehencoder sowie Haupttaster wie `Button_Start`
  - eigene Produktionsdaten unter
    [production](../../hardware/electronics/control_panel/production)

- [LED_bar_long](../../hardware/electronics/LED_bar_long/LED_bar_long.kicad_sch)
  - aktuell gepflegte LED-Leiste fuer die Beleuchtung
  - Fertigungsdaten unter
    [production](../../hardware/electronics/LED_bar_long/production)

Aktueller Verdrahtungshinweis fuer den realen Scanneraufbau:

- die Beleuchtung wird jetzt getrennt links/rechts geschaltet
- `LED-left` haengt an einer MOSFET-Stufe auf `BCM12`
- `LED-right` haengt an einer MOSFET-Stufe auf `BCM13`

## Historischer Hinweis

Das fruehere Projekt `LED_bar_short` ist nicht mehr der aktive Pfad. Die aktuellen Arbeitsstaende liegen bei `LED_bar_long`, `control_panel` und `abr_pi5_header`.

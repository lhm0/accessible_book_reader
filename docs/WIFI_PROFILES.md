# Mehrere WLAN-Profile

Der Raspberry Pi verwendet NetworkManager fuer die WLAN-Verbindungen. Das
ABR-Werkzeug `abr.wifi_profiles` verwaltet deshalb keine eigene Passwortdatei,
sondern arbeitet mit den geschuetzten NetworkManager-Verbindungsprofilen.

Praktisch bestaetigter Stand am `2026-08-03`:

- Wechsel vom lokalen Router auf einen iPhone-Hotspot funktioniert
- Rueckwechsel ist auch ueber eine Raspberry-Pi-Connect-Sitzung moeglich
- das Hinzufuegen eines Profils ist vom eigentlichen Verbindungswechsel
  getrennt, damit die laufende SSH-Sitzung beim Speichern erhalten bleibt
- beim Boot und nach Verbindungsverlust kann NetworkManager aus allen
  gespeicherten, erreichbaren Profilen automatisch auswaehlen

## Profile anzeigen und hinzufuegen

```bash
cd ~/src/abr
sudo .venv/bin/python -m abr.wifi_profiles list
sudo .venv/bin/python -m abr.wifi_profiles add PROFILNAME TATSAECHLICHE_SSID
```

`add` fragt das WLAN-Passwort zuerst interaktiv ab und legt erst danach das
vollstaendige NetworkManager-Profil an. Damit liegen die Zugangsdaten bereits
vor, bevor die Aktivierung die bestehende SSH-Verbindung unterbrechen kann.
Das Passwort steht nicht in der Shell-History und wird nicht im Repository
gespeichert. Profilname und SSID duerfen verschieden sein. Namen mit
Leerzeichen muessen in Anfuehrungszeichen stehen.

Wichtig: Die Namen in dieser Anleitung sind Platzhalter. Befehle einzeln und
mit der tatsaechlichen SSID ausfuehren, nicht den gesamten Beispielblock
unveraendert in ein Terminal kopieren. `add` speichert das Profil nur und
veraendert die laufende Verbindung nicht. Eine sofortige Aktivierung ist mit
`--activate` moeglich, kann aber eine SSH-Sitzung unterbrechen.

Das vorhandene, bereits von NetworkManager gespeicherte WLAN muss nicht neu
angelegt werden. Einmalig werden alle vorhandenen WLAN-Profile fuer die
automatische Auswahl vorbereitet:

```bash
sudo .venv/bin/python -m abr.wifi_profiles configure
```

Dabei werden `connection.autoconnect=yes` und
`connection.autoconnect-retries=0` gesetzt. NetworkManager versucht damit
beim Boot und nach einem Verbindungsverlust dauerhaft, eines der erreichbaren
gespeicherten Netze zu verwenden.

## Profilname und SSID pruefen

Profilname und SSID sind nicht zwingend identisch. Die Profilnamen zeigt das
ABR-Werkzeug:

```bash
sudo .venv/bin/python -m abr.wifi_profiles list
```

Die SSID eines bestimmten Profils zeigt NetworkManager:

```bash
nmcli -g 802-11-wireless.ssid connection show "Example WiFi"
```

Alle Profile samt SSID:

```bash
nmcli -f NAME,TYPE,802-11-wireless.ssid connection show
```

Fuer `switch` muss der Profilname aus `abr.wifi_profiles list` exakt
uebernommen werden. Alternativ kann die dort angezeigte UUID verwendet werden.

## Manuell umschalten

```bash
sudo .venv/bin/python -m abr.wifi_profiles switch Mobil
```

Alternativ kann die automatische Auswahl aller gespeicherten Profile sofort
angestossen werden:

```bash
sudo .venv/bin/python -m abr.wifi_profiles auto
```

`add`, `switch` und `auto` werden innerhalb einer erkannten SSH-Sitzung
standardmaessig abgelehnt. Am sichersten werden sie mit Tastatur und Bildschirm
direkt am Pi ausgefuehrt. Soll die bestehende SSH-Sitzung bewusst geopfert
werden, steht die Freigabeoption vor dem Unterbefehl:

```bash
sudo .venv/bin/python -m abr.wifi_profiles --allow-ssh-disconnect switch Mobil
```

Die ABR-Runtime laeuft als systemd-Dienst unabhaengig von SSH weiter.

Wenn kein Bildschirm und keine Tastatur am Pi vorhanden sind, ist der
erprobte Ablauf:

1. neues Profil per SSH mit `add` speichern; die laufende Verbindung bleibt
   erhalten
2. mit `list` Profilname und UUID kontrollieren
3. Ziel-WLAN einschalten
4. mit `--allow-ssh-disconnect switch PROFILNAME` bewusst wechseln
5. Rechner ebenfalls mit dem Ziel-WLAN verbinden und per `abr.local`, IP oder
   Raspberry Pi Connect erneut auf den Pi zugreifen
6. fuer den Rueckwechsel den exakt angezeigten Namen des lokalen Profils
   verwenden

Sind mehrere Netze gleichzeitig erreichbar, kann beim Anlegen eine hoehere
Prioritaet angegeben werden:

```bash
sudo .venv/bin/python -m abr.wifi_profiles add Zuhause MeinWLAN --priority 20
sudo .venv/bin/python -m abr.wifi_profiles add Mobil MeinHotspot --priority 10
```

## Absicherung beim Boot

NetworkManager fuehrt Autoconnect selbst aus. Die zusaetzliche One-shot-Unit
stellt bei jedem Boot sicher, dass auch spaeter extern angelegte WLAN-Profile
Autoconnect und unbegrenzte Wiederholungen verwenden:

```bash
cd ~/src/abr
sudo deploy/install_wifi_autoconnect.sh
systemctl status abr-wifi-autoconnect.service --no-pager
```

Nach erfolgreichem Lauf ist `active (exited)` der erwartete Zustand. Kontrolle:

```bash
sudo .venv/bin/python -m abr.wifi_profiles list
nmcli connection show
nmcli device status
```

Der Installer setzt Benutzer-, Repository- und Pythonpfad passend zur lokalen
Installation in die systemd-Unit ein.

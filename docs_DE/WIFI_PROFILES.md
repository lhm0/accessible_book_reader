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
`connection.autoconnect-retries=1` gesetzt. Ein fehlerhaftes Profil soll
NetworkManagers automatische Auswahl nicht unbegrenzt blockieren. Die
dauerhafte Suche ueber alle Profile uebernimmt der unten beschriebene Dienst;
`configure` allein installiert diesen Dienst nicht.

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

Alle Profilnamen und Verbindungstypen (die SSID oben pro Profil abfragen):

```bash
nmcli -f NAME,TYPE connection show
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

`switch`, `auto`, `watch` und `add --activate` werden innerhalb einer erkannten
SSH-Sitzung standardmaessig abgelehnt. `add` ohne `--activate` bleibt erlaubt.
Vor einem Wechsel ohne Tastatur und Bildschirm den unten beschriebenen
Suchdienst installieren und seinen Status pruefen. Um den Verbindungswechsel
ueber SSH zu erlauben, steht die Freigabeoption vor dem Unterbefehl:

```bash
sudo .venv/bin/python -m abr.wifi_profiles --allow-ssh-disconnect switch Mobil
```

Die ABR-Runtime laeuft als systemd-Dienst unabhaengig von SSH weiter.

Wenn kein Bildschirm und keine Tastatur am Pi vorhanden sind, ist der
Ablauf mit installiertem Suchdienst:

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

## Dauerhafte Suche nach bekannten WLANs

Einmalig installieren, auch auf Geraeten mit der bisherigen Konfiguration:

```bash
cd ~/src/abr
sudo deploy/install_wifi_autoconnect.sh
```

Der Installer konfiguriert die gespeicherten Profile und installiert/startet
`abr-wifi-autoconnect.service` als Root-Dienst. Er startet bei jedem Boot,
unabhaengig vom Vorlesedienst und von SSH. Root ist fuer die nicht-interaktive
Aktivierung systemweiter NetworkManager-Profile erforderlich.

- Zwischen zwei Prueflaeufen liegen zehn Sekunden. Scan und Verbindungsversuch
  koennen den einzelnen Lauf verlaengern. Geprueft wird `wlan0`.
- Eine bestehende WLAN-Verbindung wird beibehalten, auch ohne Internetzugang.
- Ohne Verbindung wird ein Scan angestossen und ein gespeichertes Profil
  versucht. Nach einem Fehlschlag folgt das naechste Profil; nach dem letzten
  beginnt die Suche wieder von vorne, ohne Obergrenze.
- Die Wiederherstellung durchlaeuft die Profile in stabiler UUID-Reihenfolge.
  NetworkManagers eigene automatische Auswahl beruecksichtigt weiterhin
  die konfigurierten Prioritaeten.
- Ein Aktivierungsaufruf wartet maximal 45 Sekunden. Laufende Verbindungs-
  versuche von NetworkManager oder manuelle Wechsel erhalten bis zu 120 Sekunden
  Zeit, bevor die Suche das naechste Profil versucht. Ein nmcli-Timeout allein
  beendet nicht zwingend den Verbindungsversuch in NetworkManager.
- Spaeter hinzugefuegte oder geloeschte Profile werden beim naechsten Suchlauf
  beruecksichtigt. Es werden nur gespeicherte Profile aktiviert, keine
  unbekannten offenen WLANs neu angelegt.
- Auch nach einem fehlgeschlagenen `switch` oder erneutem Verbindungsverlust
  sucht der Dienst weiter. Fehler von NetworkManager werden erneut versucht;
  systemd startet einen abgestuerzten Suchdienst neu.

Voraussetzung sind ein eingeschaltetes, von NetworkManager verwaltetes
WLAN-Geraet und mindestens ein erreichbar werdendes Profil mit korrekten
Zugangsdaten. Bei gesperrtem oder fehlendem Adapter wird weiter geprueft,
aber keine Funk- oder Verwaltungssperre aufgehoben. Der Dienst prueft die
WLAN-Verbindung, nicht die Erreichbarkeit von Internetdiensten.

Kontrolle und Live-Log:

```bash
sudo systemctl status abr-wifi-autoconnect.service --no-pager
sudo journalctl -u abr-wifi-autoconnect.service -n 30 -f
```

Praktischer Geraetetest: Dienst installieren, Hotspot ausschalten und spaeter
wieder einschalten; der Pi soll sich ohne Eingriff erneut verbinden. Zusaetzlich
mit einem fehlerhaften Profil und einem erreichbaren korrekten Profil testen.
Die automatisierten Tests simulieren diese Situationen; sie ersetzen keinen
Funk- und DHCP-Test auf dem Raspberry Pi.

## Update einer bestehenden Installation

Nachdem der neue Code auf den Pi uebertragen wurde, den Installer erneut
aufrufen. Ein Git-Update allein installiert oder aktualisiert die systemd-Unit
nicht. Der Installer startet den Suchdienst neu; eine bestehende Verbindung
wird vom Suchdienst beibehalten.

```bash
cd ~/src/abr
sudo deploy/install_wifi_autoconnect.sh
systemctl is-enabled abr-wifi-autoconnect.service
systemctl is-active abr-wifi-autoconnect.service
```

Erwartete Ausgabe der letzten beiden Befehle: `enabled` und `active`.
Der Control-Panel-Dienst muss fuer diese Installation nicht gestoppt werden.
`--allow-ssh-disconnect` installiert keinen Dienst und ist selbst keine
Rueckschaltfunktion. Erst der installierte Suchdienst sorgt fuer die
fortgesetzten Versuche nach einem fehlgeschlagenen Wechsel.

## Fehler eingrenzen

```bash
nmcli device status
nmcli radio wifi
sudo .venv/bin/python -m abr.wifi_profiles list
sudo journalctl -u abr-wifi-autoconnect.service -b -n 100 --no-pager
sudo journalctl -u NetworkManager.service -b -n 100 --no-pager
```

| Beobachtung | Bedeutung / naechster Schritt |
|---|---|
| `Keine gespeicherten WLAN-Profile` | Mit `add` mindestens ein Profil speichern. |
| `WLAN-Geraet nicht bereit` | Adapter, Funkfreigabe und Verwaltung durch NetworkManager pruefen. |
| `WLAN-Verbindung fehlgeschlagen` | SSID, Passwort und Reichweite pruefen; der Suchdienst versucht weitere Profile. |
| `WLAN verbunden` | Die WLAN-Verbindung steht. Fehlender Internetzugang allein loest keinen Wechsel aus. |
| Dienst `inactive` oder `failed` | Dienstlog lesen und Installer erneut ausfuehren. |

Bei mehreren Profilen kann ein kompletter Durchlauf mehrere Minuten dauern.
Wenn kein gespeichertes Netz erreichbar ist, bleibt der Pi offline und sucht
weiter. Fuer erneuten SSH-Zugriff muss auch der Mac das verbundene Netz
ueber `abr.local` oder die aktuelle IP-Adresse erreichen koennen.

## Praxistest ohne Bildschirm

1. Suchdienst installieren und `enabled` / `active` kontrollieren.
2. Zwei erreichbare WLANs als Profile speichern und deren Zugangsdaten pruefen.
3. Das aktuell verbundene WLAN ausschalten. Der Pi soll selbst zum anderen
   gespeicherten Netz wechseln; den Mac fuer SSH gegebenenfalls ebenfalls wechseln.
4. Beide WLANs ausschalten, warten und eines wieder einschalten. Der Pi soll
   sich selbst verbinden, auch wenn vorher mehrere Suchrunden erfolglos waren.
5. Den Vorgang wiederholen, um die Wiederherstellung nach erneutem Verlust zu pruefen.
6. Optional ein separates Testprofil mit falschem Passwort anlegen und gezielt
   aktivieren. Ein korrektes erreichbares Profil muss danach weiterhin zum Zuge kommen.
7. Den Pi neu starten und pruefen, dass Suchdienst und WLAN automatisch starten.

Stand 2026-09-17: 24 automatisierte WLAN-Tests bestanden; der neue Suchdienst
ist noch nicht auf echter Raspberry-Pi-Hardware praktisch bestaetigt.

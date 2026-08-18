# Fernwartung per E-Mail

Stand: `2026-07-13`

## Zweck

Die E-Mail-Wartung ergaenzt SSH um zwei Dateiwege:

- `email_download DATEI` sendet eine lokale Datei immer an den in der lokalen
  `mail.ini` eingetragenen Wert `recipient`.
- Ein `systemd`-Timer prueft alle zwei Minuten noch nicht vom ABR verarbeitete
  E-Mails. Eine Mail von diesem konfigurierten Empfaenger mit dem Betreff
  `save PFAD/` und genau einem
  Anhang speichert den Anhang unter seinem Anhangsnamen im angegebenen Ordner.

Die Implementierung liegt in `abr/remote_mail.py` und verwendet nur die
Python-Standardbibliothek.

## Sicherheitsregeln

- Die Kontodaten liegen ausschliesslich in `~/.config/abr/mail.ini` mit Modus
  `0600`, nicht im Repository.
- Uploads werden nur vom exakten, lokal als `recipient` konfigurierten
  Absender angenommen.
- Die Mail muss genau einen Anhang enthalten.
- Das Zielverzeichnis muss bereits existieren. Der Dateiname wird aus dem
  Anhang uebernommen und darf selbst keinen Pfad enthalten.
- Eine vorhandene Datei wird atomar niemals ueberschrieben.
- Relative Uploadpfade beziehen sich auf das Home-Verzeichnis des Pi-Benutzers.
- Erfolgreich verarbeitete Upload-Mails werden nach dem sicheren Speichern des
  Anhangs aus dem IMAP-Postfach geloescht. Bereits durch ein anderes
  Mailprogramm gelesene Nachrichten werden ebenfalls erkannt.
  Verarbeitete IMAP-UIDs stehen in `~/.local/state/abr/mail_upload.json`.
  Fehlgeschlagene Mails werden nicht geloescht und beim naechsten Lauf erneut
  versucht, unabhaengig von ihrem Gelesen-Status.

E-Mail ist nicht Ende-zu-Ende-verschluesselt. Deshalb keine privaten
Schluessel, Passwoerter oder andere Geheimnisse auf diesem Weg uebertragen.

## Installation auf dem Raspberry Pi

Im aktuellen Projektpfad:

```bash
cd ~/src/abr
sudo deploy/install_remote_mail.sh
```

Beim ersten Lauf wird `~/.config/abr/mail.ini` aus
`deploy/mail.ini.example` angelegt. Die Datei mit Mailadresse, Empfaenger,
Benutzername, App-Passwort sowie den SMTP-/IMAP-Daten des eigenen Anbieters
ausfuellen und denselben Installationsbefehl erneut starten. Die echten Werte
bleiben ausserhalb des Repositorys; die Datei hat Modus `0600`. Viele Anbieter
verlangen fuer diesen Zweck ein separates App-Passwort. SMTP und IMAP werden
mit SSL/TLS verwendet.

Der Installer erzeugt:

- `/usr/local/bin/email_download`
- `/etc/systemd/system/abr-email-upload.service`
- `/etc/systemd/system/abr-email-upload.timer`

## Benutzung

Download vom Pi:

```bash
cd ~/src/abr/captures/latest/raw
email_download cam0_raw.jpg
```

Upload zum Pi, absolute Variante:

```text
Betreff: save ~/src/abr/
Anhang: example.txt
```

Relative Variante, bezogen auf `~`:

```text
Betreff: save src/abr/
Anhang: example.txt
```

Wichtig: In das Betreff-Feld wird nur `save ...` eingetragen. Die
Beschriftung `Betreff:` ist nicht Teil des eigentlichen Mailbetreffs.

## Pruefung und Diagnose

```bash
email_download --help
systemctl status abr-email-upload.timer
sudo systemctl start abr-email-upload.service
journalctl -u abr-email-upload.service -n 50 --no-pager
```

Eine bereits vorhandene Zieldatei fuehrt absichtlich zu einem Fehler. Nach
dem Entfernen oder Umbenennen der Zieldatei kann die weiterhin vorhandene Mail
beim naechsten Lauf verarbeitet werden.

# Herkunft der System-Audiodateien

Die Audioausgaben in den Sprachunterordnern wurden aus projekteigenen kurzen
Systemtexten mit Google Cloud Text-to-Speech erzeugt. Zur Erzeugung dient das
Repository-Skript `hardware/generate_audio_message.py`; sein Standard-Backend
ist Google Cloud TTS. Die Dateien sind keine menschlichen Sprachaufnahmen und
enthalten keine aus einem fremden Audiowerk uebernommenen Aufnahmen.

Ausnahme ist das sprachneutrale Umblättersignal `tatata.wav` in den beiden
Sprachordnern. Es wurde separat als MP3 bereitgestellt und als unkomprimiertes
WAV mit PCM 16 Bit, Mono und 24000 Hz konvertiert; es wurde nicht mit Google
Cloud TTS erzeugt. Vor einer Weitergabe muss deshalb unabhaengig von diesem
Google-TTS-Hinweis sichergestellt sein, dass die erforderlichen Rechte an der
bereitgestellten Ausgangsaufnahme vorliegen.

Google dokumentiert, dass mit Cloud Text-to-Speech erzeugte Audiodateien in
Anwendungen sowie in Audio- und Videomedien verwendet werden duerfen, sofern
die Google-Cloud-Bedingungen und das anwendbare Recht eingehalten werden:

https://cloud.google.com/text-to-speech/docs/basics

In der geprueften Produktdokumentation ist keine Pflicht zur Namensnennung fuer
die erzeugte Audiodatei genannt. Dieser Herkunftshinweis dient deshalb der
Transparenz und ist keine dort verlangte Namensnennung. Er bedeutet auch nicht,
dass Google das Projekt unterstuetzt oder freigegeben hat. Fuer eine erneute
Synthese gelten die jeweils aktuellen Google-Cloud-Nutzungsbedingungen des
verwendeten Kontos.

Die vom Projekt verfassten Systemtexte sowie die projekteigene Auswahl und
Anordnung werden unter `CC-BY-SA-4.0` bereitgestellt. Soweit an rein
synthetischer Sprachausgabe nach dem jeweils anwendbaren Recht keine eigenen
Urheberrechte entstehen, erhebt das Projekt daran keine weitergehenden
Exklusivrechte. Die vollstaendige Lizenzabgrenzung steht in der
Repository-Datei `LICENSE.md`.

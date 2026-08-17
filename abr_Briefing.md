# Briefing für CODEX — Projekt „Accessible Book Reader (ABR)“

## Projektziel

Entwicklung eines Systems zum sehr einfachen Einscannen und Vorlesen von Büchern.

Das Buch wird **aufgeschlagen mit der bedruckten Seite nach unten** auf zwei geneigte Glasflächen gelegt. Die Konstruktion ähnelt einem Zelt („BookTent“). Unter jeder Glasfläche befindet sich später eine Kamera. Jede Seite wird separat fotografiert.

Ziel ist **nicht primär PDF-Erzeugung**, sondern:

1. zuverlässige Texterkennung (OCR)
2. Strukturierung des Textes
3. intelligente Seitenverknüpfung
4. Ausgabe als Sprache (Text-to-Speech)

Das System soll insbesondere für Belletristik funktionieren.

---

# Projektstrategie

Das größte Projektrisiko ist die Qualität der OCR-/Layout-Auswertung.

Deshalb wird zunächst **nur die Software-Pipeline entwickelt und getestet**, ohne spezielle Hardware.

## Phase 1: Software-Prototyp

Die ersten Tests erfolgen mit:

- einfachen Smartphone-Fotos
- simulierten Buchseiten
- manuell aufgenommenen Bildern

Erst wenn die OCR-/Strukturerkennung zuverlässig funktioniert, wird die Hardware entwickelt.

---

# Zielplattform

## Entwicklungsumgebung

- VS Code
- Python 3.11+
- Linux/macOS bevorzugt
- später Raspberry Pi 5

## Zielhardware (später)

- Raspberry Pi 5
- 2 × ESP32
- 2 × Kameramodule
- LED-Blitzbeleuchtung
- Lautsprecher

Die ESP32 sollen später nur:

- Kamera auslösen
- Blitz synchronisieren
- Bild übertragen

Die gesamte Bildauswertung läuft auf dem Raspberry Pi.

---

# Geometrie des späteren Geräts

## Mechanik

Das Buch liegt:

- aufgeschlagen
- mit den bedruckten Seiten nach unten
- auf zwei geneigten Glasflächen

Die Form entspricht einem Dach/Zelt.

## Typische Buchgröße

Optimierung auf Belletristik:

- Taschenbücher
- normale Hardcover

Empfohlene Glasfläche pro Seite:

- ca. 160 × 240 mm

---

# Anforderungen an die Software

# 1. Bildaufnahme

Das System soll zwei Bilder verarbeiten:

- linke Seite
- rechte Seite

Im Prototyp stammen diese Bilder zunächst von Smartphone-Fotos.

Später kommen sie von zwei Kameras.

---

# 2. Bildvorverarbeitung

Notwendige Schritte:

## Rotationserkennung

Das Buch kann in beiden Richtungen aufgelegt werden.

Die Software muss erkennen:

- welche Seite oben/unten ist
- ob 180° Rotation notwendig ist

## Bildoptimierung

- Graustufen
- Kontrastverbesserung
- adaptive Thresholds
- Schärfung
- Rauschreduzierung

Verwendbare Bibliotheken:

- OpenCV
- NumPy

---

# 3. OCR

Ziel:

- möglichst fehlerfreie Texterkennung
- zunächst deutschsprachige Bücher (später auch Englisch)
- Belletristik
- robuste Verarbeitung typischer Druckschrift

## OCR-Optionen

Die Architektur soll austauschbar sein.

Es sollen mindestens folgende OCR-Backends testbar sein:

### Option A — Tesseract

Vorteile:

- lokal
- stabil
- leichtgewichtig
- schnell

Nachteile:

- begrenzte Layoutanalyse

Bibliotheken:

- pytesseract
- tesseract-ocr-deu

---

### Option B — PaddleOCR

Vorteile:

- moderne Deep-Learning-OCR
- gute Layoutanalyse
- Orientation Detection
- Struktur-Erkennung

Soll bevorzugt getestet werden.

---

### Option C — docTR

Optional evaluieren.

---

# 4. Layout-/Strukturerkennung

Sehr wichtig.

Das System soll erkennen:

- Seitenzahlen
- Kapitelüberschriften
- Absätze
- Leerzeilen
- Kapitelwechsel

Ziel:

Die spätere Sprachausgabe soll natürlich wirken.

## Wichtiger Spezialfall

Ein Satz kann über zwei Seiten gehen.

Beispiel:

Seite 10 endet mit:

„Er öffnete langsam die Tür und“

Seite 11 beginnt mit:

„blickte in den dunklen Raum.“

Das System darf NICHT den unvollständigen Satz sprechen.

Stattdessen:

- Satz puffern
- nächste Seite abwarten
- Satz zusammenführen
- erst dann ausgeben

Dafür wird eine Textstruktur benötigt.

---

# 5. Satzsegmentierung

Benötigt:

- Satzende-Erkennung
- Erkennung unvollständiger Sätze
- Absatzgrenzen

Mögliche Bibliotheken:

- spaCy (deutsch)
- NLTK
- einfache heuristische Regeln

---

# 6. Seitenreihenfolge

Das System muss robust arbeiten bei:

- links/rechts vertauscht
- 180° Rotation
- unterschiedlicher Reihenfolge der Bilder

---

# 7. Text-to-Speech (TTS)

Der erkannte Text soll vorgelesen werden.

## Erste Zielsetzung

Lokale TTS-Lösung.

## Optionen

### Piper TTS (bevorzugt)

- gute Qualität
- lokal
- Raspberry Pi geeignet

### eSpeak NG

- fallback
- leichtgewichtig

---

# Softwarearchitektur

Die Architektur soll modular sein.

## Vorschlag

project/
│
├── input/
├── preprocessing/
├── orientation/
├── layout/
├── ocr/
├── text_logic/
├── tts/
├── tests/
└── run_fallback_pipeline.py

---

# Erwartete Pipeline

## Schritt 1

Lade zwei Bilder.

## Schritt 2

Vorverarbeitung.

## Schritt 3

Orientierung erkennen.

## Schritt 4

OCR durchführen.

## Schritt 5

Layout analysieren.

## Schritt 6

Textblöcke in Lesereihenfolge bringen.

## Schritt 7

Sätze zusammenführen.

## Schritt 8

Unvollständige Sätze puffern.

## Schritt 9

Text an TTS ausgeben.

---

# Ziel der ersten Entwicklungsphase

Zunächst KEINE GUI.

CLI genügt.

Beispiel:

```bash id="t2xrq9"
python run_fallback_pipeline.py left.jpg right.jpg
```

Ausgabe:

- erkannter Text
- Strukturinformationen
- erkannte Kapitel
- Debug-Bilder
- optionale Sprachausgabe

---

# Wichtige Entwicklungsziele

## Priorität 1

OCR-Qualität evaluieren.

## Priorität 2

Layout-/Struktur-Erkennung.

## Priorität 3

Satzfortsetzung über Seiten hinweg.

## Priorität 4

Robustheit gegen schlechte Bilder.

---

# Debug-/Analysefunktionen

Sehr wichtig.

Das System soll:

- Zwischenbilder speichern
- OCR-Konfidenzen anzeigen
- erkannte Layoutregionen visualisieren
- Rotation anzeigen
- erkannte Textblöcke markieren

---

# Empfohlene Bibliotheken

## Pflicht

- OpenCV
- NumPy
- Pillow

## OCR

- PaddleOCR
- pytesseract

## NLP

- spaCy (de_core_news_sm)

## TTS

- piper
- espeak-ng

---

# Anforderungen an CODEX

Zunächst soll der Code lokal auf einem Mac lauffähig sein. Später wird er dann auf den Raspberry Pi 5 portiert.

Bitte:

1. eine saubere modulare Python-Architektur erzeugen
2. austauschbare OCR-Backends vorsehen
3. Testbilder einfach integrierbar machen
4. Debugging stark unterstützen
5. zunächst auf lokale Verarbeitung optimieren
6. Raspberry-Pi-Kompatibilität beachten
7. keine unnötig komplexe Infrastruktur verwenden

---

# Erste konkrete Aufgabe für CODEX

Implementiere einen ersten Prototypen mit:

- Bild laden
- Vorverarbeitung
- Rotationserkennung
- OCR
- einfache Absatz-/Satzsegmentierung
- Konsolenausgabe
- optionaler TTS-Ausgabe

Nutze zunächst PaddleOCR und OpenCV.

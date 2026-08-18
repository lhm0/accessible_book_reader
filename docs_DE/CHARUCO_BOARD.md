# ChArUco Board

Stand: `2026-06-26`

## Zweck

Dieses Werkzeug erzeugt ein druckbares `ChArUco`-Board fuer die Kamera-Kalibrierung.

Datei:

- [calibration/generate_charuco_board.py](../calibration/generate_charuco_board.py)

## Empfohlener Pfad Fuer ABR

Fuer die aktuellen `IMX519`-Kameras mit `140 Grad`-Weitwinkel ist ein `ChArUco`-Board der beste pragmatische Kalibrierpfad:

- robuster bei starker Verzeichnung als ein reines Checkerboard
- gute Eckdetektion auch bei teilweiser Sichtbarkeit
- spaeter gut automatisierbar mit `OpenCV`

Der aktuelle Standard fuer ABR ist:

- Boardgroesse: `160 x 240 mm`
- Schachbrettfelder: `8 x 12`
- Feldgroesse: `20 x 20 mm`
- Markerlaenge: `14 mm`
- Dictionary: `DICT_5X5_50`

Der erzeugte Referenzsatz liegt aktuell bereits unter:

- `calibration/out/charuco_160x240.png`
- `calibration/out/charuco_160x240_a4.svg`
- `calibration/out/charuco_160x240.json`

Diese Kombination fuellt die Zielgroesse exakt aus:

- `160 / 8 = 20 mm`
- `240 / 12 = 20 mm`

## Vorbereitung

In der lokalen `venv` auf dem Mac:

```bash
cd ~/src/abr
source .venv/bin/activate
pip install opencv-contrib-python numpy
```

Wichtig:

- `opencv-python` reicht nicht, weil `cv2.aruco` dort meist fehlt
- benoetigt wird `opencv-contrib-python`

## Erzeugung Fuer 160 x 240 mm

```bash
python calibration/generate_charuco_board.py \
  --output-prefix calibration/out/charuco_160x240
```

Das Skript schreibt:

- `calibration/out/charuco_160x240.png`
- `calibration/out/charuco_160x240_a4.svg`
- `calibration/out/charuco_160x240.json`

Die aktuellen Kalibrierbilder im Repo verwenden genau dieses Board:

- `calibration/shots/cam0_charuco_01.jpg`
- `calibration/shots/cam1_charuco_01.jpg`

## Bedeutung Der Ausgaben

- `PNG`: reine Rastergrafik des Boards
- `A4-SVG`: druckfertige Seite mit exakt zentriertem `160 x 240 mm`-Board
- `JSON`: Boardparameter fuer spaetere Kalibrierung und Dokumentation

## Druckhinweis

Die SVG sollte:

- auf `100%`
- ohne `An Seite anpassen`
- ohne automatische Skalierung

gedruckt werden.

Danach mit einem Lineal nachmessen:

- Gesamtbreite des Boards: `160 mm`
- Gesamthoehe des Boards: `240 mm`
- ein einzelnes Schachbrettfeld: `20 mm`

Wenn diese Masse nicht stimmen, ist der Ausdruck fuer eine saubere Kalibrierung ungeeignet.

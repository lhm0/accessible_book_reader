# Manual Undistort

Stand: `2026-06-26`

## Zweck

Dieses Werkzeug entzerrt ein einzelnes Bild mit manuell uebergebenen Kameraparametern. Im aktuellen Projektstand ist es nur noch ein Fallback- und Vergleichswerkzeug, nicht mehr der bevorzugte Kalibrierpfad.

Datei:

- [calibration/manual_undistort.py](../calibration/manual_undistort.py)

## Rolle Im Aktuellen Projektstand

Das Skript ist bewusst kein Kalibrierwerkzeug.

Es nimmt stattdessen:

- Kameramatrix `K`
- Distortion-Koeffizienten
- Modellwahl `fisheye` oder `standard`

und schreibt daraus eine entzerrte Bilddatei.

Damit kannst du am Mac Werte schrittweise variieren und die Wirkung direkt vergleichen.

Bevorzugter aktueller Projektpfad fuer die Pi-Kameras ist stattdessen:

- `ChArUco`-Board erzeugen: [docs/CHARUCO_BOARD.md](../docs/CHARUCO_BOARD.md)
- feste Remap aus Kalibrierbild berechnen: [docs/PLANAR_CHARUCO_REMAP.md](../docs/PLANAR_CHARUCO_REMAP.md)

## Vorbereitung Am Mac

Im Repo:

```bash
cd ~/src/abr
source .venv/bin/activate
```

Falls `opencv-python` in der lokalen `venv` noch fehlt:

```bash
pip install opencv-python numpy
```

## Empfehlung Fuer Dein Objektiv

Fuer ein `140 Grad`-Weitwinkelobjektiv ist zuerst das `fisheye`-Modell sinnvoll.

Verwende dort:

- `fx`
- `fy`
- `cx`
- `cy`
- `k1,k2,k3,k4`

## Beispielaufrufe

### Fisheye-Modell

```bash
python calibration/manual_undistort.py \
  --input calibration/test_input.jpg \
  --output calibration/out/fisheye_try_01.jpg \
  --model fisheye \
  --fx 2200 \
  --fy 2200 \
  --cx 2328 \
  --cy 1748 \
  --dist "0.08,-0.03,0.005,-0.001" \
  --balance 0.2
```

### Standardmodell

```bash
python calibration/manual_undistort.py \
  --input calibration/test_input.jpg \
  --output calibration/out/standard_try_01.jpg \
  --model standard \
  --fx 2200 \
  --fy 2200 \
  --cx 2328 \
  --cy 1748 \
  --dist "-0.25,0.12,0.0,0.0,-0.03" \
  --alpha 0.0
```

## Parameterhinweise

### Kameramatrix

- `fx`, `fy`: effektive Brennweiten in Pixel
- `cx`, `cy`: optisches Zentrum in Pixel

Pragmatischer Startwert fuer eine `4656x3496`-Aufnahme:

- `cx = 2328`
- `cy = 1748`

also erst einmal Bildmitte annehmen.

### Fisheye

- `dist` erwartet genau `k1,k2,k3,k4`
- `balance = 0.0`
  - mehr Beschnitt
  - meist geradliniger
- `balance = 1.0`
  - mehr Sichtfeld
  - eher mehr Randreste

### Standardmodell

- `dist` erwartet genau `k1,k2,p1,p2,k3`
- `alpha = 0.0`
  - maximaler Beschnitt auf brauchbaren Bereich
- `alpha = 1.0`
  - mehr Rand, mehr schwarze Flaechen moeglich

## Praktischer Workflow

1. Ein Testbild nach `calibration/` legen
2. Mit `fisheye` starten
3. `cx` und `cy` zunaechst auf Bildmitte setzen
4. zuerst nur `k1` und `k2` grob variieren
5. danach `k3` und `k4` feinjustieren
6. `balance` so einstellen, dass du einen brauchbaren Kompromiss aus Randbeschnitt und Geradlinigkeit bekommst

## Vorschlag Fuer Erste Versuche

Fuer starke Tonnenverzeichnung mit Fisheye-Modell koennen diese Startwerte als reine Naeherung helfen:

- `fx = 1800` bis `2600`
- `fy = 1800` bis `2600`
- `k1 = 0.02` bis `0.20`
- `k2 = -0.20` bis `0.05`
- `k3 = -0.05` bis `0.05`
- `k4 = -0.02` bis `0.02`

Das sind bewusst nur Suchbereiche, keine Kalibrierwerte.

## Optional Fuer Schnellere Vergleiche

Wenn du nur schnell Varianten vergleichen willst:

```bash
python calibration/manual_undistort.py \
  --input calibration/test_input.jpg \
  --output calibration/out/preview.jpg \
  --model fisheye \
  --fx 2200 \
  --fy 2200 \
  --cx 2328 \
  --cy 1748 \
  --dist "0.08,-0.03,0.005,-0.001" \
  --balance 0.2 \
  --preview-width 1600
```

Dann wird nur die Ausgabedatei zum schnelleren visuellen Vergleich verkleinert.

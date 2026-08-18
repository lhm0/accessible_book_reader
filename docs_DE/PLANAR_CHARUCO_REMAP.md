# Planar ChArUco Remap

Stand: `2026-06-26`

## Zweck

Dieses Werkzeug erzeugt aus genau einem `ChArUco`-Kalibrierbild eine glatte Vollbild-Entzerrung fuer eine starre Kamera.

Dateien:

- [calibration/calibrate_planar_charuco.py](../calibration/calibrate_planar_charuco.py)
- [calibration/apply_saved_remap.py](../calibration/apply_saved_remap.py)

## Wann Dieser Pfad Sinnvoll Ist

Dieser Pfad ist fuer ABR dann besser als eine klassische Mehrbild-Kamerakalibrierung, wenn:

- die Kamera mechanisch starr bleibt
- der Kameraaufbau spaeter nicht mehr veraendert wird
- aus einem einzelnen Referenzbild eine praktikable Vollbild-Entzerrung benoetigt wird

Das passt zum Scanner-Aufbau mit fester Kamera besser als der fruehere stueckweise Planar-Warp.

Der aktuell verifizierte Projektstand ist:

- `cam0` und `cam1` sind mechanisch justiert
- beide Kameras besitzen eine gespeicherte aktuelle Remap
- diese Remaps sind die bevorzugte Basis fuer reale Scannerbilder

## Prinzip

Das Skript:

1. erkennt `ArUco`-Marker und `ChArUco`-Ecken im Kalibrierbild
2. bestimmt daraus ein globales Kameramodell mit radialer Verzeichnung
3. entzerrt das ganze Bild glatt mit `OpenCV`
4. richtet optional die Bildebene perspektivisch zu einem echten Rechteck aus
5. schreibt die gespeicherte Remap und die Vorschau

Der wichtige Unterschied:

- kein stueckweiser Dreiecks-Warp
- keine lokalen Knicke zwischen Kontrollpunkten
- die Zwischenraeume werden genauso glatt entzerrt wie die Marker selbst
- die verbleibende Trapezform des schraeg aufgenommenen Plans kann zusaetzlich entfernt werden

## Voraussetzungen

Auf dem Mac in der lokalen `venv`:

```bash
cd ~/src/abr
source .venv/bin/activate
pip install opencv-contrib-python numpy
```

## Remap Aus Einem Kalibrierbild Erzeugen

Beispiel fuer das bereits aufgenommene Bild `cam1_charuco_01.jpg`:

```bash
python calibration/calibrate_planar_charuco.py \
  --image calibration/shots/cam1_charuco_01.jpg \
  --board-json calibration/out/charuco_160x240.json \
  --output-prefix calibration/out/cam1_planar \
  --alpha 1.0 \
  --preview-width 1600
```

Das Skript schreibt:

- `calibration/out/cam1_planar.npz`
- `calibration/out/cam1_planar.json`
- `calibration/out/cam1_planar_rectified.jpg`
- `calibration/out/cam1_planar_detected.jpg`

Analoger Aufruf fuer `cam0`:

```bash
python calibration/calibrate_planar_charuco.py \
  --image calibration/shots/cam0_charuco_01.jpg \
  --board-json calibration/out/charuco_160x240.json \
  --output-prefix calibration/out/cam0_planar \
  --alpha 1.0 \
  --preview-width 1600
```

Wenn du weniger schwarze Randflaechen willst und dafuer mehr beschneiden akzeptierst:

```bash
python calibration/calibrate_planar_charuco.py \
  --image calibration/shots/cam1_charuco_01.jpg \
  --board-json calibration/out/charuco_160x240.json \
  --output-prefix calibration/out/cam1_planar \
  --alpha 0.0 \
  --crop-valid
```

Wenn du nur die Linsenentzerrung willst und die Perspektive bewusst nicht begradigen willst:

```bash
python calibration/calibrate_planar_charuco.py \
  --image calibration/shots/cam1_charuco_01.jpg \
  --board-json calibration/out/charuco_160x240.json \
  --output-prefix calibration/out/cam1_planar \
  --no-perspective-rectify
```

## Remap Auf Ein Bild Anwenden

```bash
python calibration/apply_saved_remap.py \
  --input calibration/shots/cam1_charuco_01.jpg \
  --remap calibration/out/cam1_planar.npz \
  --output calibration/out/cam1_charuco_01_rectified.jpg
```

Beispiel fuer einen realen Scan von `cam0`:

```bash
python calibration/apply_saved_remap.py \
  --input testdata/scans0/cam0_0001.jpg \
  --remap calibration/out/cam0_planar.npz \
  --output testdata/scans0/cam0_0001_rectified.jpg
```

Wenn die angegebene Remap-Datei noch nicht existiert, erzeugt `apply_saved_remap.py` sie jetzt automatisch, sofern:

- das passende Kalibrierbild vorhanden ist, z. B. `calibration/shots/cam0_charuco_01.jpg`
- das Board-JSON vorhanden ist oder automatisch als `charuco_160x240.json` erzeugt werden kann

Damit reicht fuer den Standardpfad oft direkt:

```bash
python calibration/apply_saved_remap.py \
  --input testdata/scans0/cam0_0001.jpg \
  --remap calibration/out/cam0_planar.npz \
  --output testdata/scans0/cam0_0001_rectified.jpg
```

Explizites Kalibrierbild bleibt optional moeglich:

```bash
python calibration/apply_saved_remap.py \
  --input testdata/scans0/cam0_0001.jpg \
  --remap calibration/out/cam0_planar.npz \
  --output testdata/scans0/cam0_0001_rectified.jpg \
  --calibration-image calibration/shots/cam0_charuco_01.jpg
```

## Hinweise

- das `ChArUco`-Board sollte moeglichst plan sein
- der Kameraaufbau darf nach der Kalibrierung nicht mehr veraendert werden
- wenn spaeter Fokus, Kamerawinkel oder Hoehe geaendert werden, muss die Remap neu erzeugt werden
- die Remap gilt fuer diese Kamera und diesen mechanischen Aufbau
- aktuelle Remaps:
  - `calibration/out/cam0_planar.npz`
  - `calibration/out/cam1_planar.npz`

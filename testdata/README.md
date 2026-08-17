# Testdata

Dieser Ordner enthaelt im Repository absichtlich keine realen Buchseiten.
Lokale Testbilder werden durch `.gitignore` ausgeschlossen, weil Bilder und
OCR-Inhalte aktueller Buecher in der Regel urheberrechtlich geschuetzt sind.
Nur selbst erstellte, gemeinfreie oder fuer eine Veroeffentlichung eindeutig
freigegebene Testvorlagen duerfen ausnahmsweise versioniert werden.

Lege hier reale Testfaelle ab. Empfohlene Struktur:

```text
testdata/
  roman_001/
    left.jpg
    right.jpg
```

Alternativ funktionieren auch die ersten beiden Bilddateien im Ordner. Die Namen `left.*` und `right.*` sind aber fuer reproduzierbare Tests empfohlen.

Fuer reale Scannerbilder ist eine getrennte Ablage pro Kamera sinnvoll, z. B.:

```text
testdata/
  scans0/
    cam0_0001.jpg
    cam0_0001_rectified.jpg
  scans1/
    cam1_0001.jpg
    cam1_0001_rectified.jpg
```

Empfohlene Konvention:

- rohe Aufnahme: `cam0_0001.jpg`, `cam1_0001.jpg`
- mit gespeicherter Remap entzerrt: `cam0_0001_rectified.jpg`, `cam1_0001_rectified.jpg`

Die aktuell dokumentierten Remaps liegen unter:

- `calibration/out/cam0_planar.npz`
- `calibration/out/cam1_planar.npz`

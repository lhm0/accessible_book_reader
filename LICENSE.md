# Licensing

Copyright (c) 2026 Ludwin Monz

The Accessible Book Reader (`ABR`) is a multi-licensed project. Different
parts of the repository are licensed according to their purpose. No license
granted here changes or replaces the license of third-party material.

Where categories overlap, the licence follows the nature of the material:
executable source code and code examples are software under the GPL; editable
hardware design sources are under CERN-OHL-S; explanatory prose, illustrations
and project-owned media are under CC BY-SA. A file-specific notice takes
precedence over these defaults.

## Software: GPL-3.0-or-later

Unless a file or directory carries a different notice, software written for
this project is licensed under the GNU General Public License, version 3 or
any later version (`GPL-3.0-or-later`). This includes in particular:

- `abr/`
- `hardware/*.py`
- `calibration/*.py`
- `deploy/`
- `tests/`
- the project-owned firmware in `hardware/pn5180_gateway/src/` and
  `hardware/pn532_gateway/src/`
- other project-owned scripts and software configuration files

You may use, modify and distribute that software under the terms of the GPL.
If you convey modified versions or binaries, the GPL's corresponding-source
and copyleft requirements apply.

Full license text: [`LICENSES/GPL-3.0-or-later.txt`](LICENSES/GPL-3.0-or-later.txt)

Official source: https://www.gnu.org/licenses/gpl-3.0.html

SPDX identifier: `GPL-3.0-or-later`

## Hardware designs: CERN-OHL-S-2.0

Project-owned hardware design sources and their project-owned manufacturing
outputs are licensed under the CERN Open Hardware Licence Version 2 -
Strongly Reciprocal (`CERN-OHL-S-2.0`). This includes:

- `hardware/electronics/`
- `hardware/mechanics/`
- `pn5180_qusc/`

The preferred source is the editable KiCad, CAD or simulation source, not
merely a generated fabrication archive or mesh export. When the licence
requires Complete Source, all files needed to modify and make the relevant
design must be provided.

Full license text: [`LICENSES/CERN-OHL-S-2.0.txt`](LICENSES/CERN-OHL-S-2.0.txt)

Official source: https://cern-ohl.web.cern.ch/home

SPDX identifier: `CERN-OHL-S-2.0`

## Documentation and project-owned media: CC BY-SA 4.0

Project documentation is licensed under the Creative Commons
Attribution-ShareAlike 4.0 International licence (`CC-BY-SA-4.0`). This
includes:

- `readme.md`, `readme_DE.md`, `abr_Briefing.md` and other project-authored Markdown files
- `docs/`
- project-authored README files below `hardware/` and `testdata/`
- project-owned texts, selection and arrangement embodied in the generated
  audio in `system_audio/messages/`, to the extent copyright or similar rights
  apply; see the provenance notice in that directory
- project-owned calibration-board artwork and project-owned calibration
  photographs

Attribution should name "Ludwin Monz, Accessible Book Reader" and link to the
repository. Adaptations must be shared under CC BY-SA 4.0 as required by that
licence.

Full license text: [`LICENSES/CC-BY-SA-4.0.txt`](LICENSES/CC-BY-SA-4.0.txt)

Official source: https://creativecommons.org/licenses/by-sa/4.0/legalcode

SPDX identifier: `CC-BY-SA-4.0`

## Material not covered by the project licences

The licences above apply only where Ludwin Monz owns the necessary rights.
They do not license third-party book pages, OCR reproductions of third-party
texts, vendor files, trademarks, or other material for which the repository
does not establish project ownership. In particular, locally created files
below `testdata/` and `pi_timings/` are not covered by the CC BY-SA grant
unless a file-specific notice says otherwise. Such local book images and OCR
artefacts are excluded from version control.

## Third-party components

Third-party components remain under their original licences:

- `hardware/pn5180_gateway/lib/PN5180_Library_Minimal/` is licensed under
  `LGPL-2.1-or-later`; see the licence and source headers in that directory.
- `hardware/pn532_gateway/lib/Seeed_Arduino_NFC_Minimal/` is licensed under
  `BSD-3-Clause`; see the licence in that directory.
- External Python packages, OCR models, operating-system packages and build
  tools are not relicensed by this repository. Their own terms apply.

Copyright and attribution notices in third-party files must be retained.
Further attribution and upstream information is collected in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Contributions and commercial licensing

Contributions are accepted only under the terms described in
`CONTRIBUTING.md` and the Contributor License Agreement in `CLA.md`. The CLA
keeps contributors' ownership while granting the project maintainer the right
to publish contributions under the public project licences and under separate
commercial terms.

The public licences remain valid and permit commercial use according to their
terms. Separate commercial arrangements, support, development cooperation or
alternative licensing may be offered by the copyright holders. Contact the
project maintainer through the repository for such arrangements.

## No warranty

Each component is provided without warranty to the extent permitted by its
applicable licence and by law.

## Patents and other third-party rights

No patent or professional freedom-to-operate search has been performed. The
licences apply only to rights that the respective licensor is entitled to
grant and do not assure non-infringement of unrelated third-party rights.
See [PATENT_NOTICE.md](PATENT_NOTICE.md) before making, using or distributing
the project, especially for commercial purposes.

# Usage Statistics

Last reviewed: `2026-08-07`

Deutsche Fassung: [Nutzerstatistik](../docs_DE/USAGE_STATISTICS.md)

## Purpose and Reporting Period

The device runtime records usage per book. In the `Europe/Berlin` time zone,
a reporting day starts at `04:00` and ends immediately before `04:00` the
following day.

The following values are recorded for each book:

- number of successfully ingested pages
- actual playback duration of page and summary audio
- number of chapter/latest-pages summary requests
- number of story-so-far summary requests

System prompts and signal sounds such as `bing.wav` do not count as reading
time. During incremental processing, the same page artifact may be reported
more than once; `scan_id` and `page_id` ensure that it is counted only once
within a reporting period. A new scan of the same book page counts again.

## Storage and Failure Safety

The current state is stored in:

```text
library/usage_statistics/current.json
```

Access from audio and ingest threads, as well as from the reporting process,
is serialized with a thread lock and file lock. The JSON file is replaced
atomically. Statistics errors are logged but do not interrupt the device's
primary function.

At `04:00`, `abr-usage-report.timer` starts the one-shot
`abr-usage-report.service`. It sends every completed reporting period that has
not yet been delivered to the recipient configured in `mail.ini`. A period is
removed from `current.json` and stored under the following path only after a
successful SMTP delivery:

```text
library/usage_statistics/archive/YYYY-MM-DD.json
```

Since the `2026-08-07` version, a report is sent for every completed period,
even when the device was not used. Such a report contains
`Keine Nutzung erfasst.` and totals of zero. Empty periods also receive an
archive file after successful delivery, preventing the same zero-usage report
from being sent again by a second manual service run. After the device has
been off for several days, periods that have not yet been archived are caught
up in chronological order.

If delivery fails or the Pi is switched off at `04:00`, the data is retained.
With `Persistent=true`, systemd catches up on the missed run; a later run still
sends every outstanding completed period.

## Installation on the Raspberry Pi

Prerequisites:

- the project is located at `~/src/abr`
- the virtual environment `~/src/abr/.venv` exists
- the existing mail account is configured in `~/.config/abr/mail.ini`
- the current project version has been transferred to the Pi

Install:

```bash
cd ~/src/abr
timedatectl status
sudo deploy/install_usage_statistics.sh
```

`Time zone` must show `Europe/Berlin`. Otherwise, set it with:

```bash
sudo timedatectl set-timezone Europe/Berlin
```

The installer substitutes the current user and the repository, Python,
library, and mail-configuration paths into the unit, installs both systemd
files, and enables the timer immediately.

Then restart the control-panel service so the runtime uses the new counters:

```bash
sudo systemctl restart abr-control-panel.service
```

Inspect the timer:

```bash
systemctl status abr-usage-report.timer
systemctl list-timers abr-usage-report.timer
```

## Manual Test

As soon as usage data exists, a preview e-mail can be sent immediately. It
does not change or archive the current counters:

```bash
cd ~/src/abr
.venv/bin/python -m abr.usage_report \
  --library-root library \
  --config ~/.config/abr/mail.ini \
  --preview-current
```

A regular run sends completed periods, including periods without usage. The
systemd service can be started manually after the next reporting boundary:

```bash
sudo systemctl start abr-usage-report.service
journalctl -u abr-usage-report.service -n 100 --no-pager
```

Alternatively, run the same regular operation directly:

```bash
.venv/bin/python -m abr.usage_report \
  --library-root library \
  --config ~/.config/abr/mail.ini
```

Inspect the statistics file:

```bash
python -m json.tool library/usage_statistics/current.json
```

After a successful delivery, the journal reports the period identifier and
archive path. On an SMTP error, the service exits with a failure status and
the period remains available for the next attempt.

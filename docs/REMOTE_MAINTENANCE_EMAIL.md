# Remote Maintenance by E-Mail

Last reviewed: `2026-07-13`

Deutsche Fassung: [Fernwartung per E-Mail](../docs_DE/REMOTE_MAINTENANCE_EMAIL.md)

## Purpose

E-mail maintenance supplements SSH with two file-transfer paths:

- `email_download FILE` sends a local file to the `recipient` configured in
  the local `mail.ini`.
- A `systemd` timer checks every two minutes for messages not yet processed by
  ABR. A message from that configured recipient, with the subject
  `save PATH/` and exactly one attachment, stores the attachment under its
  attachment filename in the specified directory.

The implementation is located in `abr/remote_mail.py` and uses only the Python
standard library.

## Security Rules

- Account details are stored exclusively in `~/.config/abr/mail.ini` with
  mode `0600`, never in the repository.
- Uploads are accepted only from the exact sender configured locally as
  `recipient`.
- A message must contain exactly one attachment.
- The target directory must already exist. The filename is taken from the
  attachment and must not contain a path.
- An existing file is never overwritten; storage is atomic.
- Relative upload paths are resolved from the Pi user's home directory.
- Successfully processed upload messages are deleted from the IMAP mailbox
  only after the attachment has been stored safely. Messages already marked
  as read by another mail client are also detected.
- Processed IMAP UIDs are stored in
  `~/.local/state/abr/mail_upload.json`.
- Failed messages are not deleted and are retried on the next run regardless
  of their read status.

E-mail is not end-to-end encrypted. Do not transfer private keys, passwords,
or other secrets through this mechanism.

## Installation on the Raspberry Pi

From the current project directory:

```bash
cd ~/src/abr
sudo deploy/install_remote_mail.sh
```

On its first run, the installer creates `~/.config/abr/mail.ini` from
`deploy/mail.ini.example`. Complete the file with the e-mail address,
recipient, username, app password, and SMTP/IMAP settings for the selected
provider, then run the same installation command again. Real values remain
outside the repository and the file uses mode `0600`. Many providers require
a separate app password. SMTP and IMAP both use SSL/TLS.

The installer creates:

- `/usr/local/bin/email_download`
- `/etc/systemd/system/abr-email-upload.service`
- `/etc/systemd/system/abr-email-upload.timer`

## Usage

Send a file from the Pi:

```bash
cd ~/src/abr/captures/latest/raw
email_download cam0_raw.jpg
```

Upload a file to the Pi using an absolute home-relative form:

```text
Subject: save ~/src/abr/
Attachment: example.txt
```

Relative form, resolved from `~`:

```text
Subject: save src/abr/
Attachment: example.txt
```

Important: Enter only `save ...` in the actual subject field. The label
`Subject:` is not part of the subject.

## Verification and Diagnostics

```bash
email_download --help
systemctl status abr-email-upload.timer
sudo systemctl start abr-email-upload.service
journalctl -u abr-email-upload.service -n 50 --no-pager
```

An existing target file deliberately causes an error. After removing or
renaming that file, the message still present in the mailbox can be processed
on the next run.

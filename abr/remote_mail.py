from __future__ import annotations

import argparse
import configparser
import email
import imaplib
import json
import os
import smtplib
import ssl
import sys
from dataclasses import dataclass
from email.headerregistry import Address
from email.message import EmailMessage, Message
from email.policy import default
from email.utils import getaddresses
from pathlib import Path


DEFAULT_CONFIG = Path("~/.config/abr/mail.ini")
DEFAULT_STATE = Path("~/.local/state/abr/mail_upload.json")


@dataclass(frozen=True)
class MailConfig:
    address: str
    recipient: str
    username: str
    password: str
    smtp_host: str
    smtp_port: int
    imap_host: str
    imap_port: int
    inbox: str = "INBOX"


def load_config(path: Path | str = DEFAULT_CONFIG) -> MailConfig:
    config_path = Path(path).expanduser()
    parser = configparser.ConfigParser(interpolation=None)
    if not parser.read(config_path):
        raise RuntimeError(f"Mail-Konfiguration nicht gefunden: {config_path}")
    try:
        section = parser["mail"]
        address = section["address"].strip()
        return MailConfig(
            address=address,
            recipient=section.get("recipient", address).strip(),
            username=section.get("username", section["address"]).strip(),
            password=section["password"],
            smtp_host=section["smtp_host"].strip(),
            smtp_port=section.getint("smtp_port", 465),
            imap_host=section["imap_host"].strip(),
            imap_port=section.getint("imap_port", 993),
            inbox=section.get("inbox", "INBOX").strip(),
        )
    except (KeyError, ValueError) as exc:
        raise RuntimeError(f"Ungueltige Mail-Konfiguration in {config_path}: {exc}") from exc


def send_file(filename: str, config: MailConfig) -> None:
    path = Path(filename).expanduser()
    if not path.is_file():
        raise RuntimeError(f"Keine regulaere Datei: {path}")

    message = EmailMessage()
    message["From"] = config.address
    message["To"] = Address(addr_spec=config.recipient)
    message["Subject"] = f"ABR download: {path.name}"
    message.set_content(f"Datei vom ABR Raspberry Pi: {path.resolve()}")
    message.add_attachment(
        path.read_bytes(),
        maintype="application",
        subtype="octet-stream",
        filename=path.name,
    )

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, context=context) as smtp:
        smtp.login(config.username, config.password)
        smtp.send_message(message)


def send_text(
    *, subject: str, body: str, config: MailConfig, recipient: str | None = None
) -> None:
    message = EmailMessage()
    message["From"] = config.address
    message["To"] = Address(addr_spec=recipient or config.recipient)
    message["Subject"] = subject
    message.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, context=context) as smtp:
        smtp.login(config.username, config.password)
        smtp.send_message(message)


def _sender_addresses(message: Message) -> set[str]:
    return {address.casefold() for _, address in getaddresses(message.get_all("From", []))}


def _attachments(message: Message) -> list[tuple[str, bytes]]:
    attachments: list[tuple[str, bytes]] = []
    for part in message.walk():
        if part.is_multipart() or part.get_content_disposition() != "attachment":
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True)
        if filename is not None and payload is not None:
            attachments.append((str(filename), payload))
    return attachments


def target_from_subject(subject: str, home: Path) -> Path | None:
    prefix = "save "
    if not subject.startswith(prefix):
        return None
    raw_directory = subject[len(prefix) :].strip()
    if not raw_directory or "\x00" in raw_directory:
        return None
    directory = Path(raw_directory).expanduser()
    if not directory.is_absolute():
        directory = home / directory
    return directory


def _safe_attachment_filename(filename: str) -> str:
    if (
        not filename
        or filename in {".", ".."}
        or "\x00" in filename
        or "/" in filename
        or "\\" in filename
    ):
        raise RuntimeError(f"Ungueltiger Dateiname im Anhang: {filename!r}")
    return filename


def save_message_attachment(
    message: Message, home: Path, *, allowed_sender: str
) -> Path | None:
    if _sender_addresses(message) != {allowed_sender.casefold()}:
        return None
    directory = target_from_subject(str(message.get("Subject", "")), home)
    if directory is None:
        return None
    attachments = _attachments(message)
    if len(attachments) != 1:
        raise RuntimeError("Upload-Mail muss genau einen benannten Anhang enthalten")
    filename, payload = attachments[0]
    if not directory.is_dir():
        raise RuntimeError(f"Zielverzeichnis existiert nicht: {directory}")
    target = directory / _safe_attachment_filename(filename)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(target, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def _load_processed_uids(path: Path, uid_validity: str) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return set()
    if data.get("uid_validity") != uid_validity:
        return set()
    return {str(uid) for uid in data.get("processed_uids", [])}


def _save_processed_uids(path: Path, uid_validity: str, processed: set[str]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {"uid_validity": uid_validity, "processed_uids": sorted(processed, key=int)},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def _delete_imap_message(imap: imaplib.IMAP4_SSL, uid: bytes) -> None:
    status, _ = imap.uid("store", uid, "+FLAGS", "(\\Deleted)")
    if status != "OK":
        raise RuntimeError(f"Upload-Mail UID {uid.decode()} konnte nicht geloescht werden")
    status, _ = imap.expunge()
    if status != "OK":
        raise RuntimeError(f"Upload-Mail UID {uid.decode()} konnte nicht entfernt werden")


def receive_once(config: MailConfig, home: Path, state_path: Path = DEFAULT_STATE) -> tuple[int, int]:
    saved = 0
    failed = 0
    context = ssl.create_default_context()
    with imaplib.IMAP4_SSL(config.imap_host, config.imap_port, ssl_context=context) as imap:
        imap.login(config.username, config.password)
        status, _ = imap.select(config.inbox)
        if status != "OK":
            raise RuntimeError(f"IMAP-Ordner kann nicht geoeffnet werden: {config.inbox}")
        _, uid_validity_data = imap.response("UIDVALIDITY")
        uid_validity = (
            uid_validity_data[0].decode("ascii", errors="replace")
            if uid_validity_data
            else "unknown"
        )
        state_path = state_path.expanduser()
        processed = _load_processed_uids(state_path, uid_validity)
        # Nicht auf UNSEEN einschraenken: Mailprogramme koennen eine neue
        # Upload-Mail bereits als gelesen markiert haben, bevor der Timer laeuft.
        status, data = imap.uid("search", None, '(SUBJECT "save ")')
        if status != "OK":
            raise RuntimeError("IMAP-Suche fehlgeschlagen")
        for uid in data[0].split():
            uid_text = uid.decode("ascii", errors="replace")
            if uid_text in processed:
                continue
            status, records = imap.uid("fetch", uid, "(BODY.PEEK[])")
            if status != "OK" or not records or not isinstance(records[0], tuple):
                failed += 1
                continue
            message = email.message_from_bytes(records[0][1], policy=default)
            try:
                target = save_message_attachment(
                    message, home, allowed_sender=config.recipient
                )
            except (FileExistsError, OSError, RuntimeError) as exc:
                failed += 1
                print(f"Upload UID {uid.decode()}: {exc}", file=sys.stderr)
                continue
            if target is not None:
                saved += 1
                print(f"Gespeichert: {target}")
                try:
                    _delete_imap_message(imap, uid)
                    print(f"Upload-Mail geloescht: UID {uid_text}")
                except RuntimeError as exc:
                    # Die Datei wurde bereits sicher gespeichert und darf nicht
                    # durch einen erneuten Lauf ueberschrieben werden. Deshalb
                    # gilt die UID auch bei einem IMAP-Loeschfehler als verarbeitet.
                    failed += 1
                    print(str(exc), file=sys.stderr)
            processed.add(uid_text)
            _save_processed_uids(state_path, uid_validity, processed)
    return saved, failed


def download_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Datei per E-Mail an den festen Wartungsempfaenger senden")
    parser.add_argument("filename")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        send_file(args.filename, config)
    except Exception as exc:
        print(f"email_download: {exc}", file=sys.stderr)
        return 1
    print(f"Gesendet an {config.recipient}: {Path(args.filename).name}")
    return 0


def upload_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Neue ABR-Upload-Mails einmalig pruefen")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    args = parser.parse_args(argv)
    try:
        saved, failed = receive_once(
            load_config(args.config),
            args.home.expanduser().resolve(),
            args.state.expanduser(),
        )
    except Exception as exc:
        print(f"email_upload: {exc}", file=sys.stderr)
        return 1
    print(f"Upload-Pruefung beendet: {saved} gespeichert, {failed} fehlgeschlagen")
    return 1 if failed else 0

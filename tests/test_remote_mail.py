from email.message import EmailMessage
from pathlib import Path

import pytest

from abr.remote_mail import (
    _delete_imap_message,
    _load_processed_uids,
    _save_processed_uids,
    load_config,
    save_message_attachment,
    target_from_subject,
)


def upload_message(
    subject: str,
    payload: bytes = b"content",
    sender: str = "owner@example.com",
    filename: str = "source.bin",
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "raspi@example.test"
    message["Subject"] = subject
    message.set_content("upload")
    message.add_attachment(payload, maintype="application", subtype="octet-stream", filename=filename)
    return message


def test_relative_directory_is_below_home(tmp_path: Path) -> None:
    assert target_from_subject("save src/abr/", tmp_path) == tmp_path / "src/abr"


def test_attachment_is_saved_with_attachment_filename(tmp_path: Path) -> None:
    target = tmp_path / "test1.txt"
    saved = save_message_attachment(
        upload_message(f"save {tmp_path}/", filename="test1.txt"),
        tmp_path,
        allowed_sender="owner@example.com",
    )
    assert saved == target
    assert target.read_bytes() == b"content"
    assert target.stat().st_mode & 0o777 == 0o600


def test_existing_file_is_never_overwritten(tmp_path: Path) -> None:
    target = tmp_path / "existing.txt"
    target.write_bytes(b"old")
    with pytest.raises(FileExistsError):
        save_message_attachment(
            upload_message(f"save {tmp_path}/", b"new", filename="existing.txt"),
            tmp_path,
            allowed_sender="owner@example.com",
        )
    assert target.read_bytes() == b"old"


def test_wrong_sender_is_ignored(tmp_path: Path) -> None:
    target = tmp_path / "ignored.txt"
    assert save_message_attachment(
        upload_message(f"save {tmp_path}/", sender="attacker@example.test", filename=target.name),
        tmp_path,
        allowed_sender="owner@example.com",
    ) is None
    assert not target.exists()


def test_missing_parent_is_rejected(tmp_path: Path) -> None:
    message = upload_message(f"save {tmp_path / 'missing'}/", filename="file.txt")
    with pytest.raises(RuntimeError, match="Zielverzeichnis"):
        save_message_attachment(message, tmp_path, allowed_sender="owner@example.com")


@pytest.mark.parametrize("filename", ["../escape.txt", "subdir/file.txt", r"subdir\file.txt"])
def test_attachment_filename_must_not_contain_a_path(tmp_path: Path, filename: str) -> None:
    with pytest.raises(RuntimeError, match="Dateiname"):
        save_message_attachment(
            upload_message(f"save {tmp_path}/", filename=filename),
            tmp_path,
            allowed_sender="owner@example.com",
        )


def test_password_may_contain_percent_sign(tmp_path: Path) -> None:
    config = tmp_path / "mail.ini"
    config.write_text(
        "[mail]\naddress=a@example.test\nrecipient=owner@example.test\npassword=50%secret\n"
        "smtp_host=smtp.example.test\nimap_host=imap.example.test\n",
        encoding="utf-8",
    )
    assert load_config(config).password == "50%secret"


def test_recipient_defaults_to_local_account_address(tmp_path: Path) -> None:
    config = tmp_path / "mail.ini"
    config.write_text(
        "[mail]\naddress=a@example.test\npassword=secret\n"
        "smtp_host=smtp.example.test\nimap_host=imap.example.test\n",
        encoding="utf-8",
    )
    assert load_config(config).recipient == "a@example.test"


def test_processed_uid_state_is_scoped_to_mailbox_uid_validity(tmp_path: Path) -> None:
    state = tmp_path / "state" / "mail_upload.json"
    _save_processed_uids(state, "123", {"20", "3"})

    assert _load_processed_uids(state, "123") == {"3", "20"}
    assert _load_processed_uids(state, "124") == set()
    assert state.stat().st_mode & 0o777 == 0o600


class FakeImap:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def uid(self, *args):
        self.calls.append(("uid", *args))
        return "OK", [b""]

    def expunge(self):
        self.calls.append(("expunge",))
        return "OK", [b"1"]


def test_successful_upload_mail_is_deleted_and_expunged() -> None:
    imap = FakeImap()
    _delete_imap_message(imap, b"42")
    assert imap.calls == [
        ("uid", "store", b"42", "+FLAGS", "(\\Deleted)"),
        ("expunge",),
    ]

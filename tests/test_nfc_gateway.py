from abr.hardware.nfc_gateway import parse_tag_id_from_status_lines, parse_tag_scan_from_status_lines


def test_parse_tag_id_from_status_lines_returns_present_uid() -> None:
    lines = [
        "OK uptime_ms=12345",
        "READER id=1 label=PN5180-1 enabled=1 online=1 fw=0x01000312 tag=1 uid=e0040150234abcde tech=ISO15693 len=8 agc=392 rf_status=0x00300188 rx_status=0x00000008 rx_len=8 last_error=none",
        "END",
    ]

    assert parse_tag_id_from_status_lines(lines) == "E0040150234ABCDE"


def test_parse_tag_id_from_status_lines_normalizes_colon_separated_uid() -> None:
    lines = [
        "OK uptime_ms=12345",
        "READER id=1 label=PN5180-1 enabled=1 online=1 fw=0x04000400 tag=1 uid=E0:04:01:09:16:F3:48:97 tech=ISO15693 len=8 agc=401 rf_status=0x00200191 rx_status=0x00000008 rx_len=8 last_error=none",
        "END",
    ]

    assert parse_tag_id_from_status_lines(lines) == "E004010916F34897"


def test_parse_tag_id_from_status_lines_prefers_iso14443a_when_both_tags_are_present() -> None:
    lines = [
        "OK uptime_ms=12345",
        "READER id=1 label=PN5180-1 enabled=1 online=1 fw=0x01000312 tag=1 uid=E0:04:01:09:16:F3:48:97 tech=ISO15693 len=8 agc=392 rf_status=0x00300188 rx_status=0x00000008 rx_len=8 tag15693=1 uid15693=E0:04:01:09:16:F3:48:97 len15693=8 tag14443a=1 uid14443a=04:A1:B2:C3 len14443a=4 last_error=none",
        "END",
    ]

    assert parse_tag_id_from_status_lines(lines) == "04A1B2C3"


def test_parse_tag_id_from_status_lines_returns_iso14443a_when_no_iso15693_is_present() -> None:
    lines = [
        "OK uptime_ms=12345",
        "READER id=1 label=PN5180-1 enabled=1 online=1 fw=0x01000312 tag=1 uid=04:A1:B2:C3 tech=ISO14443A len=4 agc=210 rf_status=0x00300188 rx_status=0x00000004 rx_len=4 tag15693=0 uid15693=- len15693=- tag14443a=1 uid14443a=04:A1:B2:C3 len14443a=4 last_error=none",
        "END",
    ]

    assert parse_tag_id_from_status_lines(lines) == "04A1B2C3"


def test_parse_tag_id_from_status_lines_prefers_iso14443a_across_multiple_readers() -> None:
    lines = [
        "OK uptime_ms=12345",
        "READER id=1 label=PN5180-1 enabled=1 online=1 fw=0x01000312 tag=1 uid=04:A1:B2:C3 tech=ISO14443A len=4 agc=210 rf_status=0x00300188 rx_status=0x00000004 rx_len=4 tag15693=0 uid15693=- len15693=- tag14443a=1 uid14443a=04:A1:B2:C3 len14443a=4 last_error=none",
        "READER id=2 label=PN5180-2 enabled=1 online=1 fw=0x01000312 tag=1 uid=E0:04:01:09:16:F3:48:97 tech=ISO15693 len=8 agc=392 rf_status=0x00300188 rx_status=0x00000008 rx_len=8 tag15693=1 uid15693=E0:04:01:09:16:F3:48:97 len15693=8 tag14443a=0 uid14443a=- len14443a=- last_error=none",
        "END",
    ]

    assert parse_tag_id_from_status_lines(lines) == "04A1B2C3"


def test_parse_tag_scan_preserves_technologies_and_reader_ids() -> None:
    scan = parse_tag_scan_from_status_lines(
        [
            "READER id=1 tag=1 tag15693=1 uid15693=E0:04:01:09:16:F3:48:97 "
            "tag14443a=1 uid14443a=04:A1:B2:C3",
            "READER id=2 tag=0 tag15693=0 uid15693=- tag14443a=0 uid14443a=-",
            "END",
        ]
    )

    assert [(tag.uid, tag.technology, tag.reader_id) for tag in scan.tags] == [
        ("04A1B2C3", "ISO14443A", 1),
        ("E004010916F34897", "ISO15693", 1),
    ]


def test_parse_tag_id_from_status_lines_returns_none_without_tag() -> None:
    lines = [
        "OK uptime_ms=12345",
        "READER id=1 label=PN532-1 enabled=1 online=1 fw=0x32010607 tag=0 uid=- tech=- len=- agc=- rf_status=- rx_status=- rx_len=- last_error=none",
        "END",
    ]

    assert parse_tag_id_from_status_lines(lines) is None

import hashlib
import stat
import zipfile

import pytest
from django.test import override_settings

from apps.documents.validation import (
    FileValidationError,
    inspect_zip,
    normalize_original_filename,
    validate_staged_file,
)


def _write_zip(path, members, *, compression=zipfile.ZIP_DEFLATED):
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def _ooxml_members(kind="docx"):
    if kind == "docx":
        part = "word/document.xml"
        content_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
        )
    else:
        part = "xl/workbook.xml"
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
    content_types = (
        '<?xml version="1.0"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        f'<Override PartName="/{part}" ContentType="{content_type}"/>'
        "</Types>"
    )
    return {
        "[Content_Types].xml": content_types,
        "_rels/.rels": '<Relationships xmlns="urn:test"/>',
        part: '<document xmlns="urn:test"/>',
    }


@pytest.mark.parametrize(
    ("filename", "payload", "mime_type"),
    [
        ("paper.pdf", b"%PDF-1.7\nbody\n%%EOF\n", "application/pdf"),
        (
            "figure.png",
            b"\x89PNG\r\n\x1a\n" + b"body" + b"\x00\x00\x00\x00IEND\xaeB\x60\x82",
            "image/png",
        ),
        ("photo.jpg", b"\xff\xd8payload\xff\xd9", "image/jpeg"),
        ("photo.jpeg", b"\xff\xd8payload\xff\xd9", "image/jpeg"),
    ],
)
def test_signature_formats_are_detected_from_content(tmp_path, filename, payload, mime_type):
    path = tmp_path / "staged.part"
    path.write_bytes(payload)

    result = validate_staged_file(path, filename)

    assert result.detected_mime_type == mime_type
    assert result.file_size == len(payload)
    assert result.sha256 == hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize("filename", ["../paper.pdf", "folder/paper.pdf", "paper.exe", "paper.doc"])
def test_original_filename_rejects_paths_and_non_whitelisted_extensions(filename):
    with pytest.raises(FileValidationError):
        normalize_original_filename(filename)


@pytest.mark.parametrize(
    ("filename", "payload"),
    [
        ("fake.pdf", b"not a pdf%%EOF"),
        ("truncated.pdf", b"%PDF-1.7 without eof"),
        ("fake.png", b"\x89PNG\r\n\x1a\nmissing-iend"),
        ("fake.jpg", b"\xff\xd8missing-end"),
    ],
)
def test_signature_formats_reject_mismatch_or_missing_terminator(tmp_path, filename, payload):
    path = tmp_path / "staged.part"
    path.write_bytes(payload)

    with pytest.raises(FileValidationError) as exc_info:
        validate_staged_file(path, filename)

    assert exc_info.value.code == "type_mismatch"


def test_plain_zip_is_inspected_without_extracting_members(tmp_path):
    path = tmp_path / "safe.zip"
    _write_zip(path, {"folder/readme.txt": b"safe"})

    result = validate_staged_file(path, "archive.zip")

    assert result.detected_mime_type == "application/zip"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    "member_name", ["../escape.txt", "/absolute.txt", "C:/drive.txt", "a\\b.txt"]
)
def test_zip_rejects_unsafe_member_paths(tmp_path, member_name):
    path = tmp_path / "unsafe.zip"
    _write_zip(path, {member_name: b"unsafe"})

    with pytest.raises(FileValidationError) as exc_info:
        inspect_zip(path)

    assert exc_info.value.code == "unsafe_zip_path"


def test_zip_rejects_nested_archives_by_name_or_signature(tmp_path):
    named = tmp_path / "named.zip"
    disguised = tmp_path / "disguised.zip"
    _write_zip(named, {"inner.zip": b"not-important"})
    _write_zip(disguised, {"inner.bin": b"PK\x03\x04nested"})

    for path in (named, disguised):
        with pytest.raises(FileValidationError) as exc_info:
            inspect_zip(path)
        assert exc_info.value.code == "nested_zip"


def test_zip_rejects_symbolic_links_and_duplicate_paths(tmp_path):
    symlink_zip = tmp_path / "symlink.zip"
    link = zipfile.ZipInfo("link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(symlink_zip, "w") as archive:
        archive.writestr(link, "target")
    with pytest.raises(FileValidationError) as exc_info:
        inspect_zip(symlink_zip)
    assert exc_info.value.code == "unsafe_zip_member_type"

    duplicate_zip = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(duplicate_zip, "w") as archive:
        archive.writestr("A.txt", b"first")
        archive.writestr("a.txt", b"second")
    with pytest.raises(FileValidationError) as exc_info:
        inspect_zip(duplicate_zip)
    assert exc_info.value.code == "duplicate_zip_member"


def test_zip_rejects_encrypted_member_flags(tmp_path):
    path = tmp_path / "encrypted-flag.zip"
    _write_zip(path, {"secret.txt": b"secret"})
    content = bytearray(path.read_bytes())
    local_header = content.index(b"PK\x03\x04")
    central_header = content.index(b"PK\x01\x02")
    content[local_header + 6] |= 0x1
    content[central_header + 8] |= 0x1
    path.write_bytes(content)

    with pytest.raises(FileValidationError) as exc_info:
        inspect_zip(path)

    assert exc_info.value.code == "encrypted_zip_member"


@override_settings(
    LABARCHIVE_ZIP_MAX_MEMBER_SIZE=8,
    LABARCHIVE_ZIP_MAX_TOTAL_SIZE=12,
    LABARCHIVE_ZIP_MAX_COMPRESSION_RATIO=1,
    LABARCHIVE_ZIP_MAX_MEMBERS=1,
)
def test_zip_limits_come_from_settings_and_fail_closed(tmp_path):
    cases = {
        "member.zip": {"large.txt": b"123456789"},
        "count.zip": {"one.txt": b"1", "two.txt": b"2"},
        "ratio.zip": {"zeros.txt": b"0" * 8},
    }
    expected_codes = {
        "member.zip": "zip_member_too_large",
        "count.zip": "zip_too_many_members",
        "ratio.zip": "zip_ratio_too_high",
    }
    for filename, members in cases.items():
        path = tmp_path / filename
        _write_zip(path, members)
        with pytest.raises(FileValidationError) as exc_info:
            inspect_zip(path)
        assert exc_info.value.code == expected_codes[filename]


@override_settings(
    LABARCHIVE_ZIP_MAX_MEMBER_SIZE=8,
    LABARCHIVE_ZIP_MAX_TOTAL_SIZE=12,
    LABARCHIVE_ZIP_MAX_COMPRESSION_RATIO=100,
    LABARCHIVE_ZIP_MAX_MEMBERS=2,
)
def test_zip_total_uncompressed_limit_is_enforced(tmp_path):
    path = tmp_path / "total.zip"
    _write_zip(path, {"one.txt": b"1234567", "two.txt": b"1234567"})

    with pytest.raises(FileValidationError) as exc_info:
        inspect_zip(path)

    assert exc_info.value.code == "zip_total_too_large"


def test_zip_crc_is_verified_without_extracting_to_disk(tmp_path):
    path = tmp_path / "corrupt.zip"
    _write_zip(path, {"payload.txt": b"valid-payload"}, compression=zipfile.ZIP_STORED)
    content = bytearray(path.read_bytes())
    payload_offset = content.index(b"valid-payload")
    content[payload_offset + 5] ^= 0x1
    path.write_bytes(content)

    with pytest.raises(FileValidationError) as exc_info:
        inspect_zip(path)

    assert exc_info.value.code == "invalid_zip"


@pytest.mark.parametrize(
    ("kind", "filename", "mime_type"),
    [
        (
            "docx",
            "document.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            "xlsx",
            "workbook.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    ],
)
def test_ooxml_requires_safe_container_and_expected_structure(tmp_path, kind, filename, mime_type):
    path = tmp_path / "office.part"
    _write_zip(path, _ooxml_members(kind))

    result = validate_staged_file(path, filename)

    assert result.detected_mime_type == mime_type


def test_ooxml_rejects_missing_relationships_wrong_kind_and_macros(tmp_path):
    missing = _ooxml_members()
    missing.pop("_rels/.rels")
    wrong_kind = _ooxml_members("xlsx")
    macro = _ooxml_members()
    macro["word/vbaProject.bin"] = b"macro"
    cases = (
        ("missing.docx", missing, "invalid_ooxml"),
        ("wrong.docx", wrong_kind, "invalid_ooxml"),
        ("macro.docx", macro, "macro_enabled_ooxml"),
    )
    for filename, members, code in cases:
        path = tmp_path / filename
        _write_zip(path, members)
        with pytest.raises(FileValidationError) as exc_info:
            validate_staged_file(path, filename)
        assert exc_info.value.code == code


def test_ooxml_rejects_doctype_and_entity_declarations(tmp_path):
    path = tmp_path / "unsafe.docx"
    members = _ooxml_members()
    members["_rels/.rels"] = '<!DOCTYPE x [<!ENTITY x "unsafe">]><Relationships>&x;</Relationships>'
    _write_zip(path, members)

    with pytest.raises(FileValidationError) as exc_info:
        validate_staged_file(path, "unsafe.docx")

    assert exc_info.value.code == "unsafe_ooxml_xml"


def test_validation_rejects_digest_or_size_change_and_symbolic_link(tmp_path):
    path = tmp_path / "paper.part"
    payload = b"%PDF-1.7\n%%EOF"
    path.write_bytes(payload)

    for kwargs, code in (
        ({"expected_size": len(payload) + 1}, "size_mismatch"),
        ({"expected_sha256": "0" * 64}, "sha256_mismatch"),
    ):
        with pytest.raises(FileValidationError) as exc_info:
            validate_staged_file(path, "paper.pdf", **kwargs)
        assert exc_info.value.code == code

    link = tmp_path / "link.part"
    link.symlink_to(path)
    with pytest.raises(FileValidationError) as exc_info:
        validate_staged_file(link, "paper.pdf")
    assert exc_info.value.code == "invalid_staged_file"

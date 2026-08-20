import hashlib
from uuid import uuid4

import pytest

from apps.documents.storage import ControlledFileStorage, StorageError


def _storage(tmp_path, *, max_upload_size=1024):
    media_root = tmp_path / "media"
    return ControlledFileStorage(
        media_root=media_root,
        staging_root=media_root / ".staging",
        max_upload_size=max_upload_size,
    )


def test_staging_streams_size_and_sha256_then_promotes_to_server_key(tmp_path):
    storage = _storage(tmp_path)
    project_id = uuid4()
    asset_id = uuid4()

    staged = storage.stage_chunks(asset_id, [b"phase", b"-three"])
    relative_key = storage.final_key(project_id, asset_id, ".PDF")
    final_path = storage.promote(staged.path, relative_key)

    assert staged.file_size == 11
    assert staged.sha256 == hashlib.sha256(b"phase-three").hexdigest()
    assert relative_key == (
        f"projects/{project_id.hex}/documents/{asset_id.hex[:2]}/{asset_id.hex}.pdf"
    )
    assert storage.stored_filename(asset_id, ".PDF") == f"{asset_id.hex}.pdf"
    assert final_path.read_bytes() == b"phase-three"
    assert not staged.path.exists()


def test_staging_rejects_oversize_and_empty_streams_without_leaving_files(tmp_path):
    storage = _storage(tmp_path, max_upload_size=4)

    for chunks, code in (([b"12345"], "file_too_large"), ([], "empty_file")):
        asset_id = uuid4()
        with pytest.raises(StorageError) as exc_info:
            storage.stage_chunks(asset_id, chunks)
        assert exc_info.value.code == code
        assert not storage.staging_path(asset_id).exists()


def test_staging_is_exclusive_and_does_not_overwrite_an_active_attempt(tmp_path):
    storage = _storage(tmp_path)
    asset_id = uuid4()
    first = storage.stage_chunks(asset_id, [b"first"])

    with pytest.raises(StorageError) as exc_info:
        storage.stage_chunks(asset_id, [b"second"])

    assert exc_info.value.code == "staging_file_exists"
    assert first.path.read_bytes() == b"first"


@pytest.mark.parametrize(
    "relative_key",
    ["/absolute.pdf", "../escape.pdf", "documents/../escape.pdf", "C:/escape.pdf", "a\\b"],
)
def test_final_path_resolution_rejects_unsafe_storage_keys(tmp_path, relative_key):
    storage = _storage(tmp_path)

    with pytest.raises(StorageError) as exc_info:
        storage.resolve_final(relative_key)

    assert exc_info.value.code == "unsafe_storage_key"


def test_promote_refuses_to_overwrite_existing_immutable_asset(tmp_path):
    storage = _storage(tmp_path)
    first_id = uuid4()
    second_id = uuid4()
    relative_key = storage.final_key(uuid4(), first_id, ".pdf")
    first = storage.stage_chunks(first_id, [b"first"])
    storage.promote(first.path, relative_key)
    second = storage.stage_chunks(second_id, [b"second"])

    with pytest.raises(StorageError) as exc_info:
        storage.promote(second.path, relative_key)

    assert exc_info.value.code == "final_file_exists"
    assert storage.resolve_final(relative_key).read_bytes() == b"first"
    assert second.path.read_bytes() == b"second"


def test_discard_only_removes_files_inside_controlled_staging_root(tmp_path):
    storage = _storage(tmp_path)
    staged = storage.stage_chunks(uuid4(), [b"discard"])
    outside = tmp_path / "outside.part"
    outside.write_bytes(b"preserve")

    assert storage.discard_staged(staged.path) is True
    assert storage.discard_staged(staged.path) is False
    with pytest.raises(StorageError):
        storage.discard_staged(outside)
    assert outside.read_bytes() == b"preserve"


def test_reconciliation_enumeration_excludes_staging_from_final_keys(tmp_path):
    storage = _storage(tmp_path)
    staged = storage.stage_chunks(uuid4(), [b"staging"])
    final_id = uuid4()
    final_staged = storage.stage_chunks(final_id, [b"final"])
    final_key = storage.final_key(uuid4(), final_id, ".pdf")
    storage.promote(final_staged.path, final_key)

    assert storage.iter_staging_entries() == (staged.path,)
    assert storage.iter_final_keys() == (final_key,)


def test_staging_quarantine_can_compensate_or_purge(tmp_path):
    storage = _storage(tmp_path)
    task_id = uuid4()
    first = storage.stage_chunks(uuid4(), [b"first"])

    quarantined = storage.quarantine_staging_entry(first.path, task_id)
    assert quarantined.read_bytes() == b"first"
    assert not first.path.exists()
    storage.restore_quarantined_staging(quarantined, first.path)
    assert first.path.read_bytes() == b"first"

    quarantined = storage.quarantine_staging_entry(first.path, task_id)
    storage.purge_quarantined_staging(quarantined)
    assert not quarantined.exists()
    assert not first.path.exists()

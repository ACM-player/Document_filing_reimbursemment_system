from pathlib import Path

import pytest

from apps.documents.models import MalwareScanStatus
from apps.documents.scanning import ScanResult, scan_allows_release, scan_file


class _Scanner:
    def __init__(self, result):
        self.result = result

    def scan(self, path):
        assert path == Path("staged.part")
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_missing_scanner_records_not_configured_without_claiming_clean():
    result = scan_file(Path("staged.part"))

    assert result == ScanResult(MalwareScanStatus.NOT_CONFIGURED, "scanner_not_configured")
    assert scan_allows_release(result, require_malware_scan=False) is True
    assert scan_allows_release(result, require_malware_scan=True) is False


@pytest.mark.parametrize(
    ("status", "development_allowed", "production_allowed"),
    [
        (MalwareScanStatus.CLEAN, True, True),
        (MalwareScanStatus.PENDING, False, False),
        (MalwareScanStatus.INFECTED, False, False),
        (MalwareScanStatus.ERROR, False, False),
    ],
)
def test_scan_release_policy_is_fail_closed(status, development_allowed, production_allowed):
    result = scan_file(Path("staged.part"), _Scanner(ScanResult(status, "test")))

    assert scan_allows_release(result, require_malware_scan=False) is development_allowed
    assert scan_allows_release(result, require_malware_scan=True) is production_allowed


def test_scanner_errors_and_invalid_results_become_explicit_error_facts():
    raised = scan_file(Path("staged.part"), _Scanner(RuntimeError("scanner unavailable")))
    invalid = scan_file(Path("staged.part"), _Scanner(ScanResult("UNKNOWN")))
    malformed = scan_file(Path("staged.part"), _Scanner(None))
    oversized_reason = scan_file(
        Path("staged.part"),
        _Scanner(ScanResult(MalwareScanStatus.CLEAN, "x" * 101)),
    )

    assert raised == ScanResult(MalwareScanStatus.ERROR, "scanner_error")
    assert invalid == ScanResult(MalwareScanStatus.ERROR, "invalid_scanner_result")
    assert malformed == ScanResult(MalwareScanStatus.ERROR, "invalid_scanner_result")
    assert oversized_reason == ScanResult(MalwareScanStatus.ERROR, "invalid_scanner_result")

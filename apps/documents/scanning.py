from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from django.conf import settings

from .models import MalwareScanStatus


@dataclass(frozen=True)
class ScanResult:
    status: str
    reason_code: str = ""


class MalwareScanner(Protocol):
    def scan(self, path: Path) -> ScanResult: ...


class NotConfiguredMalwareScanner:
    def scan(self, path: Path) -> ScanResult:
        del path
        return ScanResult(MalwareScanStatus.NOT_CONFIGURED, "scanner_not_configured")


def scan_file(path: Path, scanner: MalwareScanner | None = None) -> ScanResult:
    active_scanner = scanner or NotConfiguredMalwareScanner()
    try:
        result = active_scanner.scan(Path(path))
    except Exception:
        return ScanResult(MalwareScanStatus.ERROR, "scanner_error")
    if (
        not isinstance(result, ScanResult)
        or result.status not in MalwareScanStatus.values
        or not isinstance(result.reason_code, str)
        or len(result.reason_code) > 100
    ):
        return ScanResult(MalwareScanStatus.ERROR, "invalid_scanner_result")
    return result


def scan_allows_release(
    result: ScanResult,
    *,
    require_malware_scan: bool | None = None,
) -> bool:
    require_scan = (
        settings.LABARCHIVE_REQUIRE_MALWARE_SCAN
        if require_malware_scan is None
        else require_malware_scan
    )
    if require_scan:
        return result.status == MalwareScanStatus.CLEAN
    return result.status in {
        MalwareScanStatus.NOT_CONFIGURED,
        MalwareScanStatus.CLEAN,
    }

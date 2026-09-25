"""K2/K3: the capture kit's manifest, build and verifier (the script itself runs on real
Windows PowerShell 5.1 in the capture-kit CI workflow)."""

import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from tally_contract import tally_constants as tc
from tally_tools import capture_kit as kit
from tally_tools.mock_tally import MockConfig, answer

SOURCE = kit.SOURCE


def test_every_gate_has_a_capture_scenario_or_checklist_item() -> None:
    covered = kit.gates_covered(kit.manifest())
    assert {f"G{i}" for i in range(1, 36)} <= covered


def test_every_entry_has_the_fields_the_script_reads_under_strict_mode() -> None:
    m = kit.manifest()
    for section in ("check", "capture", "reference"):
        for entry in m[section]:
            assert set(entry) == {"id", "file", "gates", "needs_other_company", "expect_error"}, (
                entry
            )
    capture_ids = {e["id"] for e in m["capture"]}
    for scenario in m["scenarios"]:
        assert set(scenario) == {"name", "gates", "requests", "instructions", "undo"}
        assert set(scenario["requests"]) <= capture_ids, scenario["name"]


def test_build_writes_the_script_docs_tdl_requests_and_a_zip(tmp_path: Path) -> None:
    built = kit.build(tmp_path)
    for name in (
        "Capture-Tally.ps1",
        "README.md",
        "CHECKLIST.md",
        "manifest.json",
        "tdl/TA_Minimal.tdl",
        "tdl/TallyAnalytics.tdl",
    ):
        assert (built / name).is_file(), name
    manifest = json.loads((built / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["tdl_version"] == tc.TDL_VERSION
    for section in ("check", "capture", "reference"):
        for entry in manifest[section]:
            request = (built / entry["file"]).read_bytes()
            assert ET.fromstring(request).tag == "ENVELOPE", entry["id"]
    with zipfile.ZipFile(tmp_path / f"{kit.KIT_NAME}.zip") as archive:
        assert f"{kit.KIT_NAME}/Capture-Tally.ps1" in archive.namelist()


def test_templates_carry_placeholders_the_script_fills() -> None:
    raw = kit.CAPTURE["vouchers_full"][0]()
    assert b"{{COMPANY}}" in raw and b"{{BOOKS_FROM}}" in raw


def test_the_script_is_ascii_for_windows_powershell_5_1() -> None:
    """Windows PowerShell 5.1 reads a BOM-less script as ANSI: any non-ASCII byte would be
    misread, so the script must be pure ASCII."""
    raw = (SOURCE / "Capture-Tally.ps1").read_bytes()
    assert all(b < 128 for b in raw)


@pytest.mark.parametrize("name", ["README.md", "CHECKLIST.md"])
def test_docs_open_with_the_test_company_warning(name: str) -> None:
    head = (SOURCE / name).read_text(encoding="utf-8")[:600]
    assert "TEST COMPANY ONLY" in head and "real business" in head


def test_readme_loads_the_minimal_tdl_first_and_explains_errors() -> None:
    readme = (SOURCE / "README.md").read_text(encoding="utf-8")
    assert readme.index("TA_Minimal.tdl") < readme.index("TallyAnalytics.tdl")
    assert "Troubleshooting TDL errors" in readme
    for what in ("full error text", "line number", "TallyPrime version"):
        assert what in readme


def _fake_run(root: Path, config: MockConfig) -> Path:
    """What the script writes, reproduced in Python, to test the verifier."""
    run = root / "20260101-000000-capture"
    folder = run / "capture"
    folder.mkdir(parents=True)
    body = kit.CAPTURE["info"][0]().replace(b"{{COMPANY}}", b"Test Co")
    status, response = answer(config, body)
    (folder / "info.request.xml").write_bytes(body)
    (folder / "info.response.xml").write_bytes(response)
    (folder / "info.meta.json").write_text(
        json.dumps({"id": "info", "http_status": status}), encoding="utf-8"
    )
    for name in ("run.json", "summary.json"):
        (run / name).write_text("{}", encoding="utf-8")
    (run.parent / f"{run.name}.zip").write_bytes(b"zip")
    return folder


def test_verifier_accepts_exact_bytes_and_catches_any_change(tmp_path: Path) -> None:
    config = MockConfig(utf16=True)
    folder = _fake_run(tmp_path, config)
    assert kit.verify(tmp_path, config) == []
    tampered = folder / "info.response.xml"
    tampered.write_bytes(tampered.read_bytes().decode("utf-16").encode("utf-8"))  # re-encoded
    assert any("bytes differ" in p for p in kit.verify(tmp_path, config))

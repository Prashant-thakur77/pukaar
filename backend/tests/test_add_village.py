"""scripts/add_village.py: a village and a new district go into data/ without a code edit, with candidate river
cells from the existing rule and a checklist of what people still have to verify; the seed then carries the
district's LGD code onto the village record, and the CAP message reads it from there."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("add_village", ROOT / "scripts" / "add_village.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture()
def data(tmp_path):
    for name in ("villages.json", "districts.json", "official_sources.json", "river_cells.json", "thresholds.json"):
        shutil.copy(ROOT / "data" / name, tmp_path / name)
    return tmp_path


def fake_cells(lat, lon):
    rows = [{"lat": lat + 0.02, "lon": lon, "km": 2.2, "mean": 4.1, "max": 30.0, "days": 3653},
            {"lat": lat, "lon": lon + 0.02, "km": 1.9, "mean": 0.6, "max": 2.0, "days": 3653}]
    return {"candidates": rows, "rule_suggests": {"lat": lat + 0.02, "lon": lon, "mean": 4.1}}


def test_a_village_in_a_new_district(data):
    mod = _module()
    out = mod.add_village(data, name="Kasol", name_hi="कसोल", district="Kullu", lat=32.01, lon=77.31,
                          district_hi="कुल्लू", lgd_district="20", lgd_village="012345", cells_fn=fake_cells)
    assert out["id"] == "kasol" and out["district_new"] and out["cells"]
    v = next(x for x in json.loads((data / "villages.json").read_text())["villages"] if x["id"] == "kasol")
    assert v["lgd_code"] == "012345" and v["district"] == "Kullu" and "not verified" in v["coords_source"]
    d = json.loads((data / "districts.json").read_text())["districts"]["Kullu"]
    assert d == {"name_hi": "कुल्लू", "state": "Himachal Pradesh", "lgd_state_code": "2", "lgd_code": "20", "officers": []}
    cells = json.loads((data / "river_cells.json").read_text())["villages"]["kasol"]
    assert cells["rule_suggests"]["mean"] == 4.1 and "chosen" not in cells  # chosen by a person, never by the script
    assert json.loads((data / "official_sources.json").read_text())["villages"]["kasol"]["imd_district"] == "Kullu"
    text = (data / "onboarding" / "kasol.md").read_text()
    for must in ("Coordinates checked", "LGD village code", "New district", "River cell chosen by hand",
                 "make seed", "/start kasol"):
        assert must in text, must


def test_refusals(data):
    mod = _module()
    with pytest.raises(ValueError, match="exists"):
        mod.add_village(data, name="Gohar", name_hi="गोहर", district="Mandi", lat=31.5, lon=77.1, offline=True)
    with pytest.raises(ValueError, match="new district"):
        mod.add_village(data, name="Banjar", name_hi="बंजार", district="Kullu", lat=31.6, lon=77.3, offline=True)
    with pytest.raises(ValueError, match="not in India"):
        mod.add_village(data, name="X", name_hi="X", district="Mandi", lat=77.1, lon=31.5, offline=True)
    with pytest.raises(ValueError, match="LGD code 22"):
        mod.add_village(data, name="Bali", name_hi="बाली", district="Mandi", lat=31.6, lon=77.1, lgd_district="99",
                        offline=True)


def test_offline_and_no_network_leave_a_note(data):
    mod = _module()

    def down(lat, lon):
        raise ConnectionError("no network")

    out = mod.add_village(data, name="Bali", name_hi="बाली", district="Mandi", lat=31.6, lon=77.1, cells_fn=down)
    assert not out["cells"] and "could not be reached" in out["checklist"]
    out = mod.add_village(data, name="Seri", name_hi="सेरी", district="Mandi", lat=31.62, lon=77.12, offline=True)
    assert "--offline" in out["checklist"]


def test_seeded_village_of_a_new_district_carries_its_codes_into_cap(data, monkeypatch, repo, frozen):
    from Pukaar.core.config import get_settings
    from Pukaar.scripts.seed import seed
    from Pukaar.services import cap

    _module().add_village(data, name="Kasol", name_hi="कसोल", district="Kullu", lat=32.01, lon=77.31,
                          district_hi="कुल्लू", lgd_district="20", offline=True)
    monkeypatch.setenv("PUKAAR_DATA_DIR", str(data))
    get_settings.cache_clear()
    try:
        seed(repo)
        v = repo.get_village("kasol")
        assert (v.district_hi, v.lgd_district_code, v.lgd_village_code) == ("कुल्लू", "20", None)
        assert v.officers == ["officer1", "officer2"]  # dev: the demo officers
        assert cap.lgd_codes(v) == ("20", None)
        assert cap.area_desc(v, v.name, v.name_hi, hindi=True).startswith("कसोल, कुल्लू")
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_make_target_exists():
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "add-village:" in text and "scripts/add_village.py" in text and "staff-assign:" in text

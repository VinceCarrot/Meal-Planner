"""Read-only LAN viewer (ui4view) and the this-computer-only rule of the main UI (ADR-024)."""

import ast
import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from meal_planner.demo import synthetic_catalogue, write_catalogue
from meal_planner.web import create_app as create_main_app

UI4VIEW = Path(__file__).resolve().parent.parent / "ui4view"
LAN = {"REMOTE_ADDR": "192.168.1.23"}


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


reader = _load("menu_reader", UI4VIEW / "menu_reader.py")  # viewer_app imports it under this name
viewer_app = _load("ui4view_app", UI4VIEW / "app.py")


def write_menu(data_dir, menu_id, start, version=1, dish_ids=("dish_0001", "dish_0002")):
    dinners = [{"date": (start + timedelta(days=w * 7 + d)).isoformat(), "dish_ids": list(dish_ids)}
               for w in range(4) for d in range(5)]
    path = data_dir / "menus" / menu_id / f"v{version:03d}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"menu_id": menu_id, "version": version, "start_date": start.isoformat(),
                                    "diners": [{"description": "成人", "count": 2}], "dinners": dinners},
                                   allow_unicode=True), encoding="utf-8")


@pytest.fixture
def data_dir(tmp_path):
    data = tmp_path / "data"
    write_catalogue(synthetic_catalogue(10), data)
    return data


# --- Viewer ---------------------------------------------------------------------------


def test_no_menu_yet(data_dir):
    assert reader.current_menu(data_dir) == {"menu": None}
    assert reader.current_menu(data_dir / "missing") == {"menu": None}


def test_menu_with_recipes(data_dir):
    write_menu(data_dir, "M001", date(2026, 10, 19))
    view = reader.current_menu(data_dir, today=date(2026, 10, 28))

    menu = view["menu"]
    assert (menu["start_date"], menu["end_date"]) == ("2026-10-19", "2026-11-15")
    assert [len(w["dinners"]) for w in menu["weeks"]] == [5, 5, 5, 5]
    wednesday = menu["weeks"][1]["dinners"][2]
    assert (wednesday["weekday"], wednesday["is_today"]) == ("周三", True)
    recipe = view["recipes"]["dish_0001"]
    assert recipe["name_zh"] != "dish_0001" and recipe["ingredients"]
    assert all(not line["name"].startswith("ing_") for line in recipe["ingredients"])  # resolved to Chinese names


def test_newest_version_and_running_menu_are_shown(data_dir):
    write_menu(data_dir, "M001", date(2026, 10, 19))
    write_menu(data_dir, "M001", date(2026, 10, 19), version=2, dish_ids=("dish_0003",))
    write_menu(data_dir, "M002", date(2026, 11, 16))

    running = reader.current_menu(data_dir, today=date(2026, 10, 20))["menu"]
    assert (running["menu_id"], running["version"]) == ("M001", 2)
    assert running["weeks"][0]["dinners"][0]["dishes"][0]["dish_id"] == "dish_0003"
    assert reader.current_menu(data_dir, today=date(2026, 10, 1))["menu"]["menu_id"] == "M001"  # next to start
    assert reader.current_menu(data_dir, today=date(2027, 1, 1))["menu"]["menu_id"] == "M002"  # most recent


def test_deleted_dish_still_shows(data_dir):
    write_menu(data_dir, "M001", date(2026, 10, 19), dish_ids=("dish_9999",))
    view = reader.current_menu(data_dir, today=date(2026, 10, 19))
    assert view["menu"]["weeks"][0]["dinners"][0]["dishes"][0]["name_zh"] == "dish_9999"
    assert view["recipes"]["dish_9999"]["missing"]


def test_broken_menu_file_is_reported(data_dir):
    (data_dir / "menus" / "M001").mkdir(parents=True)
    (data_dir / "menus" / "M001" / "v001.yaml").write_text("dinners: [", encoding="utf-8")
    response = viewer_app.create_app(data_dir).test_client().get("/api/menu")
    assert response.status_code == 500 and "v001.yaml" in response.get_json()["detail"]


def test_viewer_serves_other_devices(data_dir):
    write_menu(data_dir, "M001", date(2026, 10, 19))
    client = viewer_app.create_app(data_dir).test_client()
    for path in ("/", "/api/menu", "/static/modules/menu/menu.js"):
        response = client.get(path, base_url="http://192.168.1.5:5050", environ_base=LAN)
        assert response.status_code == 200, path
    assert client.get("/api/menu", environ_base=LAN).get_json()["menu"]["menu_id"] == "M001"


def test_viewer_is_read_only_and_has_no_claude_path(data_dir):
    before = {p: p.read_bytes() for p in data_dir.rglob("*") if p.is_file()}
    app = viewer_app.create_app(data_dir)
    methods = {m for rule in app.url_map.iter_rules() for m in rule.methods}
    assert methods <= {"GET", "HEAD", "OPTIONS"}
    client = app.test_client()
    assert client.post("/api/menu", json={}).status_code == 405
    assert {p: p.read_bytes() for p in data_dir.rglob("*") if p.is_file()} == before

    for source in UI4VIEW.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not {m for m in imported if m.split(".")[0] in {"meal_planner", "subprocess", "anthropic", "mcp"}}, source
    for source in UI4VIEW.rglob("*.js"):
        assert "claude" not in source.read_text(encoding="utf-8").lower(), source


# --- Main UI: this computer only ----------------------------------------------------------


def test_main_ui_refuses_other_devices(data_dir):
    client = create_main_app(data_dir).test_client()
    assert client.get("/api/ingredients").status_code == 200
    assert client.get("/api/ingredients", environ_base={"REMOTE_ADDR": "::1"}).status_code == 200
    for path in ("/", "/api/ingredients", "/api/settings"):
        response = client.get(path, environ_base=LAN)  # Host is localhost: a forged Host header does not help
        assert response.status_code == 403, path
    refused = client.post("/api/ingredients/suggest", json={"name_zh": "秋葵"}, environ_base=LAN)
    assert refused.status_code == 403

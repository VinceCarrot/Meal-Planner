"""Read the current four-week menu from the planner's data folder (read-only).

This module reads YAML files only. It deliberately does not import the
`meal_planner` package, so the viewer has no path to the Claude integration.
It never writes anything.
"""

from datetime import date, timedelta
from pathlib import Path

import yaml

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
MENU_DAYS = 28  # four weeks


class MenuReadError(Exception):
    """A data file exists but cannot be read."""


def current_menu(data_dir: Path, today: date | None = None) -> dict:
    """The menu to show, with the recipes of its dishes.

    Each menu's newest version is used. The menu whose four weeks contain today
    wins; otherwise the next one to start; otherwise the most recent one.
    Returns {"menu": None} when there is no menu yet.
    """
    today = today or date.today()
    menus = [_read(path) for path in _latest_versions(Path(data_dir) / "menus")]
    menus = [m for m in menus if m and m.get("dinners")]
    if not menus:
        return {"menu": None}

    def start(m):
        return date.fromisoformat(str(m["start_date"]))

    running = [m for m in menus if start(m) <= today < start(m) + timedelta(days=MENU_DAYS)]
    upcoming = sorted((m for m in menus if start(m) > today), key=start)
    chosen = (max(running, key=start) if running else upcoming[0] if upcoming else max(menus, key=start))
    return _view(chosen, Path(data_dir), today)


def _latest_versions(menus_dir: Path) -> list[Path]:
    if not menus_dir.is_dir():
        return []
    latest = []
    for menu_dir in sorted(p for p in menus_dir.iterdir() if p.is_dir()):
        versions = sorted(menu_dir.glob("v[0-9][0-9][0-9]*.yaml"))
        if versions:
            latest.append(versions[-1])
    return latest


def _read(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        raise MenuReadError(f"{path.name}: {e}") from None


def _records(path: Path, key: str, id_field: str) -> dict:
    if not path.exists():
        return {}
    return {r[id_field]: r for r in (_read(path).get(key) or []) if isinstance(r, dict) and id_field in r}


def _view(menu: dict, data_dir: Path, today: date) -> dict:
    dishes = _records(data_dir / "dishes.yaml", "dishes", "dish_id")
    ingredients = _records(data_dir / "ingredients.yaml", "ingredients", "ingredient_id")
    start = date.fromisoformat(str(menu["start_date"]))

    weeks: list[list[dict]] = [[] for _ in range(MENU_DAYS // 7)]
    used = set()
    for dinner in menu["dinners"]:
        day = date.fromisoformat(str(dinner["date"]))
        week = (day - start).days // 7
        if not 0 <= week < len(weeks):
            continue
        ids = list(dinner.get("dish_ids") or [])
        used.update(ids)
        weeks[week].append({
            "date": day.isoformat(),
            "weekday": WEEKDAYS[day.weekday()],
            "is_today": day == today,
            "dishes": [_summary(i, dishes.get(i)) for i in ids],
        })
    for week in weeks:
        week.sort(key=lambda d: d["date"])

    return {
        "menu": {
            "menu_id": menu.get("menu_id"),
            "version": menu.get("version"),
            "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=MENU_DAYS - 1)).isoformat(),
            "diners": [f"{d.get('description')} × {d.get('count')}" for d in menu.get("diners") or []],
            "weeks": [{"n": n + 1, "dinners": w} for n, w in enumerate(weeks)],
        },
        "recipes": {i: _recipe(i, dishes.get(i), ingredients) for i in sorted(used)},
    }


def _summary(dish_id: str, dish: dict | None) -> dict:
    dish = dish or {}
    return {"dish_id": dish_id, "name_zh": dish.get("name_zh") or dish_id, "dish_type": dish.get("dish_type")}


def _recipe(dish_id: str, dish: dict | None, ingredients: dict) -> dict:
    if dish is None:
        return {"dish_id": dish_id, "name_zh": dish_id, "missing": True, "ingredients": [], "steps": []}
    lines = []
    for line in dish.get("ingredients") or []:
        ing = ingredients.get(line.get("ingredient_id")) or {}
        lines.append({
            "name": ing.get("name_zh") or line.get("unmatched_name") or line.get("ingredient_id") or "",
            "quantity": line.get("quantity"),
            "unit": line.get("unit"),
            "note": line.get("note"),
        })
    return {
        "dish_id": dish_id,
        "name_zh": dish.get("name_zh") or dish_id,
        "name_en": dish.get("name_en"),
        "dish_type": dish.get("dish_type"),
        "servings": dish.get("servings"),
        "ingredients": lines,
        "steps": list(dish.get("steps") or []),
    }

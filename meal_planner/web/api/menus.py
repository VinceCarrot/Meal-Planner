"""Menu planning, saving and history."""

from datetime import date

from flask import Blueprint, request

from ...catalogue import DataError, DataIssue
from ...menus import plan_new_menu, prepare, save_new_menu, task_constraints_from_input
from ...models import Diner, PreferencesFile
from ...vocab import TaskScope
from ..helpers import NotFound, body, dump, load, settings
from ..serialize import dinners_from_input, menu_view, plan_view

bp = Blueprint("menus", __name__)


def _start_date(data) -> date:
    try:
        start = date.fromisoformat(str(data["start_date"]))
    except ValueError:
        raise DataError([DataIssue("request", "start_date", "日期格式应为 YYYY-MM-DD")]) from None
    if start.weekday() != 0:
        raise DataError([DataIssue("request", "start_date", f"{start} 不是星期一")])
    return start


@bp.post("/menus/plan")
def plan():
    store, cat = load()
    data = body()
    task_constraints = task_constraints_from_input(data.get("task_constraints", []), TaskScope.MENU_GENERATION, cat)
    current = settings()
    ctx, effective, result = plan_new_menu(store, cat, current, _start_date(data), task_constraints)
    return plan_view(result, ctx.dishes, effective, current.candidates)


@bp.post("/menus")
def save():
    """Save a planned menu as version 1 of a new menu; the server validates it again."""
    store, cat = load()
    data = body()
    task_constraints = task_constraints_from_input(data.get("task_constraints", []), TaskScope.MENU_GENERATION, cat)
    ctx, effective = prepare(store, cat, settings(), _start_date(data), task_constraints, TaskScope.MENU_GENERATION)
    diners = [Diner.model_validate(d) for d in data["diners"]]
    dinners = dinners_from_input(data["dinners"])
    menu, report = save_new_menu(store, cat, ctx, effective, diners, dinners, data.get("change_note") or None)
    return {"menu_id": menu.menu_id, "version": menu.version, "status": report.status.value}, 201


@bp.get("/menus")
def list_menus():
    store, cat = load()
    rows = []
    for menu_id in reversed(store.menu_ids()):
        versions = store.menu_versions(menu_id)
        if not versions:
            continue
        latest = store.load_menu(cat, menu_id)
        rows.append({
            "menu_id": menu_id,
            "versions": versions,
            "start_date": latest.start_date.isoformat(),
            "status": (latest.validation_report or {}).get("status"),
            "created_at": latest.created_at.isoformat(),
            "change_note": latest.change_note,
        })
    return rows


@bp.get("/menus/<menu_id>")
def get_menu(menu_id):
    store, cat = load()
    versions = store.menu_versions(menu_id)
    if not versions:
        raise NotFound(f"菜单 {menu_id} 不存在")
    version = request.args.get("version", type=int)
    if version is not None and version not in versions:
        raise NotFound(f"菜单 {menu_id} 没有版本 {version}")
    return menu_view(store.load_menu(cat, menu_id, version), cat, versions)


@bp.get("/preferences")
def get_preferences():
    _, cat = load()
    return dump(cat.preferences)


@bp.put("/preferences/diners")
def put_default_diners():
    store, cat = load()
    diners = [dump(Diner.model_validate(d)) for d in body()["diners"]]
    preferences = PreferencesFile.model_validate(dump(cat.preferences) | {"default_diners": diners})
    cat = store.save_preferences(cat, preferences)
    return dump(cat.preferences)

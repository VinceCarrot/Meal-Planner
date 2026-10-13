"""Menu planning, saving and history."""

from datetime import date
from io import BytesIO

from flask import Blueprint, current_app, request, send_file

from ...catalogue import DataError, DataIssue
from ...adjust import menu_changes, propose_replacement, save_adjusted_version
from ...menus import plan_new_menu, prepare, save_new_menu, task_constraints_from_input
from ...models import Diner, PreferencesFile
from ...pdf_export import build_menu_pdf, dishes_in_order
from ...settings import LLMTask
from ...translation import load_translations, save_translations, source_hash, translate_dishes
from ...vocab import FeedbackScope, TaskScope
from ..helpers import NotFound, body, dump, llm, load, settings
from ..serialize import changes_view, dinners_from_input, menu_view, plan_view, proposal_view

ADJ = TaskScope.MENU_ADJUSTMENT

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
    menu = _version(store, cat, menu_id, request.args.get("version", type=int))
    view = menu_view(menu, cat, versions)
    if menu.based_on_version:
        base = store.load_menu(cat, menu_id, menu.based_on_version)
        view["changes"] = changes_view(menu_changes(base.dinners, menu.dinners), {d.dish_id: d for d in cat.dishes.dishes})
    return view


def _version(store, cat, menu_id, version):
    versions = store.menu_versions(menu_id)
    if not versions:
        raise NotFound(f"菜单 {menu_id} 不存在")
    if version is not None and version not in versions:
        raise NotFound(f"菜单 {menu_id} 没有版本 {version}")
    return store.load_menu(cat, menu_id, version)


@bp.post("/menus/<menu_id>/adjust/propose")
def propose_adjustment(menu_id):
    """Propose replacing one dish; nothing is saved."""
    store, cat = load()
    data = body()
    base = _version(store, cat, menu_id, data.get("version"))
    task_constraints = task_constraints_from_input(data.get("task_constraints", []), ADJ, cat)
    ctx, effective = prepare(store, cat, settings(), base.start_date, task_constraints, ADJ, exclude_menu=menu_id)
    proposal = propose_replacement(ctx, effective, base, date.fromisoformat(data["date"]), str(data["dish_id"]))
    return proposal_view(proposal, ctx.dishes, effective)


@bp.post("/menus/<menu_id>/adjust/save")
def save_adjustment(menu_id):
    """Save confirmed dinners as a new version (validated again) and record optional dislike feedback."""
    store, cat = load()
    data = body()
    base = _version(store, cat, menu_id, int(data["version"]))
    task_constraints = task_constraints_from_input(data.get("task_constraints", []), ADJ, cat)
    ctx, effective = prepare(store, cat, settings(), base.start_date, task_constraints, ADJ, exclude_menu=menu_id)
    note = str(data.get("change_note") or "").strip()
    if not note:
        raise DataError([DataIssue("request", "change_note", "请填写这次修改的原因")])
    feedback = data.get("feedback")
    if feedback:
        feedback = (str(feedback["dish_id"]), FeedbackScope(feedback["scope"]), feedback.get("note") or None)
    menu, report = save_adjusted_version(store, cat, ctx, effective, base, dinners_from_input(data["dinners"]), note, feedback)
    return {"menu_id": menu.menu_id, "version": menu.version, "status": report.status.value}, 201


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


# --- English PDF export --------------------------------------------------------------------


def _current(cache, dishes, ingredients, dish_id) -> bool:
    return dish_id in cache and cache[dish_id].source_hash == source_hash(dishes[dish_id], ingredients)


@bp.post("/menus/<menu_id>/export/translate")
def translate_menu(menu_id):
    """Translate the menu's recipes whose English version is missing or out of date."""
    store, cat = load()
    menu = _version(store, cat, menu_id, body().get("version"))
    dishes = {d.dish_id: d for d in cat.dishes.dishes}
    ingredients = {i.ingredient_id: i for i in cat.ingredients.ingredients}
    order = dishes_in_order(menu)
    data_dir = current_app.config["DATA_DIR"]
    cache = load_translations(data_dir)
    already = sum(_current(cache, dishes, ingredients, k) for k in order)
    cache, failed = translate_dishes(llm(LLMTask.TRANSLATION), [dishes[k] for k in order], ingredients, cache)
    save_translations(data_dir, cache)
    return {
        "dishes": len(order),
        "translated_now": len(order) - already - len(failed),
        "failed": [{"dish_id": k, "name_zh": dishes[k].name_zh, "error": e} for k, e in failed.items()],
        "warnings": [
            {"dish_id": k, "name_zh": dishes[k].name_zh, "warnings": list(cache[k].warnings)}
            for k in order if k in cache and cache[k].warnings
        ],
    }


@bp.get("/menus/<menu_id>/export.pdf")
def export_pdf(menu_id):
    """The English recipe book of one menu version, from up-to-date translations only."""
    store, cat = load()
    menu = _version(store, cat, menu_id, request.args.get("version", type=int))
    dishes = {d.dish_id: d for d in cat.dishes.dishes}
    ingredients = {i.ingredient_id: i for i in cat.ingredients.ingredients}
    cache = load_translations(current_app.config["DATA_DIR"])
    order = dishes_in_order(menu)
    stale = [k for k in order if not _current(cache, dishes, ingredients, k)]
    if stale:
        raise DataError([DataIssue("translations.yaml", k, "缺少最新的英文翻译，请先翻译") for k in stale])
    pdf = build_menu_pdf(menu, dishes, {k: cache[k] for k in order})
    return send_file(BytesIO(pdf), mimetype="application/pdf", as_attachment=True,
                     download_name=f"{menu_id}_v{menu.version}_recipes_en.pdf")

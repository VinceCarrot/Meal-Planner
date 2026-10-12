"""Menu workflow used by the Web UI: task constraints, planning and saving versions.

Kept free of HTTP so that it can be tested directly. Every saved version carries a
validation report computed here on the server, never one supplied by a client.
"""

from collections.abc import Sequence
from datetime import date, datetime, timedelta

from pydantic import ValidationError

from .catalogue import Catalogue, DataError, DataIssue, constraint_ref_errors
from .constraints import EffectiveConstraintSet, build_effective_set
from .models import Constraint, Dinner, Diner, MenuVersion
from .plan_context import PlanContext, make_context
from .planner import PlanResult, plan_menu
from .settings import Settings
from .store import DataStore
from .validator import ValidationReport, validate_menu
from .vocab import ConstraintSource, TaskScope

HISTORY_DAYS = 28  # earlier dinners considered for repetition across plans (longest repeat window)


def task_constraints_from_input(raw: Sequence[dict], task: TaskScope, cat: Catalogue) -> list[Constraint]:
    """Validate task constraints sent by a client (already parsed and possibly edited by the user)."""
    issues, result = [], []
    ingredient_ids = cat.ingredient_ids
    for n, item in enumerate(raw):
        loc = f"task_constraints[{n}]"
        try:
            c = Constraint.model_validate(item)
        except ValidationError as e:
            issues += [DataIssue("request", loc, err["msg"]) for err in e.errors()]
            continue
        if c.source != ConstraintSource.TASK or tuple(c.scope) != (task,):
            issues.append(DataIssue("request", loc, f"must be a task constraint for {task} only"))
        issues += [DataIssue("request", loc, msg) for msg in constraint_ref_errors(c, ingredient_ids)]
        result.append(c)
    ids = [c.constraint_id for c in result]
    if len(set(ids)) != len(ids):
        issues.append(DataIssue("request", "task_constraints", "duplicate constraint IDs"))
    if issues:
        raise DataError(issues)
    return result


def menu_history(store: DataStore, cat: Catalogue, before: date, exclude_menu: str | None = None) -> list[Dinner]:
    """Dinners from the latest version of other saved menus in the days before `before`."""
    earliest = before - timedelta(days=HISTORY_DAYS)
    dinners = []
    for menu_id in store.menu_ids():
        if menu_id == exclude_menu or not store.menu_versions(menu_id):
            continue
        menu = store.load_menu(cat, menu_id)
        dinners += [d for d in menu.dinners if earliest <= d.date < before]
    return dinners


def prepare(
    store: DataStore, cat: Catalogue, settings: Settings, start_date: date,
    task_constraints: Sequence[Constraint], task: TaskScope, exclude_menu: str | None = None,
) -> tuple[PlanContext, EffectiveConstraintSet]:
    history = menu_history(store, cat, start_date, exclude_menu)
    ctx = make_context(cat, settings, start_date, history)
    return ctx, build_effective_set(cat.constraints.constraints, task_constraints, task)


def plan_new_menu(
    store: DataStore, cat: Catalogue, settings: Settings, start_date: date, task_constraints: Sequence[Constraint]
) -> tuple[PlanContext, EffectiveConstraintSet, PlanResult]:
    ctx, effective = prepare(store, cat, settings, start_date, task_constraints, TaskScope.MENU_GENERATION)
    return ctx, effective, plan_menu(ctx, effective)


def save_new_menu(
    store: DataStore,
    cat: Catalogue,
    ctx: PlanContext,
    effective: EffectiveConstraintSet,
    diners: Sequence[Diner],
    dinners: Sequence[Dinner],
    change_note: str | None = None,
) -> tuple[MenuVersion, ValidationReport]:
    """Validate `dinners` again and store them as version 1 of a new menu."""
    report = validate_menu(dinners, ctx, effective)
    menu = MenuVersion(
        menu_id=_next_menu_id(store),
        version=1,
        start_date=ctx.start_date,
        diners=tuple(diners),
        dinners=tuple(sorted(dinners, key=lambda d: d.date)),
        constraint_snapshot=effective.constraints,
        validation_report=report.model_dump(mode="json"),
        change_note=change_note,
        created_at=datetime.now().replace(microsecond=0),
    )
    store.save_menu_version(cat, menu)
    return menu, report


def _next_menu_id(store: DataStore) -> str:
    numbers = [int(m[1:]) for m in store.menu_ids() if m[1:].isdigit()]
    return f"M{max(numbers, default=0) + 1:03d}"

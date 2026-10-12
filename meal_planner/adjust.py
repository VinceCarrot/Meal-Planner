"""Local menu adjustment: replace one dish, widening the scope only when needed.

Scopes are tried in order: the dish alone, its whole dinner, its week, the whole
menu. Dates outside the scope keep exactly their dishes. Inside a wider scope the
existing dishes are preferred (each dropped dish costs `penalty_change`), so
unrelated approved items stay unless a hard constraint requires a change. The
replaced dish is never put back on its date. Every proposal is validated
independently, and nothing is saved until the user confirms.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from .catalogue import Catalogue
from .constraints import EffectiveConstraintSet
from .models import Dinner, Feedback, MenuVersion, PreferencesFile
from .plan_context import PlanContext
from .planner import plan_menu
from .store import DataStore
from .validator import PlanStatus, ValidationReport, validate_menu
from .vocab import FeedbackScope

SCOPES = ("dish", "dinner", "week", "menu")
ACCEPTED = (PlanStatus.FEASIBLE, PlanStatus.FEASIBLE_WITH_UNRESOLVED)


@dataclass(frozen=True)
class Attempt:
    scope: str
    status: PlanStatus
    message: str


@dataclass(frozen=True)
class Change:
    date: date
    removed: tuple[str, ...]
    added: tuple[str, ...]


@dataclass(frozen=True)
class AdjustmentProposal:
    status: PlanStatus
    scope: str | None  # the scope that produced the proposal
    dinners: tuple[Dinner, ...] | None
    report: ValidationReport | None
    changes: tuple[Change, ...]
    attempts: tuple[Attempt, ...]  # every scope tried, in order


def propose_replacement(
    ctx: PlanContext, effective: EffectiveConstraintSet, menu: MenuVersion, target_date: date, target_dish: str
) -> AdjustmentProposal:
    current = {d.date: d.dish_ids for d in menu.dinners}
    if target_dish not in current.get(target_date, ()):
        raise ValueError(f"{target_dish} is not served on {target_date} in {menu.menu_id} v{menu.version}")

    banned = {(target_date, target_dish)}
    attempts = []
    for scope in SCOPES:
        free = _scope_dates(scope, ctx.dates, target_date)
        keep = {d: tuple(k for k in ids if (d, k) not in banned) for d, ids in current.items()}
        fixed = {d: ids for d, ids in keep.items() if d not in free}
        prefer = {d: ids for d, ids in keep.items() if d in free}
        if scope == "dish":
            fixed, prefer = keep, {}

        result = plan_menu(ctx, effective, fixed=fixed, free_dates=free, banned=banned, prefer=prefer,
                           diagnose=scope == SCOPES[-1])
        if result.status in ACCEPTED:
            return AdjustmentProposal(result.status, scope, result.dinners, result.report,
                                      tuple(menu_changes(menu.dinners, result.dinners)), tuple(attempts) + (Attempt(scope, result.status, ""),))
        attempts.append(Attempt(scope, result.status, "; ".join(result.messages) or _failed_summary(result.report)))
        if result.status == PlanStatus.BLOCKED:
            break  # a constraint problem; widening the scope cannot help

    return AdjustmentProposal(attempts[-1].status, None, None, None, (), tuple(attempts))


def save_adjusted_version(
    store: DataStore,
    cat: Catalogue,
    ctx: PlanContext,
    effective: EffectiveConstraintSet,
    base: MenuVersion,
    dinners: Sequence[Dinner],
    change_note: str,
    feedback: tuple[str, FeedbackScope, str | None] | None = None,
) -> tuple[MenuVersion, ValidationReport]:
    """Validate `dinners` again and store them as the next version of `base`'s menu.

    `feedback` = (dish_id, scope, note) records a dislike in preferences.yaml.
    """
    report = validate_menu(dinners, ctx, effective)
    menu = MenuVersion(
        menu_id=base.menu_id,
        version=max(store.menu_versions(base.menu_id)) + 1,
        based_on_version=base.version,
        start_date=base.start_date,
        diners=base.diners,
        dinners=tuple(sorted(dinners, key=lambda d: d.date)),
        constraint_snapshot=effective.constraints,
        validation_report=report.model_dump(mode="json"),
        change_note=change_note,
        created_at=datetime.now().replace(microsecond=0),
    )
    new_feedback = None
    if feedback:
        dish_id, scope, note = feedback
        numbers = [int(f.feedback_id[1:]) for f in cat.preferences.feedback]
        new_feedback = Feedback(
            feedback_id=f"F{max(numbers, default=0) + 1:03d}", dish_id=dish_id, kind="dislike", scope=scope,
            menu_id=base.menu_id, note=note, created_at=menu.created_at,
        )
    store.save_menu_version(cat, menu)
    if new_feedback:
        store.save_preferences(cat, PreferencesFile.model_validate(
            cat.preferences.model_dump() | {"feedback": cat.preferences.feedback + (new_feedback,)}))
    return menu, report


def menu_changes(old: Sequence[Dinner], new: Sequence[Dinner]) -> list[Change]:
    """Per date, the dishes removed and added between two versions."""
    before = {d.date: set(d.dish_ids) for d in old}
    changes = []
    for dinner in new:
        removed = before.get(dinner.date, set()) - set(dinner.dish_ids)
        added = set(dinner.dish_ids) - before.get(dinner.date, set())
        if removed or added:
            changes.append(Change(dinner.date, tuple(sorted(removed)), tuple(sorted(added))))
    return changes


def _scope_dates(scope: str, dates: list[date], target: date) -> set[date]:
    if scope in ("dish", "dinner"):
        return {target}
    if scope == "week":
        week = dates.index(target) // 5
        return set(dates[week * 5:week * 5 + 5])
    return set(dates)


def _failed_summary(report: ValidationReport | None) -> str:
    if report is None:
        return ""
    failed = [r.constraint_id for r in report.results if r.status == "failed" and r.strictness == "hard"]
    return f"hard constraints not met: {', '.join(failed)}" if failed else ""

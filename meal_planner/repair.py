"""Local repair of whole-meal similarity after solving (architecture §6.9).

Starting from a valid menu, repeatedly replace one dish in a dinner involved in
the worst meal-similarity violation with another dish of the same type. A change
is kept only if the independent validator reports fewer hard violations, or the
same number with a lower total penalty. The search is deterministic.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from .constraint_types import MealSimilarity
from .constraints import EffectiveConstraintSet
from .models import Dinner
from .plan_context import PlanContext
from .validator import ValidationReport, validate_menu
from .vocab import Strictness


@dataclass(frozen=True)
class RepairStats:
    steps: int
    penalty_before: int
    penalty_after: int
    seconds: float


def repair_meal_similarity(
    ctx: PlanContext,
    effective: EffectiveConstraintSet,
    dinners: Sequence[Dinner],
    editable: Callable[[date, str], bool] = lambda d, k: True,
) -> tuple[list[Dinner], RepairStats]:
    started = time.monotonic()
    current = list(dinners)
    report = validate_menu(current, ctx, effective)
    before = report.penalty_total
    rules = [c.execution for c in effective.constraints if isinstance(c.execution, MealSimilarity)]
    if not rules or report.structural_errors:
        return current, RepairStats(0, before, before, time.monotonic() - started)

    steps = 0
    while steps < ctx.settings.repair_max_steps:
        improved = _first_improvement(ctx, effective, current, report, rules, editable)
        if improved is None:
            break
        current, report = improved
        steps += 1
    return current, RepairStats(steps, before, report.penalty_total, time.monotonic() - started)


def _key(report: ValidationReport) -> tuple[int, int]:
    hard_violations = sum(len(r.violations) for r in report.results if r.strictness == Strictness.HARD)
    return hard_violations + len(report.structural_errors), report.penalty_total


def _first_improvement(ctx, effective, current, report, rules, editable):
    best_key = _key(report)
    for day in _dates_to_change(ctx, current, rules):
        index = next(n for n, d in enumerate(current) if d.date == day)
        dinner = current[index]
        for pos, dish_id in enumerate(dinner.dish_ids):
            if not editable(day, dish_id):
                continue
            dish_type = ctx.dishes[dish_id].dish_type
            for candidate in sorted(ctx.dishes):
                if ctx.dishes[candidate].dish_type != dish_type or candidate in dinner.dish_ids:
                    continue
                ids = dinner.dish_ids[:pos] + (candidate,) + dinner.dish_ids[pos + 1:]
                trial = current[:index] + [Dinner(date=day, dish_ids=ids)] + current[index + 1:]
                trial_report = validate_menu(trial, ctx, effective)
                if not trial_report.structural_errors and _key(trial_report) < best_key:
                    return trial, trial_report
    return None


def _dates_to_change(ctx: PlanContext, dinners: list[Dinner], rules: list[MealSimilarity]) -> list[date]:
    """Dates in meal-similarity violations, worst pair first."""
    scored = []
    for i, d1 in enumerate(dinners):
        for d2 in dinners[i + 1:]:
            gap = (d2.date - d1.date).days
            for rule in rules:
                threshold = rule.max_similarity or ctx.settings.default_meal_similarity_threshold
                if gap < rule.window_weeks * 7:
                    score = ctx.meal_similarity(d1.dish_ids, d2.dish_ids).normalized
                    if score > threshold:
                        scored.append((-score, d1.date, d2.date))
    ordered = []
    for _, a, b in sorted(scored):
        ordered += [day for day in (a, b) if day not in ordered]
    return ordered

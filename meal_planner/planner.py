"""Plan a 20-dinner menu: check inputs, solve, repair, validate, explain.

The returned status always comes from the independent validator when a menu
exists. When no menu exists the result explains why: blocking constraint issues,
catalogue shortfalls, or hard constraints whose relaxation would help. Nothing
is relaxed automatically; relaxations are only suggested for user approval.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date

from .checks import counted_by, describe_counted
from .constraint_types import COUNT_TYPES, DishCount, DishTypeCount, ExactRepeatWindow, MatchingDishCount
from .constraints import EffectiveConstraintSet
from .models import Constraint, Dinner
from .plan_context import PlanContext
from .repair import RepairStats, repair_meal_similarity
from .solver import SolverResult, hard_excluded_dishes, solve
from .validator import PlanStatus, ValidationReport, validate_menu
from .vocab import DishType, Strictness

DIAGNOSIS_TIME_LIMIT_S = 10


@dataclass(frozen=True)
class CatalogueGap:
    """Not enough eligible approved dishes for a hard count rule (dish_type None: any type)."""

    constraint_id: str
    dish_type: DishType | None
    eligible_dishes: int
    max_uses_per_dish: int
    servings_needed: int
    what: str | None = None  # what the rule counts, when more specific than the dish type

    @property
    def additional_dishes_needed(self) -> int:
        shortfall = self.servings_needed - self.eligible_dishes * self.max_uses_per_dish
        return math.ceil(shortfall / self.max_uses_per_dish)

    def describe(self) -> str:
        what = self.what or (f"{self.dish_type} dishes" if self.dish_type else "dishes")
        return (
            f"{self.constraint_id}: needs {self.servings_needed} servings of {what}, but only "
            f"{self.eligible_dishes} eligible {what} can be served at most {self.max_uses_per_dish} time(s) each; "
            f"at least {self.additional_dishes_needed} more approved {what} needed"
        )


@dataclass(frozen=True)
class PlanResult:
    status: PlanStatus
    dinners: tuple[Dinner, ...] | None = None
    report: ValidationReport | None = None
    messages: tuple[str, ...] = ()
    gaps: tuple[CatalogueGap, ...] = ()
    # Hard constraints each of which, if relaxed alone, would make planning feasible.
    relaxation_candidates: tuple[str, ...] = ()
    solver: SolverResult | None = None
    repair: RepairStats | None = None


def plan_menu(
    ctx: PlanContext,
    effective: EffectiveConstraintSet,
    *,
    fixed: Mapping[date, Sequence[str]] | None = None,
    free_dates: set[date] | None = None,
    banned: set[tuple[date, str]] | None = None,
    prefer: Mapping[date, Sequence[str]] | None = None,
    diagnose: bool = True,
) -> PlanResult:
    """`diagnose`: when the model is infeasible, re-solve without each hard constraint to name the culprits."""
    if not effective.ready:
        return PlanResult(PlanStatus.BLOCKED, messages=tuple(f"{', '.join(i.constraint_ids)}: {i.message}" for i in effective.issues))
    constraints = list(effective.constraints)
    if not any(isinstance(c.execution, (DishCount, MatchingDishCount)) and c.execution.min for c in constraints):
        return PlanResult(PlanStatus.BLOCKED, messages=(
            "specify how many dishes each dinner should have (a dish_count or matching_dish_count constraint with a minimum)",))

    gaps = capacity_gaps(ctx, constraints)
    if gaps:
        return PlanResult(PlanStatus.INFEASIBLE, messages=tuple(g.describe() for g in gaps) + _not_frequent_note(ctx), gaps=tuple(gaps))

    result = solve(ctx, constraints, fixed=fixed, free_dates=free_dates, banned=banned, prefer=prefer)
    if result.status == "infeasible":
        candidates = _relaxation_candidates(ctx, constraints, fixed, free_dates, banned) if diagnose else []
        message = (
            "no menu satisfies all hard constraints; relaxing any one of these would allow a plan: " + ", ".join(candidates)
            if candidates
            else "no menu satisfies all hard constraints together"
            + ("; no single constraint is solely responsible" if diagnose else "")
        )
        return PlanResult(PlanStatus.INFEASIBLE, messages=(message,) + _not_frequent_note(ctx),
                          relaxation_candidates=tuple(candidates), solver=result)
    if result.dinners is None:
        return PlanResult(
            PlanStatus.NO_SOLUTION_FOUND,
            messages=(f"no menu found within {ctx.settings.time_limit_s:.0f}s (solver status: {result.status}); feasibility is unknown",),
            solver=result,
        )

    fixed, prefer, banned = fixed or {}, prefer or {}, banned or set()

    def editable(day: date, dish_id: str) -> bool:
        kept = tuple(fixed.get(day, ())) + tuple(prefer.get(day, ()))
        return (free_dates is None or day in free_dates) and dish_id not in kept

    def allowed(day: date, dish_id: str) -> bool:
        return (day, dish_id) not in banned

    dinners, stats = repair_meal_similarity(ctx, effective, result.dinners, editable, allowed)
    report = validate_menu(dinners, ctx, effective)
    return PlanResult(report.status, dinners=tuple(dinners), report=report, solver=result, repair=stats)


def _not_frequent_note(ctx: PlanContext) -> tuple[str, ...]:
    if ctx.selectable is None:
        return ()
    left_out = len(ctx.dishes) - len(ctx.selectable & ctx.dishes.keys())
    return (f"{left_out} approved dish(es) not marked 常用 were not considered",) if left_out else ()


def max_uses_per_dish(dates: Sequence[date], window_days: int | None) -> int:
    """How often one dish can appear in the plan when repeats must be `window_days` apart."""
    if window_days is None:
        return len(dates)
    uses, last = 0, None
    for d in dates:
        if last is None or (d - last).days >= window_days:
            uses, last = uses + 1, d
    return uses


def capacity_gaps(ctx: PlanContext, constraints: Sequence[Constraint]) -> list[CatalogueGap]:
    """Proven shortfalls: hard count minimums that the eligible catalogue cannot cover."""
    hard = [c for c in constraints if c.strictness == Strictness.HARD]
    windows = [c.execution.weeks * 7 for c in hard if isinstance(c.execution, ExactRepeatWindow)]
    window = max(windows, default=None)
    excluded = hard_excluded_dishes(ctx, hard)
    eligible = [d for k, d in ctx.dishes.items() if k not in excluded and ctx.is_selectable(k)]

    gaps = []
    for c in hard:
        rule = c.execution
        if not isinstance(rule, COUNT_TYPES) or not rule.min:
            continue
        dates = [d for d in ctx.dates if rule.applies_on(d.isoweekday())]
        uses = max_uses_per_dish(dates, window)
        if isinstance(rule, MatchingDishCount):
            dish_type = rule.dish_types[0] if len(rule.dish_types) == 1 else None
            what = describe_counted(rule)
        else:
            dish_type = rule.dish_type if isinstance(rule, DishTypeCount) else None
            what = None
        count = sum(1 for d in eligible if counted_by(d, rule, ctx.ingredients))
        needed = len(dates) * rule.min
        if count * uses < needed:
            gaps.append(CatalogueGap(c.constraint_id, dish_type, count, uses, needed, what))
    return gaps


def _relaxation_candidates(ctx, constraints, fixed, free_dates, banned) -> list[str]:
    """Hard constraints whose removal alone makes the model feasible (each re-solve is time-limited)."""
    candidates = []
    for c in constraints:
        if c.strictness != Strictness.HARD or c.execution is None:
            continue
        others = [o for o in constraints if o is not c]
        quick = replace(ctx, settings=ctx.settings.model_copy(update={"time_limit_s": DIAGNOSIS_TIME_LIMIT_S}))
        if solve(quick, others, fixed=fixed, free_dates=free_dates, banned=banned).status in ("optimal", "feasible"):
            candidates.append(c.constraint_id)
    return candidates

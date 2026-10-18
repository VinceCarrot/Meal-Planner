"""CP-SAT model for the 20-dinner plan (ADR-017).

One boolean per (dinner date, eligible dish). Hard constraints become model
constraints; soft constraints become penalty terms with the same weights the
validator uses. Whole-meal similarity is not modelled here; it is evaluated and
repaired after solving (architecture §6.9). A solver result is only a candidate:
the planner always validates it independently.
"""

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from ortools.sat.python import cp_model

from .checks import counted_by, exclusion_hits, shared_ingredients
from .constraint_types import (
    COUNT_TYPES,
    AnyOf,
    DishCount,
    DishSimilarity,
    ExactRepeatWindow,
    IngredientExclusion,
    NoSharedIngredients,
)
from .models import Constraint, Dinner
from .plan_context import PlanContext
from .vocab import DishType, Strictness

DISH_TYPE_ORDER = {DishType.MEAT: 0, DishType.MIXED: 1, DishType.VEGETARIAN: 2, DishType.SOUP: 3}

_STATUS = {
    cp_model.OPTIMAL: "optimal",
    cp_model.FEASIBLE: "feasible",
    cp_model.INFEASIBLE: "infeasible",
    cp_model.UNKNOWN: "unknown",
    cp_model.MODEL_INVALID: "invalid",
}


@dataclass(frozen=True)
class SolverResult:
    status: str  # optimal | feasible | infeasible | unknown (time limit, no solution) | invalid
    dinners: tuple[Dinner, ...] | None
    objective: int | None
    wall_time_s: float
    num_variables: int


def hard_excluded_dishes(ctx: PlanContext, constraints: Sequence[Constraint]) -> set[str]:
    excluded = set()
    for c in constraints:
        if isinstance(c.execution, IngredientExclusion) and c.strictness == Strictness.HARD:
            excluded |= {k for k, dish in ctx.dishes.items() if exclusion_hits(dish, c.execution, ctx.ingredients)}
    return excluded


def solve(
    ctx: PlanContext,
    constraints: Sequence[Constraint],
    *,
    fixed: Mapping[date, Sequence[str]] | None = None,
    free_dates: set[date] | None = None,
    banned: set[tuple[date, str]] | None = None,
    prefer: Mapping[date, Sequence[str]] | None = None,
    time_limit_s: float | None = None,
) -> SolverResult:
    """Solve the plan.

    `fixed` dishes are forced; dates outside `free_dates` get only their fixed dishes;
    `banned` (date, dish) pairs are never chosen; dropping a `prefer` dish costs
    `penalty_change` points (used to keep an existing menu where possible).
    """
    started = time.monotonic()
    fixed = fixed or {}
    banned = banned or set()
    prefer = prefer or {}
    for dish_id in {k for ks in fixed.values() for k in ks}:
        if dish_id not in ctx.dishes:
            raise ValueError(f"fixed dish '{dish_id}' is not an approved dish")

    dates = ctx.dates
    fixed_ids = {k for ks in fixed.values() for k in ks}
    candidates = {k for k in ctx.dishes if ctx.is_selectable(k)} - hard_excluded_dishes(ctx, constraints)
    dishes = sorted(candidates | fixed_ids)

    m = cp_model.CpModel()
    x = {(i, k): m.new_bool_var(f"x_{i}_{k}") for i in range(len(dates)) for k in dishes}
    terms: list[tuple[int, cp_model.IntVar]] = []  # (penalty points, variable)

    for i, d in enumerate(dates):
        m.add(sum(x[i, k] for k in dishes) >= 1)
        for k in fixed.get(d, ()):
            m.add(x[i, k] == 1)
        if free_dates is not None and d not in free_dates:
            for k in dishes:
                if k not in fixed.get(d, ()):
                    m.add(x[i, k] == 0)
        for k in dishes:
            if (d, k) in banned:
                m.add(x[i, k] == 0)
        for k in prefer.get(d, ()):
            if (i, k) in x and (d, k) not in banned:
                dropped = m.new_bool_var(f"dropped_{i}_{k}")
                m.add(dropped + x[i, k] == 1)
                terms.append((ctx.settings.penalty_change, dropped))
        terms += [(ctx.settings.penalty_disliked, x[i, k]) for k in dishes if k in ctx.disliked]

    for c in constraints:
        rule, hard = c.execution, c.strictness == Strictness.HARD
        if isinstance(rule, COUNT_TYPES):
            terms += _count(m, x, ctx, dates, dishes, rule, hard)
        elif isinstance(rule, AnyOf):
            terms += _any_of(m, x, ctx, dates, dishes, rule, hard)
        elif isinstance(rule, NoSharedIngredients):
            terms += _no_shared(m, x, ctx, dates, dishes, rule, hard)
        elif isinstance(rule, IngredientExclusion) and not hard:
            hits = [k for k in dishes if exclusion_hits(ctx.dishes[k], rule, ctx.ingredients)]
            terms += [(ctx.settings.penalty_soft_exclusion, x[i, k]) for i in range(len(dates)) for k in hits]
        elif isinstance(rule, ExactRepeatWindow):
            terms += _repeat(m, x, ctx, dates, dishes, rule.weeks * 7, hard)
        elif isinstance(rule, DishSimilarity):
            terms += _similarity(m, x, ctx, dates, dishes, rule, hard, _max_dishes_per_dinner(constraints))

    m.minimize(sum(points * var for points, var in terms if points))

    limit = time_limit_s or ctx.settings.time_limit_s
    solver = cp_model.CpSolver()
    # Deterministic search: the same input gives the same menu regardless of machine load.
    # Deterministic time roughly tracks seconds; the wall-clock limit is only a safety net.
    solver.parameters.max_deterministic_time = limit
    solver.parameters.max_time_in_seconds = limit * 3
    solver.parameters.num_workers = ctx.settings.workers
    solver.parameters.interleave_search = True
    solver.parameters.random_seed = 0
    status = _STATUS.get(solver.solve(m), "unknown")

    dinners = None
    if status in ("optimal", "feasible"):
        dinners = tuple(
            Dinner(date=d, dish_ids=tuple(sorted(
                (k for k in dishes if solver.value(x[i, k])),
                key=lambda k: (DISH_TYPE_ORDER[ctx.dishes[k].dish_type], k),
            )))
            for i, d in enumerate(dates)
        )
    return SolverResult(
        status=status,
        dinners=dinners,
        objective=round(solver.objective_value) if dinners else None,
        wall_time_s=time.monotonic() - started,
        num_variables=len(m.proto.variables),
    )


def _members(ctx, dishes, rule) -> list[str]:
    return [k for k in dishes if counted_by(ctx.dishes[k], rule, ctx.ingredients)]


def _count(m, x, ctx, dates, dishes, rule, hard):
    members = _members(ctx, dishes, rule)
    terms = []
    for i, d in enumerate(dates):
        if not rule.applies_on(d.isoweekday()):
            continue
        count = sum(x[i, k] for k in members)
        if hard:
            if rule.min is not None:
                m.add(count >= rule.min)
            if rule.max is not None:
                m.add(count <= rule.max)
            continue
        if rule.min is not None:
            under = m.new_int_var(0, rule.min, f"under_{i}")
            m.add(under >= rule.min - count)
            terms.append((ctx.settings.penalty_soft_count, under))
        if rule.max is not None:
            over = m.new_int_var(0, len(members), f"over_{i}")
            m.add(over >= count - rule.max)
            terms.append((ctx.settings.penalty_soft_count, over))
    return terms


def _any_of(m, x, ctx, dates, dishes, rule: AnyOf, hard):
    """Per dinner, one indicator per alternative; an alternative's bounds hold when its indicator is set."""
    members = [_members(ctx, dishes, alt) for alt in rule.alternatives]
    terms = []
    for i, d in enumerate(dates):
        if not rule.applies_on(d.isoweekday()):
            continue
        chosen = []
        for n, (alt, alt_members) in enumerate(zip(rule.alternatives, members)):
            h = m.new_bool_var(f"anyof_{i}_{n}")
            count = sum(x[i, k] for k in alt_members)
            if alt.min is not None:
                m.add(count >= alt.min).only_enforce_if(h)
            if alt.max is not None:
                m.add(count <= alt.max).only_enforce_if(h)
            chosen.append(h)
        if hard:
            m.add_bool_or(chosen)
        else:
            missed = m.new_bool_var(f"anyof_missed_{i}")
            m.add_bool_or([*chosen, missed])
            terms.append((ctx.settings.penalty_soft_count, missed))
    return terms


def _no_shared(m, x, ctx, dates, dishes, rule: NoSharedIngredients, hard):
    pairs = [
        (a, b)
        for n, a in enumerate(dishes)
        for b in dishes[n + 1:]
        if shared_ingredients(ctx.dishes[a], ctx.dishes[b], rule, ctx.ingredients)
    ]
    terms = []
    for i in range(len(dates)):
        for a, b in pairs:
            if hard:
                m.add_bool_or([x[i, a].Not(), x[i, b].Not()])
            else:
                both = m.new_bool_var(f"shared_{i}_{a}_{b}")
                m.add_bool_or([x[i, a].Not(), x[i, b].Not(), both])
                terms.append((ctx.settings.penalty_shared_ingredient, both))
    return terms


def _day_pairs(dates, window_days, same_day: bool):
    return [
        (i, j)
        for i in range(len(dates))
        for j in range(i if same_day else i + 1, len(dates))
        if (dates[j] - dates[i]).days < window_days
    ]


def _repeat(m, x, ctx, dates, dishes, window_days, hard):
    terms = []
    pairs = _day_pairs(dates, window_days, same_day=False)
    for k in dishes:
        for i, j in pairs:
            if hard:
                m.add_bool_or([x[i, k].Not(), x[j, k].Not()])
            else:
                y = m.new_bool_var(f"rep_{k}_{i}_{j}")
                m.add_bool_or([x[i, k].Not(), x[j, k].Not(), y])
                terms.append((ctx.settings.penalty_soft_repeat, y))
    for served in ctx.history:
        for i, d in enumerate(dates):
            if 0 < (d - served.date).days < window_days:
                for k in served.dish_ids:
                    if k in ctx.dishes and (i, k) in x:
                        if hard:
                            m.add(x[i, k] == 0)
                        else:
                            terms.append((ctx.settings.penalty_soft_repeat, x[i, k]))
    return terms


def _max_dishes_per_dinner(constraints: Sequence[Constraint]) -> int | None:
    maxima = [
        c.execution.max
        for c in constraints
        if isinstance(c.execution, DishCount) and c.strictness == Strictness.HARD and c.execution.max is not None
        and not c.execution.weekdays  # a bound must hold on every dinner
    ]
    return min(maxima, default=None)


def _similarity(m, x, ctx, dates, dishes, rule: DishSimilarity, hard, max_dishes: int | None):
    threshold = rule.max_similarity or ctx.settings.default_dish_similarity_threshold
    neighbours: dict[str, list[tuple[str, int]]] = {k: [] for k in dishes}  # dish -> [(similar dish, points)]
    compared = [k for k in dishes if ctx.dishes[k].dish_type not in rule.skip_dish_types]
    for n, a in enumerate(compared):
        for b in compared[n + 1:]:
            score = ctx.similarity(a, b, rule.feature)
            if score is not None and score > threshold:
                points = round(ctx.settings.penalty_dish_similarity * score)
                neighbours[a].append((b, points))
                neighbours[b].append((a, points))

    # A dish served again on another dinner is as similar as it gets (score 1.0).
    itself = round(ctx.settings.penalty_dish_similarity) if threshold < 1 else None
    compared_set = set(compared)
    terms = []
    for i, j in _day_pairs(dates, rule.days, same_day=rule.same_dinner):
        for a in dishes:
            # Same dinner: count each unordered pair once (b > a). Different dinners: a on i, b on j.
            similar = [(b, pts) for b, pts in neighbours[a] if i != j or b > a]
            if i != j and itself is not None and a in compared_set:
                similar.append((a, itself))
            if not similar:
                continue
            if hard:
                for b, _ in similar:
                    m.add_bool_or([x[i, a].Not(), x[j, b].Not()])
                continue
            # When a is served on day i, the penalty covers every similar dish served on day j.
            bound = sum(sorted((pts for _, pts in similar), reverse=True)[:max_dishes])
            penalty = m.new_int_var(0, bound, f"sim_{i}_{j}_{a}")
            m.add(penalty >= sum(pts * x[j, b] for b, pts in similar)).only_enforce_if(x[i, a])
            terms.append((1, penalty))
    return terms

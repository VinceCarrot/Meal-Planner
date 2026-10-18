"""Independent final validation of a complete 20-dinner menu.

The validator does not trust the solver: it re-checks the finished menu against
every effective constraint and reports one result per constraint. Soft
constraints also report their penalty, using the same weights as the solver,
so that repair and reporting share one definition of plan quality.
"""

from collections.abc import Sequence
from datetime import date
from enum import StrEnum

from .calories import estimate_dish_calories
from .checks import counted_by, describe_counted, exclusion_hits, find_repeats, shared_ingredients
from .constraint_types import (
    AnyOf,
    DishCount,
    DishSimilarity,
    DishTypeCount,
    ExactRepeatWindow,
    IngredientExclusion,
    MatchingDishCount,
    MealSimilarity,
    NoSharedIngredients,
)
from .constraints import EffectiveConstraintSet
from .models import Constraint, Dinner, Record
from .plan_context import PlanContext
from .vocab import ParseStatus, Strictness


class ResultStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_EVALUABLE = "not_evaluable"
    APPROXIMATED = "approximated"
    CONFLICT = "conflict"


class PlanStatus(StrEnum):
    FEASIBLE = "feasible"  # every constraint evaluated exactly; all hard constraints pass
    FEASIBLE_WITH_UNRESOLVED = "feasible_with_unresolved"  # hard pass; some results approximate or not evaluable
    BEST_EFFORT = "best_effort"  # a menu exists but a hard constraint failed or could not be checked
    INFEASIBLE = "infeasible"  # proven: no menu satisfies the hard constraints
    NO_SOLUTION_FOUND = "no_solution_found"  # time limit reached without any menu
    BLOCKED = "blocked"  # constraints need user input before planning


class ConstraintResult(Record):
    constraint_id: str
    description: str
    strictness: Strictness
    status: ResultStatus
    detail: str
    violations: tuple[str, ...] = ()
    penalty: int = 0  # soft constraints only


class DinnerCalories(Record):
    date: date
    known_kcal: float
    complete: bool  # False: some ingredient lines could not be converted


class ValidationReport(Record):
    status: PlanStatus
    structural_errors: tuple[str, ...]
    results: tuple[ConstraintResult, ...]
    disliked_servings: tuple[str, ...]
    preference_penalty: int
    calories: tuple[DinnerCalories, ...]

    @property
    def hard_ok(self) -> bool:
        return not self.structural_errors and all(
            r.status in (ResultStatus.PASSED, ResultStatus.APPROXIMATED)
            for r in self.results
            if r.strictness == Strictness.HARD
        )

    @property
    def penalty_total(self) -> int:
        return sum(r.penalty for r in self.results) + self.preference_penalty


def validate_menu(dinners: Sequence[Dinner], ctx: PlanContext, effective: EffectiveConstraintSet) -> ValidationReport:
    dinners = sorted(dinners, key=lambda d: d.date)
    errors = _structural_errors(dinners, ctx)
    # Constraints are evaluated on approved dishes only; anything else is a structural error above.
    known = []
    for d in dinners:
        ids = tuple(i for i in d.dish_ids if i in ctx.dishes)
        if ids:
            known.append(Dinner(date=d.date, dish_ids=ids))

    results = tuple(_evaluate(c, known, ctx, effective) for c in effective.constraints)
    disliked = tuple(f"{d.date} {i}" for d in known for i in d.dish_ids if i in ctx.disliked)
    calories = tuple(_dinner_calories(d, ctx) for d in known)

    report = ValidationReport(
        status=PlanStatus.FEASIBLE,
        structural_errors=tuple(errors),
        results=results,
        disliked_servings=disliked,
        preference_penalty=len(disliked) * ctx.settings.penalty_disliked,
        calories=calories,
    )
    return report.model_copy(update={"status": _overall_status(report)})


def _overall_status(report: ValidationReport) -> PlanStatus:
    if not report.hard_ok or any(r.status == ResultStatus.CONFLICT for r in report.results):
        return PlanStatus.BEST_EFFORT
    if any(r.status in (ResultStatus.NOT_EVALUABLE, ResultStatus.APPROXIMATED) for r in report.results):
        return PlanStatus.FEASIBLE_WITH_UNRESOLVED
    return PlanStatus.FEASIBLE


def _structural_errors(dinners: Sequence[Dinner], ctx: PlanContext) -> list[str]:
    errors = []
    if [d.date for d in dinners] != ctx.dates:
        errors.append(f"menu must have one dinner on each of the 20 weekdays from {ctx.dates[0]} to {ctx.dates[-1]}")
    for d in dinners:
        if not d.dish_ids:
            errors.append(f"{d.date}: dinner has no dishes")
        if len(set(d.dish_ids)) != len(d.dish_ids):
            errors.append(f"{d.date}: the same dish appears twice")
        errors += [f"{d.date}: '{i}' is not an approved dish" for i in d.dish_ids if i not in ctx.dishes]
    return errors


def _evaluate(c: Constraint, dinners: list[Dinner], ctx: PlanContext, effective: EffectiveConstraintSet) -> ConstraintResult:
    def result(status, detail, violations=(), penalty=0):
        return ConstraintResult(
            constraint_id=c.constraint_id, description=c.description, strictness=c.strictness,
            status=status, detail=detail, violations=tuple(violations),
            penalty=penalty if c.strictness == Strictness.SOFT else 0,
        )

    if effective.status_of(c.constraint_id) == ParseStatus.CONFLICT:
        return result(ResultStatus.CONFLICT, "conflicts with another active constraint")
    if c.execution is None:
        return result(ResultStatus.NOT_EVALUABLE, c.parse_notes or f"not evaluable ({c.parse_status})")

    violations, penalty, unknown = _EVALUATORS[type(c.execution)](c.execution, dinners, ctx)
    if violations:
        detail = f"{len(violations)} violation(s)" + (f"; {unknown} dish pair(s) could not be compared" if unknown else "")
        return result(ResultStatus.FAILED, detail, violations, penalty)
    if unknown:
        return result(ResultStatus.APPROXIMATED, f"{unknown} dish pair(s) could not be compared (missing features)")
    if c.parse_status == ParseStatus.APPROXIMATED:
        return result(ResultStatus.APPROXIMATED, c.parse_notes or "checked with an approximate interpretation")
    return result(ResultStatus.PASSED, "satisfied")


# Each evaluator returns (violations, soft penalty points, number of unknown similarity pairs).


def _count_deviation(rule, dinner: Dinner, ctx) -> tuple[int, int]:
    """(actual count, dishes missing or in excess) of one count rule in one dinner."""
    actual = sum(1 for i in dinner.dish_ids if counted_by(ctx.dishes[i], rule, ctx.ingredients))
    return actual, max(0, (rule.min or 0) - actual) + (max(0, actual - rule.max) if rule.max is not None else 0)


def _counts(rule: DishCount | DishTypeCount | MatchingDishCount, dinners, ctx):
    violations, units = [], 0
    for d in dinners:
        if not rule.applies_on(d.date.isoweekday()):
            continue
        actual, deviation = _count_deviation(rule, d, ctx)
        if deviation:
            violations.append(f"{d.date}: {actual} {describe_counted(rule)}")
            units += deviation
    return violations, units * ctx.settings.penalty_soft_count, 0


def _any_of(rule: AnyOf, dinners, ctx):
    violations = []
    for d in dinners:
        if not rule.applies_on(d.date.isoweekday()):
            continue
        outcomes = [_count_deviation(alt, d, ctx) for alt in rule.alternatives]
        if all(deviation for _, deviation in outcomes):
            found = "; ".join(f"{actual} {describe_counted(alt)}" for alt, (actual, _) in zip(rule.alternatives, outcomes))
            violations.append(f"{d.date}: no alternative holds ({found})")
    return violations, len(violations) * ctx.settings.penalty_soft_count, 0


def _no_shared(rule: NoSharedIngredients, dinners, ctx):
    violations = []
    for d in dinners:
        ids = d.dish_ids
        for x in range(len(ids)):
            for y in range(x + 1, len(ids)):
                shared = shared_ingredients(ctx.dishes[ids[x]], ctx.dishes[ids[y]], rule, ctx.ingredients)
                if shared:
                    violations.append(f"{d.date}: {ids[x]} and {ids[y]} share {', '.join(shared)}")
    return violations, len(violations) * ctx.settings.penalty_shared_ingredient, 0


def _exclusion(rule: IngredientExclusion, dinners, ctx):
    violations = [
        f"{d.date}: {i} contains {', '.join(hits)}"
        for d in dinners
        for i in d.dish_ids
        if (hits := exclusion_hits(ctx.dishes[i], rule, ctx.ingredients))
    ]
    return violations, len(violations) * ctx.settings.penalty_soft_exclusion, 0


def _repeats(rule: ExactRepeatWindow, dinners, ctx):
    plan_dates = {d.date for d in dinners}
    repeats = [r for r in find_repeats(list(ctx.history) + dinners, rule.weeks) if r.second in plan_dates]
    violations = [f"{r.dish_id} on {r.first} and {r.second}" for r in repeats]
    return violations, len(violations) * ctx.settings.penalty_soft_repeat, 0


def _dish_similarity(rule: DishSimilarity, dinners, ctx):
    threshold = rule.max_similarity or ctx.settings.default_dish_similarity_threshold
    violations, penalty, unknown = [], 0, 0
    skipped = set(rule.skip_dish_types)
    for (d1, a), (d2, b) in _dish_pairs_in_window(dinners, rule.days, rule.same_dinner):
        if ctx.dishes[a].dish_type in skipped or ctx.dishes[b].dish_type in skipped:
            continue
        score = ctx.similarity(a, b, rule.feature)
        if score is None:
            unknown += 1
        elif score > threshold:
            violations.append(f"{d1} {a} ~ {d2} {b}: {score:.2f}")
            penalty += round(ctx.settings.penalty_dish_similarity * score)
    return violations, penalty, unknown


def _meal_similarity(rule: MealSimilarity, dinners, ctx):
    threshold = rule.max_similarity or ctx.settings.default_meal_similarity_threshold
    violations, penalty, unknown = [], 0, 0
    for i, d1 in enumerate(dinners):
        for d2 in dinners[i + 1:]:
            if (d2.date - d1.date).days >= rule.window_weeks * 7:
                break
            sim = ctx.meal_similarity(d1.dish_ids, d2.dish_ids)
            unknown += sim.unknown_pairs
            if sim.normalized > threshold:
                violations.append(f"{d1.date} ~ {d2.date}: {sim.normalized:.2f}")
                penalty += round(ctx.settings.penalty_meal_similarity * sim.normalized)
    return violations, penalty, unknown


def _dish_pairs_in_window(dinners: Sequence[Dinner], days: int, same_dinner: bool = True):
    """Pairs of dishes served in the same dinner (if `same_dinner`) or on dinners less than `days` apart.

    A dish served again on another dinner forms a pair with itself (similarity 1.0), so a
    similarity rule is not satisfied by simply repeating one dish.
    """
    for i, d1 in enumerate(dinners):
        for d2 in dinners[i if same_dinner else i + 1:]:
            if (d2.date - d1.date).days >= days:
                break
            if d1 is d2:
                ids = d1.dish_ids
                pairs = [(ids[x], ids[y]) for x in range(len(ids)) for y in range(x + 1, len(ids))]
            else:
                pairs = [(a, b) for a in d1.dish_ids for b in d2.dish_ids]
            for a, b in pairs:
                yield (d1.date, a), (d2.date, b)


_EVALUATORS = {
    DishCount: _counts,
    DishTypeCount: _counts,
    MatchingDishCount: _counts,
    AnyOf: _any_of,
    NoSharedIngredients: _no_shared,
    IngredientExclusion: _exclusion,
    ExactRepeatWindow: _repeats,
    DishSimilarity: _dish_similarity,
    MealSimilarity: _meal_similarity,
}


def _dinner_calories(dinner: Dinner, ctx: PlanContext) -> DinnerCalories:
    estimates = [estimate_dish_calories(ctx.dishes[i], ctx.ingredients) for i in dinner.dish_ids]
    return DinnerCalories(
        date=dinner.date,
        known_kcal=round(sum(e.known_kcal for e in estimates), 1),
        complete=all(e.complete for e in estimates),
    )

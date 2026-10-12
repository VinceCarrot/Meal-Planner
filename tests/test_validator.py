"""Validator behaviour on hand-made menus (no solver involved)."""

from datetime import date

import pytest

from synthetic import synthetic_catalogue
from meal_planner.constraints import build_effective_set
from meal_planner.models import Constraint, Dinner
from meal_planner.plan_context import make_context
from meal_planner.settings import Settings
from meal_planner.validator import PlanStatus, ResultStatus, validate_menu
from meal_planner.vocab import TaskScope

START = date(2026, 10, 19)
GEN = TaskScope.MENU_GENERATION


@pytest.fixture(scope="module")
def ctx():
    return make_context(synthetic_catalogue(100), Settings(), START)


def _constraint(n, strictness="hard", execution=None, status=None, **extra):
    status = status or ("executable" if execution else "unsupported")
    return Constraint(constraint_id=f"C{n:03d}", description=f"rule {n}", scope=[GEN], strictness=strictness,
                      source="persistent", execution=execution, parse_status=status, **extra)


def _menu(ctx, pick):
    """A 20-dinner menu; `pick(i)` returns the dish IDs for dinner i."""
    return [Dinner(date=d, dish_ids=tuple(pick(i))) for i, d in enumerate(ctx.dates)]


def _by_type(ctx, dish_type):
    return sorted(k for k, d in ctx.dishes.items() if d.dish_type == dish_type)


@pytest.fixture
def varied_menu(ctx):
    soups, veg, meat = _by_type(ctx, "soup"), _by_type(ctx, "vegetarian"), _by_type(ctx, "meat")
    return _menu(ctx, lambda i: [meat[i], veg[i], soups[i % len(soups)]])


def _check(ctx, menu, *constraints):
    return validate_menu(menu, ctx, build_effective_set(list(constraints), [], GEN))


def test_all_passing_menu_is_feasible(ctx, varied_menu):
    report = _check(ctx, varied_menu, _constraint(1, execution={"type": "dish_count", "min": 3, "max": 3}))
    assert report.status == PlanStatus.FEASIBLE and report.hard_ok
    assert len(report.calories) == 20


def test_hard_failure_makes_best_effort(ctx, varied_menu):
    report = _check(ctx, varied_menu, _constraint(1, execution={"type": "dish_count", "min": 4}))
    assert report.status == PlanStatus.BEST_EFFORT
    [result] = report.results
    assert result.status == ResultStatus.FAILED and len(result.violations) == 20
    assert result.penalty == 0  # hard constraints do not carry penalties


def test_soft_failure_is_penalized_but_plan_stays_feasible(ctx, varied_menu):
    report = _check(ctx, varied_menu, _constraint(1, "soft", {"type": "dish_count", "min": 4}))
    assert report.status == PlanStatus.FEASIBLE
    assert report.results[0].status == ResultStatus.FAILED
    assert report.penalty_total == 20 * ctx.settings.penalty_soft_count


def test_soft_unsupported_constraint_is_unresolved(ctx, varied_menu):
    report = _check(ctx, varied_menu, _constraint(1, "soft", parse_notes="热量约束暂不支持"))
    assert report.status == PlanStatus.FEASIBLE_WITH_UNRESOLVED
    assert (report.results[0].status, report.results[0].detail) == (ResultStatus.NOT_EVALUABLE, "热量约束暂不支持")


def test_hard_unsupported_constraint_is_never_reported_as_met(ctx, varied_menu):
    report = _check(ctx, varied_menu, _constraint(1, "hard"))
    assert report.status == PlanStatus.BEST_EFFORT


def test_approximated_constraint_is_reported_as_such(ctx, varied_menu):
    c = _constraint(1, execution={"type": "dish_count", "min": 3}, status="approximated", parse_notes="只近似表达")
    report = _check(ctx, varied_menu, c)
    assert report.results[0].status == ResultStatus.APPROXIMATED
    assert report.status == PlanStatus.FEASIBLE_WITH_UNRESOLVED


def test_structural_errors(ctx, varied_menu):
    menu = varied_menu[:19] + [Dinner(date=varied_menu[19].date, dish_ids=("dish_9999",))]
    report = _check(ctx, menu)
    assert report.status == PlanStatus.BEST_EFFORT
    assert report.structural_errors == (f"{varied_menu[19].date}: 'dish_9999' is not an approved dish",)

    short = _check(ctx, varied_menu[:19])
    assert "one dinner on each of the 20 weekdays" in short.structural_errors[0]


def test_repeat_and_exclusion_violations_are_listed(ctx):
    soup = _by_type(ctx, "soup")[0]
    veg = _by_type(ctx, "vegetarian")
    menu = _menu(ctx, lambda i: [veg[i], soup])
    report = _check(
        ctx, menu,
        _constraint(1, execution={"type": "exact_repeat_window", "weeks": 1}),
        _constraint(2, "soft", {"type": "ingredient_exclusion", "ingredient_ids": [ctx.dishes[soup].style.main_ingredients[0]]}),
    )
    repeat, exclusion = report.results
    assert repeat.status == ResultStatus.FAILED and f"{soup} on {ctx.dates[0]} and {ctx.dates[1]}" in repeat.violations
    soup_hits = [v for v in exclusion.violations if f" {soup} contains" in v]
    assert exclusion.status == ResultStatus.FAILED and len(soup_hits) == 20
    assert exclusion.penalty == len(exclusion.violations) * ctx.settings.penalty_soft_exclusion


def test_meal_similarity_flags_identical_neighbouring_dinners(ctx, varied_menu):
    menu = list(varied_menu)
    menu[1] = Dinner(date=menu[1].date, dish_ids=menu[0].dish_ids)
    report = _check(ctx, menu, _constraint(1, "soft", {"type": "meal_similarity", "max_similarity": 0.9, "window_weeks": 1}))
    [result] = report.results
    assert result.violations == (f"{ctx.dates[0]} ~ {ctx.dates[1]}: 1.00",)
    assert result.penalty == ctx.settings.penalty_meal_similarity


def test_unknown_similarity_is_reported_as_approximate():
    local = make_context(synthetic_catalogue(100), Settings(), START)
    template = local.dishes[_by_type(local, "vegetarian")[0]].model_dump()
    bare = template | {"dish_id": "dish_0999", "style": {}, "ingredients": [{"ingredient_id": "ing_soy_sauce"}]}
    local.dishes["dish_0999"] = type(local.dishes["dish_0001"]).model_validate(bare)
    veg, soup = _by_type(local, "vegetarian"), _by_type(local, "soup")
    menu = _menu(local, lambda i: ["dish_0999" if i == 0 else veg[i], soup[i % len(soup)]])

    # A threshold no real pair exceeds, so the only finding is the uncomparable dish.
    rule = {"type": "dish_similarity", "max_similarity": 1.0, "window_weeks": 1}
    report = _check(local, menu, _constraint(1, "soft", rule))

    assert report.results[0].status == ResultStatus.APPROXIMATED
    assert "could not be compared" in report.results[0].detail

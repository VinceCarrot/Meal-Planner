import dataclasses
from datetime import date, timedelta

import pytest

from meal_planner.demo import synthetic_catalogue
from meal_planner import planner
from meal_planner.checks import check_count, exclusion_hits
from meal_planner.constraint_types import DishCount, DishTypeCount, IngredientExclusion
from meal_planner.constraints import build_effective_set
from meal_planner.models import Constraint, Dinner, DishesFile, PreferencesFile, Feedback
from meal_planner.plan_context import make_context
from meal_planner.planner import max_uses_per_dish, plan_menu
from meal_planner.settings import Settings
from meal_planner.solver import SolverResult
from meal_planner.validator import PlanStatus, ResultStatus, ValidationReport
from meal_planner.vocab import TaskScope

START = date(2026, 10, 19)
GEN = TaskScope.MENU_GENERATION

DISHES_4 = ("hard", {"type": "dish_count", "min": 4, "max": 4})
SOUP_1 = ("hard", {"type": "dish_type_count", "dish_type": "soup", "min": 1, "max": 1})
MEAT_1 = ("hard", {"type": "dish_type_count", "dish_type": "meat", "min": 1})
VEG_1 = ("hard", {"type": "dish_type_count", "dish_type": "vegetarian", "min": 1})
NO_REPEAT_2W = ("hard", {"type": "exact_repeat_window", "weeks": 2})
TYPICAL = [DISHES_4, SOUP_1, MEAT_1, VEG_1, NO_REPEAT_2W]


@pytest.fixture(scope="module")
def catalogue():
    return synthetic_catalogue(100)


@pytest.fixture
def settings():
    s = Settings()
    return Settings(planner=s.planner.model_copy(update={"time_limit_s": 10}))


def effective(*specs):
    constraints = [
        Constraint(constraint_id=f"C{n:03d}", description=f"rule {n}", scope=[GEN], strictness=strictness,
                   source="persistent", execution=execution, parse_status="executable")
        for n, (strictness, execution) in enumerate(specs, start=1)
    ]
    return build_effective_set(constraints, [], GEN)


def run(catalogue, settings, specs, **kwargs):
    ctx = make_context(catalogue, settings, START, kwargs.pop("history", ()))
    return ctx, plan_menu(ctx, effective(*specs), **kwargs)


def test_feasible_plan_is_validated_independently(catalogue, settings):
    ctx, result = run(catalogue, settings, TYPICAL)

    assert result.status == PlanStatus.FEASIBLE == result.report.status
    assert [d.date for d in result.dinners] == ctx.dates
    assert all(r.status == ResultStatus.PASSED for r in result.report.results)
    for dinner in result.dinners:
        dishes = [ctx.dishes[i] for i in dinner.dish_ids]
        for _, rule in TYPICAL[:4]:
            rule = DishCount(**rule) if rule["type"] == "dish_count" else DishTypeCount(**rule)
            assert check_count(dishes, rule).passed


def test_same_input_gives_the_same_menu(catalogue, settings):
    _, first = run(catalogue, settings, TYPICAL)
    _, second = run(catalogue, settings, TYPICAL)
    assert first.dinners == second.dinners


def test_pending_dishes_are_never_selected(catalogue, settings):
    pending = [d.model_copy(update={"dish_id": f"dish_9{n:03d}", "review_status": "pending"}) for n, d in enumerate(catalogue.dishes.dishes)]
    with_pending = dataclasses.replace(catalogue, pending_dishes=DishesFile(dishes=pending))
    _, result = run(with_pending, settings, TYPICAL)
    assert result.status == PlanStatus.FEASIBLE
    assert not any(i.startswith("dish_9") for d in result.dinners for i in d.dish_ids)


def test_catalogue_shortfall_is_explained_without_solving(catalogue, settings):
    two_soups = ("hard", {"type": "dish_type_count", "dish_type": "soup", "min": 2})
    whole_plan = ("hard", {"type": "exact_repeat_window", "weeks": 4})
    _, result = run(catalogue, settings, [DISHES_4, two_soups, whole_plan])

    assert result.status == PlanStatus.INFEASIBLE and result.solver is None
    [gap] = result.gaps
    assert (gap.dish_type, gap.eligible_dishes, gap.max_uses_per_dish, gap.servings_needed) == ("soup", 15, 1, 40)
    assert gap.additional_dishes_needed == 25
    assert "25 more approved soup dishes needed" in result.messages[0]


def test_hard_exclusion_counts_against_capacity(catalogue, settings):
    no_animal = ("hard", {"type": "ingredient_exclusion", "categories": ["meat", "poultry", "seafood"]})
    _, result = run(catalogue, settings, [DISHES_4, MEAT_1, no_animal])
    assert result.status == PlanStatus.INFEASIBLE
    assert [(g.dish_type, g.eligible_dishes) for g in result.gaps] == [("meat", 0)]


def test_infeasibility_names_the_constraint_to_relax(catalogue, settings):
    ctx = make_context(catalogue, settings, START)
    soup = next(k for k, d in ctx.dishes.items() if d.dish_type == "soup")
    vegetarian = [k for k, d in ctx.dishes.items() if d.dish_type == "vegetarian"][:3]
    first_day = ctx.dates[0]
    # The first dinner is fixed to a soup and three vegetarian dishes: only "at least one meat dish" fails.
    _, result = run(catalogue, settings, TYPICAL, fixed={first_day: [soup, *vegetarian]},
                    free_dates=set(ctx.dates[1:]))
    assert result.status == PlanStatus.INFEASIBLE
    assert result.relaxation_candidates == ("C003",)
    assert "C003" in result.messages[0]


def test_timeout_without_solution_is_not_called_infeasible(catalogue, settings, monkeypatch):
    monkeypatch.setattr(planner, "solve", lambda *a, **k: SolverResult("unknown", None, None, 10.0, 0))
    _, result = run(catalogue, settings, TYPICAL)
    assert result.status == PlanStatus.NO_SOLUTION_FOUND
    assert "feasibility is unknown" in result.messages[0]


def test_solver_candidate_is_not_trusted(catalogue, settings, monkeypatch):
    ctx = make_context(catalogue, settings, START)
    soup = next(k for k, d in ctx.dishes.items() if d.dish_type == "soup")
    bad = tuple(Dinner(date=d, dish_ids=(soup,)) for d in ctx.dates)
    monkeypatch.setattr(planner, "solve", lambda *a, **k: SolverResult("optimal", bad, 0, 0.1, 0))

    _, result = run(catalogue, settings, TYPICAL)

    assert result.status == PlanStatus.BEST_EFFORT
    failed = {r.constraint_id for r in result.report.results if r.status == ResultStatus.FAILED}
    assert {"C001", "C003", "C004", "C005"} <= failed


def test_unready_constraints_block_planning(catalogue, settings):
    ctx = make_context(catalogue, settings, START)
    unparsed = Constraint(constraint_id="C001", description="每顿几个菜？", scope=[GEN], strictness="hard", source="persistent")
    result = plan_menu(ctx, build_effective_set([unparsed], [], GEN))
    assert result.status == PlanStatus.BLOCKED and "not parsed" in result.messages[0]


def test_dish_count_is_required(catalogue, settings):
    _, result = run(catalogue, settings, [SOUP_1])
    assert result.status == PlanStatus.BLOCKED and "how many dishes" in result.messages[0]


def test_soft_exclusion_and_dislikes_are_avoided_when_possible(catalogue, settings):
    ctx = make_context(catalogue, settings, START)
    disliked = sorted(ctx.dishes)[:10]
    feedback = [Feedback(feedback_id=f"F{n:03d}", dish_id=k, kind="dislike", scope="future_menus") for n, k in enumerate(disliked, 1)]
    with_dislikes = dataclasses.replace(catalogue, preferences=PreferencesFile(feedback=feedback))
    no_seafood = ("soft", {"type": "ingredient_exclusion", "categories": ["seafood"]})

    ctx, result = run(with_dislikes, settings, TYPICAL + [no_seafood])

    served = [i for d in result.dinners for i in d.dish_ids]
    rule = IngredientExclusion(type="ingredient_exclusion", categories=("seafood",))
    assert not any(exclusion_hits(ctx.dishes[i], rule, ctx.ingredients) for i in served)
    assert not set(served) & set(disliked)
    assert result.report.disliked_servings == ()


def test_hard_dish_similarity_is_respected(catalogue, settings):
    strict = ("hard", {"type": "dish_similarity", "max_similarity": 0.35, "window_weeks": 1})
    _, result = run(catalogue, settings, TYPICAL + [strict])
    assert result.status == PlanStatus.FEASIBLE
    assert result.report.results[-1].status == ResultStatus.PASSED


def test_repetition_window_includes_earlier_menus(catalogue, settings):
    ctx = make_context(catalogue, settings, START)
    friday_before = START - timedelta(days=3)
    history = [Dinner(date=friday_before, dish_ids=tuple(sorted(ctx.dishes)[:30]))]
    no_repeat_1w = ("hard", {"type": "exact_repeat_window", "weeks": 1})

    _, result = run(catalogue, settings, TYPICAL[:4] + [no_repeat_1w], history=history)

    assert result.status == PlanStatus.FEASIBLE
    banned = set(history[0].dish_ids)
    for dinner in result.dinners:
        if (dinner.date - friday_before).days < 7:
            assert not banned & set(dinner.dish_ids)


def test_fixed_dinners_outside_free_dates_are_unchanged(catalogue, settings):
    ctx, first = run(catalogue, settings, TYPICAL)
    target = ctx.dates[7]
    fixed = {d.date: [i for i in d.dish_ids if not (d.date == target and i == d.dish_ids[0])] for d in first.dinners}

    _, second = run(catalogue, settings, TYPICAL, fixed=fixed, free_dates={target})

    assert second.status == PlanStatus.FEASIBLE
    for before, after in zip(first.dinners, second.dinners):
        if before.date != target:
            assert before == after
        else:
            assert set(fixed[target]) <= set(after.dish_ids)


def test_report_is_serializable_for_menu_versions(catalogue, settings):
    _, result = run(catalogue, settings, TYPICAL)
    data = result.report.model_dump(mode="json")
    assert ValidationReport.model_validate(data) == result.report


@pytest.mark.parametrize("window, uses", [(None, 20), (7, 4), (14, 2), (21, 2), (28, 1)])
def test_max_uses_per_dish(window, uses):
    dates = make_context(synthetic_catalogue(10), Settings(), START).dates
    assert max_uses_per_dish(dates, window) == uses

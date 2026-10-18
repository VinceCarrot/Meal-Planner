"""Constraint types added for weekday rules, matching counts, alternatives, shared
ingredients and aspect-based similarity (ADR-025): models, solver, validator,
conflict detection, capacity gaps and parsing."""

from datetime import date

import pytest
from pydantic import TypeAdapter, ValidationError

from fakes import FakeLLM
from meal_planner.checks import counted_by, shared_ingredients
from meal_planner.constraint_parser import parse_constraints
from meal_planner.constraint_types import Execution, MatchingDishCount, NoSharedIngredients
from meal_planner.constraints import TaskConstraintInput, build_effective_set, find_conflicts, make_task_constraints
from meal_planner.demo import synthetic_catalogue
from meal_planner.models import Constraint, Dinner
from meal_planner.plan_context import make_context
from meal_planner.planner import capacity_gaps, plan_menu
from meal_planner.readonly import ReadOnlyCatalogue
from meal_planner.settings import Settings
from meal_planner.validator import PlanStatus, ResultStatus, validate_menu
from meal_planner.vocab import TaskScope

START = date(2026, 10, 19)  # a Monday
GEN = TaskScope.MENU_GENERATION
EXECUTION = TypeAdapter(Execution)

DISHES_3 = ("hard", {"type": "dish_count", "min": 3, "max": 3})
DISHES_4 = ("hard", {"type": "dish_count", "min": 4, "max": 4})


@pytest.fixture(scope="module")
def catalogue():
    return synthetic_catalogue(100)


@pytest.fixture
def ctx(catalogue):
    settings = Settings()
    return make_context(catalogue, Settings(planner=settings.planner.model_copy(update={"time_limit_s": 10})), START)


def constraints(*specs):
    return [
        Constraint(constraint_id=f"C{n:03d}", description=f"rule {n}", scope=[GEN], strictness=strictness,
                   source="persistent", execution=execution, parse_status="executable")
        for n, (strictness, execution) in enumerate(specs, start=1)
    ]


def effective(*specs):
    return build_effective_set(constraints(*specs), [], GEN)


def plan(ctx, *specs):
    result = plan_menu(ctx, effective(*specs))
    assert result.status == PlanStatus.FEASIBLE, result.messages or result.report
    assert all(r.status == ResultStatus.PASSED for r in result.report.results)
    return result.dinners


def types_of(ctx, dinner):
    return [ctx.dishes[k].dish_type for k in dinner.dish_ids]


# --- Models -----------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [
    {"type": "dish_type_count", "dish_type": "soup", "min": 1, "weekdays": [1, 1]},
    {"type": "dish_type_count", "dish_type": "soup", "min": 1, "weekdays": [6]},
    {"type": "matching_dish_count", "min": 1},
    {"type": "any_of", "alternatives": [{"type": "dish_count", "min": 3}]},
    {"type": "any_of", "alternatives": [
        {"type": "dish_type_count", "dish_type": "meat", "min": 1, "weekdays": [1]},
        {"type": "dish_type_count", "dish_type": "mixed", "min": 2}]},
    {"type": "any_of", "alternatives": [
        {"type": "any_of", "alternatives": []}, {"type": "dish_count", "min": 1}]},
    {"type": "dish_similarity", "window_days": 1, "same_dinner": False},
    {"type": "dish_similarity", "feature": "colour"},
])
def test_invalid_parameters_are_refused(bad):
    with pytest.raises(ValidationError):
        EXECUTION.validate_python(bad)


def test_similarity_window_defaults_to_weeks():
    assert EXECUTION.validate_python({"type": "dish_similarity"}).days == 7
    assert EXECUTION.validate_python({"type": "dish_similarity", "window_weeks": 2, "window_days": 2}).days == 2


def test_matching_counts_main_ingredient_or_any_use(catalogue):
    ingredients = {i.ingredient_id: i for i in catalogue.ingredients.ingredients}
    dish = next(d for d in catalogue.dishes.dishes
                if d.dish_type == "meat" and ingredients[d.style.main_ingredients[0]].category == "seafood"
                and any(ingredients[l.ingredient_id].category == "vegetable" for l in d.ingredients
                        if l.ingredient_id not in d.style.main_ingredients))
    as_main = MatchingDishCount(type="matching_dish_count", contains_categories=["vegetable"], min=1)
    any_use = as_main.model_copy(update={"as_main_ingredient": False})
    assert not counted_by(dish, as_main, ingredients) and counted_by(dish, any_use, ingredients)
    soups_only = MatchingDishCount(type="matching_dish_count", contains_categories=["seafood"], dish_types=["soup"], min=1)
    assert not counted_by(dish, soups_only, ingredients)


def test_shared_ingredients_ignore_seasonings_by_default(catalogue):
    ingredients = {i.ingredient_id: i for i in catalogue.ingredients.ingredients}
    rule = NoSharedIngredients(type="no_shared_ingredients")
    a, b = catalogue.dishes.dishes[:2]
    seasoning = next(i for i in ingredients.values() if i.category == "seasoning").ingredient_id
    a = a.model_copy(update={"ingredients": (*a.ingredients, a.ingredients[0].model_copy(update={"ingredient_id": seasoning}))})
    b = b.model_copy(update={"ingredients": (*b.ingredients, b.ingredients[0].model_copy(update={"ingredient_id": seasoning}))})
    assert seasoning not in shared_ingredients(a, b, rule, ingredients)


# --- Solver and validator ---------------------------------------------------------------


def test_weekday_soup_rule(ctx):
    dinners = plan(ctx, DISHES_3,
                   ("hard", {"type": "dish_type_count", "dish_type": "soup", "min": 1, "max": 1, "weekdays": [1, 3, 5]}),
                   ("hard", {"type": "dish_type_count", "dish_type": "soup", "max": 0, "weekdays": [2, 4]}))
    for d in dinners:
        assert types_of(ctx, d).count("soup") == (1 if d.date.isoweekday() in (1, 3, 5) else 0)


def test_weekday_rule_is_checked_only_on_its_days(ctx):
    soup = next(k for k, d in ctx.dishes.items() if d.dish_type == "soup")
    others = [k for k, d in ctx.dishes.items() if d.dish_type == "vegetarian"]
    dinners = [Dinner(date=day, dish_ids=(others[n], others[n + 1])) for n, day in enumerate(ctx.dates)]
    dinners[1] = Dinner(date=ctx.dates[1], dish_ids=(soup,))  # a Tuesday soup is not a violation
    report = validate_menu(dinners, ctx, effective(
        ("hard", {"type": "dish_type_count", "dish_type": "soup", "min": 1, "weekdays": [1, 3, 5]})))
    [result] = report.results
    assert len(result.violations) == 12 and all("10-20" not in v for v in result.violations)


def test_matching_dish_count(ctx):
    rule = {"type": "matching_dish_count", "dish_types": ["vegetarian", "mixed", "meat"],
            "contains_categories": ["seafood"], "as_main_ingredient": True, "min": 1}
    dinners = plan(ctx, DISHES_3, ("hard", rule))
    parsed = MatchingDishCount.model_validate(rule)
    for d in dinners:
        assert any(counted_by(ctx.dishes[k], parsed, ctx.ingredients) for k in d.dish_ids)


def test_dishes_counted_without_soup(ctx):
    non_soup = {"type": "matching_dish_count", "dish_types": ["vegetarian", "mixed", "meat"], "min": 3, "max": 4}
    # No dish_count rule: the non-soup count alone says how many dishes a dinner has.
    dinners = plan(ctx, ("hard", non_soup),
                   ("hard", {"type": "dish_type_count", "dish_type": "soup", "min": 1, "max": 1, "weekdays": [1, 3, 5]}))
    for d in dinners:
        types = types_of(ctx, d)
        assert 3 <= len([t for t in types if t != "soup"]) <= 4
        assert types.count("soup") == (1 if d.date.isoweekday() in (1, 3, 5) else types.count("soup"))


def test_any_of_alternatives(ctx):
    dinners = plan(ctx, DISHES_3,
                   ("hard", {"type": "any_of", "alternatives": [
                       {"type": "dish_type_count", "dish_type": "meat", "min": 1},
                       {"type": "dish_type_count", "dish_type": "mixed", "min": 2}]}),
                   ("hard", {"type": "dish_type_count", "dish_type": "meat", "max": 0, "weekdays": [2]}))
    for d in dinners:
        types = types_of(ctx, d)
        assert types.count("meat") >= 1 or types.count("mixed") >= 2
        if d.date.isoweekday() == 2:
            assert types.count("mixed") >= 2


def test_any_of_violation_is_reported(ctx):
    veg = [k for k, d in ctx.dishes.items() if d.dish_type == "vegetarian"]
    dinners = [Dinner(date=day, dish_ids=(veg[n], veg[n + 1])) for n, day in enumerate(ctx.dates)]
    report = validate_menu(dinners, ctx, effective(("soft", {"type": "any_of", "alternatives": [
        {"type": "dish_type_count", "dish_type": "meat", "min": 1},
        {"type": "dish_type_count", "dish_type": "mixed", "min": 2}]})))
    [result] = report.results
    assert result.status == ResultStatus.FAILED and len(result.violations) == 20
    assert result.penalty == 20 * ctx.settings.penalty_soft_count


def test_no_shared_ingredients_in_one_dinner(ctx):
    dinners = plan(ctx, DISHES_4, ("hard", {"type": "no_shared_ingredients"}))
    rule = NoSharedIngredients(type="no_shared_ingredients")
    for d in dinners:
        ids = d.dish_ids
        for x in range(len(ids)):
            for y in range(x + 1, len(ids)):
                assert not shared_ingredients(ctx.dishes[ids[x]], ctx.dishes[ids[y]], rule, ctx.ingredients)


def test_flavour_similarity_within_one_dinner(ctx):
    rule = {"type": "dish_similarity", "feature": "flavours", "window_days": 1, "max_similarity": 0.99,
            "skip_dish_types": ["soup"]}
    dinners = plan(ctx, DISHES_3, ("hard", rule))
    for d in dinners:
        dishes = [ctx.dishes[k] for k in d.dish_ids if ctx.dishes[k].dish_type != "soup"]
        flavour_sets = [frozenset(x.style.flavours) for x in dishes]
        assert len(set(flavour_sets)) == len(flavour_sets)


def test_adjacent_day_ingredient_similarity_skips_the_weekend(ctx):
    keys = sorted(ctx.dishes)
    a, b = next((a, b) for a in keys for b in keys if a < b and (ctx.similarity(a, b, "ingredients") or 0) > 0.5)
    unrelated = [k for k in keys if k not in (a, b)
                 and (ctx.similarity(k, a, "ingredients") or 0) <= 0.5 and (ctx.similarity(k, b, "ingredients") or 0) <= 0.5]
    rule = {"type": "dish_similarity", "feature": "ingredients", "window_days": 2, "same_dinner": False}

    def violations(day_a, day_b):
        dinners = [Dinner(date=day, dish_ids=(unrelated[n],)) for n, day in enumerate(ctx.dates)]
        dinners[day_a] = Dinner(date=ctx.dates[day_a], dish_ids=(a,))
        dinners[day_b] = Dinner(date=ctx.dates[day_b], dish_ids=(b,))
        [result] = validate_menu(dinners, ctx, effective(("soft", rule))).results
        return [v for v in result.violations if a in v and b in v]

    assert len(violations(3, 4)) == 1  # Thursday and Friday
    assert violations(4, 5) == []  # Friday and the next Monday are not adjacent calendar days
    assert violations(0, 2) == []  # Monday and Wednesday


def test_repeating_a_dish_counts_as_similar(ctx):
    keys = sorted(ctx.dishes)
    dinners = [Dinner(date=day, dish_ids=(keys[n],)) for n, day in enumerate(ctx.dates)]
    dinners[4] = Dinner(date=ctx.dates[4], dish_ids=(keys[3],))  # Thursday's dish again on Friday
    rule = {"type": "dish_similarity", "feature": "ingredients", "window_days": 2, "same_dinner": False}
    [result] = validate_menu(dinners, ctx, effective(("soft", rule))).results
    assert any(v.count(keys[3]) == 2 and v.endswith("1.00") for v in result.violations)

    planned = plan(ctx, DISHES_3, ("hard", rule))
    for d1, d2 in zip(planned, planned[1:]):
        if (d2.date - d1.date).days == 1:
            assert not set(d1.dish_ids) & set(d2.dish_ids)


def test_adjacent_day_ingredient_rule_plans(ctx):
    rule = {"type": "dish_similarity", "feature": "ingredients", "window_days": 2, "same_dinner": False}
    plan(ctx, DISHES_3, ("hard", rule))


# --- Conflicts and capacity -------------------------------------------------------------


def test_weekday_rules_on_different_days_do_not_conflict():
    assert find_conflicts(constraints(
        ("hard", {"type": "dish_type_count", "dish_type": "soup", "min": 1, "weekdays": [1, 3, 5]}),
        ("hard", {"type": "dish_type_count", "dish_type": "soup", "max": 0, "weekdays": [2, 4]}),
    )) == []


def test_weekday_conflict_names_the_days():
    [issue] = find_conflicts(constraints(
        ("hard", {"type": "dish_type_count", "dish_type": "soup", "min": 1, "weekdays": [1, 3, 5]}),
        ("hard", {"type": "dish_type_count", "dish_type": "soup", "max": 0}),
    ))
    assert issue.constraint_ids == ("C001", "C002") and "weekdays 1, 3, 5" in issue.message


def test_any_of_that_cannot_fit_conflicts():
    [issue] = find_conflicts(constraints(
        ("hard", {"type": "dish_count", "min": 2, "max": 2}),
        ("hard", {"type": "dish_type_count", "dish_type": "soup", "min": 1}),
        ("hard", {"type": "any_of", "alternatives": [
            {"type": "dish_type_count", "dish_type": "meat", "min": 2},
            {"type": "dish_type_count", "dish_type": "mixed", "min": 2}]}),
    ))
    assert set(issue.constraint_ids) == {"C001", "C002", "C003"}


def test_any_of_with_a_fitting_alternative_does_not_conflict():
    assert find_conflicts(constraints(
        ("hard", {"type": "dish_count", "min": 3, "max": 3}),
        ("hard", {"type": "dish_type_count", "dish_type": "soup", "min": 1}),
        ("hard", {"type": "any_of", "alternatives": [
            {"type": "dish_type_count", "dish_type": "meat", "min": 1},
            {"type": "dish_type_count", "dish_type": "mixed", "min": 3}]}),
    )) == []


def test_infeasible_combination_is_reported_not_hidden(ctx):
    # Every dinner needs a seafood main dish, but seafood is excluded: no menu can exist.
    result = plan_menu(ctx, effective(
        DISHES_3,
        ("hard", {"type": "matching_dish_count", "contains_categories": ["seafood"], "min": 1}),
        ("hard", {"type": "ingredient_exclusion", "categories": ["seafood"]}),
    ))
    assert result.status == PlanStatus.INFEASIBLE and result.dinners is None
    [gap] = result.gaps
    assert gap.constraint_id == "C002" and gap.eligible_dishes == 0 and "seafood" in gap.describe()


def test_capacity_gap_counts_only_the_rule_weekdays(ctx):
    rule = {"type": "matching_dish_count", "contains_categories": ["seafood"], "min": 1, "weekdays": [1]}
    hard = constraints(("hard", {"type": "exact_repeat_window", "weeks": 4}), ("hard", rule))
    ingredients = ctx.ingredients
    seafood = [d for d in ctx.dishes.values()
               if any(ingredients[m].category == "seafood" for m in d.style.main_ingredients)]
    assert len(seafood) >= 4  # four Mondays, each dish once
    assert capacity_gaps(ctx, hard) == []


# --- Parsing ----------------------------------------------------------------------------


@pytest.fixture
def view(store):
    return ReadOnlyCatalogue(store.load())


def _parse(view, description, item):
    [c] = make_task_constraints([TaskConstraintInput(description)], GEN)
    llm = FakeLLM({"results": [item | {"constraint_id": c.constraint_id}]})
    [parsed] = parse_constraints(llm, [c], view)
    return parsed, llm


@pytest.mark.parametrize("description, execution", [
    ("每顿饭3-4个菜（不包含汤）",
     {"type": "matching_dish_count", "dish_types": ["vegetarian", "mixed", "meat"], "min": 3, "max": 4}),
    ("每周一、三、五晚饭要有一个汤",
     {"type": "dish_type_count", "dish_type": "soup", "min": 1, "max": 1, "weekdays": [1, 3, 5]}),
    ("每顿饭的菜（不包括汤）里要有一个菜是绿叶菜作为食材",
     {"type": "matching_dish_count", "dish_types": ["vegetarian", "mixed", "meat"],
      "contains_categories": ["leafy_green"], "min": 1}),
    ("每顿饭要有一个大荤菜，或两个荤素搭配菜",
     {"type": "any_of", "alternatives": [{"type": "dish_type_count", "dish_type": "meat", "min": 1},
                                         {"type": "dish_type_count", "dish_type": "mixed", "min": 2}]}),
    ("每顿饭的食材不要重复", {"type": "no_shared_ingredients"}),
    ("每顿饭的菜品口味尽量不相似",
     {"type": "dish_similarity", "feature": "flavours", "window_days": 1, "skip_dish_types": ["soup"]}),
    ("相邻两天的菜品食材尽量不相似",
     {"type": "dish_similarity", "feature": "ingredients", "window_days": 2, "same_dinner": False}),
])
def test_new_types_are_accepted_from_the_parser(view, description, execution):
    parsed, _ = _parse(view, description, {"parse_status": "executable", "strictness": "hard",
                                           "execution": execution, "notes": "ok"})
    assert parsed.parse_status == "executable" and parsed.execution.type == execution["type"]


def test_malformed_any_of_is_not_trusted(view):
    bad = {"type": "any_of", "alternatives": [
        {"type": "dish_type_count", "dish_type": "meat", "min": 1, "weekdays": [1]},
        {"type": "dish_type_count", "dish_type": "mixed", "min": 2}]}
    parsed, _ = _parse(view, "周一一个大荤或两个荤素搭配",
                       {"parse_status": "executable", "strictness": "hard", "execution": bad, "notes": ""})
    assert parsed.parse_status == "unparsed" and parsed.execution is None


def test_unknown_ingredient_in_matching_rule_needs_clarification(view):
    rule = {"type": "matching_dish_count", "contains_ingredient_ids": ["ing_unknown"], "min": 1}
    parsed, _ = _parse(view, "每顿要有一道用某菜的菜",
                       {"parse_status": "executable", "strictness": "hard", "execution": rule, "notes": ""})
    assert parsed.parse_status == "needs_clarification" and "ing_unknown" in parsed.parse_notes


def test_prompt_explains_weekdays_alternatives_and_categories(view):
    _, llm = _parse(view, "每顿饭3个菜", {"parse_status": "executable", "strictness": "hard",
                                          "execution": {"type": "dish_count", "min": 3, "max": 3}, "notes": ""})
    system = llm.calls[0]["system"]
    assert "1=周一" in system and "any_of" in system and "leafy_green (绿叶菜)" in system
    assert "\n    " not in system  # type descriptions are one line each

from datetime import date

import pytest
from pydantic import ValidationError

from conftest import PLAN_START, make_menu
from meal_planner.models import (
    Constraint,
    Dinner,
    DishIngredient,
    Feedback,
    Ingredient,
    plan_dates,
)


def test_plan_dates_are_twenty_weekdays_over_four_weeks():
    dates = plan_dates(PLAN_START)
    assert len(dates) == 20
    assert all(d.weekday() < 5 for d in dates)
    assert dates[-1] == date(2026, 11, 13)


@pytest.mark.parametrize(
    "fields",
    [
        {},  # neither id nor unmatched name
        {"ingredient_id": "ing_egg", "unmatched_name": "鸡蛋"},  # both
        {"ingredient_id": "ing_egg", "quantity": 2},  # quantity without unit
    ],
)
def test_dish_ingredient_line_rules(fields):
    with pytest.raises(ValidationError):
        DishIngredient(**fields)


def test_ingredient_id_format_is_enforced():
    with pytest.raises(ValidationError):
        Ingredient(ingredient_id="Tomato", name_zh="番茄", category="vegetable")


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError, match="Extra inputs"):
        Ingredient(ingredient_id="ing_x", name_zh="x", category="other", kcal=1)


def test_records_are_immutable():
    ing = Ingredient(ingredient_id="ing_x", name_zh="x", category="other", aliases=["y"])
    with pytest.raises(ValidationError):
        ing.name_zh = "z"
    assert isinstance(ing.aliases, tuple)


def _constraint(**overrides):
    fields = dict(
        constraint_id="C001",
        description="每顿饭一个汤",
        scope=["menu_generation"],
        strictness="hard",
        source="persistent",
    )
    fields.update(overrides)
    return Constraint(**fields)


def test_constraint_defaults_to_unparsed():
    assert _constraint().parse_status == "unparsed"


@pytest.mark.parametrize("status", ["executable", "approximated"])
def test_evaluable_constraint_requires_execution_type(status):
    with pytest.raises(ValidationError, match="requires execution"):
        _constraint(parse_status=status)
    with pytest.raises(ValidationError, match="requires execution"):
        _constraint(parse_status=status, execution={"dish_type": "soup"})
    assert _constraint(parse_status=status, execution={"type": "dish_type_count"})


def test_constraint_scope_must_be_non_empty_and_unique():
    with pytest.raises(ValidationError):
        _constraint(scope=[])
    with pytest.raises(ValidationError, match="duplicates"):
        _constraint(scope=["menu_generation", "menu_generation"])


def test_this_menu_feedback_requires_menu_id():
    with pytest.raises(ValidationError, match="menu_id is required"):
        Feedback(feedback_id="F001", dish_id="dish_0001", kind="dislike", scope="this_menu")


def test_menu_must_start_on_monday():
    with pytest.raises(ValidationError, match="not a Monday"):
        make_menu(start_date=date(2026, 10, 20))


def test_menu_must_cover_exactly_the_twenty_plan_dates():
    menu = make_menu()
    with pytest.raises(ValidationError, match="exactly the 20 weekdays"):
        make_menu(dinners=menu.dinners[:19])
    shifted = menu.dinners[:19] + (Dinner(date=date(2026, 11, 14), dish_ids=("dish_0001",)),)
    with pytest.raises(ValidationError, match="exactly the 20 weekdays"):
        make_menu(dinners=shifted)


def test_menu_based_on_version_must_be_older():
    with pytest.raises(ValidationError, match="based_on_version"):
        make_menu(version=2, based_on_version=2)

from datetime import date, timedelta

import pytest

from meal_planner.checks import CheckResult, check_count, count_dish_types, exclusion_hits, find_repeats
from meal_planner.constraint_types import DishCount, DishTypeCount, IngredientExclusion
from meal_planner.models import Dinner


@pytest.fixture
def cat(store):
    return store.load()


@pytest.fixture
def dishes(cat):
    return {d.dish_id: d for d in cat.dishes.dishes}


@pytest.fixture
def ingredients(cat):
    return {i.ingredient_id: i for i in cat.ingredients.ingredients}


def test_count_dish_types(dishes):
    meal = [dishes["dish_0001"], dishes["dish_0003"], dishes["dish_0005"]]
    assert count_dish_types(meal) == {"vegetarian": 2, "soup": 1}


@pytest.mark.parametrize(
    "rule, passed, detail",
    [
        (DishCount(type="dish_count", min=3, max=4), True, "3 dishes, allowed 3-4"),
        (DishCount(type="dish_count", min=4), False, "3 dishes, allowed 4-∞"),
        (DishTypeCount(type="dish_type_count", dish_type="soup", min=1, max=1), True, "1 soup dishes, allowed 1-1"),
        (DishTypeCount(type="dish_type_count", dish_type="meat", min=1), False, "0 meat dishes, allowed 1-∞"),
        (DishTypeCount(type="dish_type_count", dish_type="vegetarian", max=1), False, "2 vegetarian dishes, allowed 0-1"),
    ],
)
def test_check_count(dishes, rule, passed, detail):
    meal = [dishes["dish_0001"], dishes["dish_0003"], dishes["dish_0005"]]
    assert check_count(meal, rule) == CheckResult(passed, detail)


def test_exclusion_by_category_and_id(dishes, ingredients):
    no_seafood = IngredientExclusion(type="ingredient_exclusion", categories=("seafood",))
    no_egg = IngredientExclusion(type="ingredient_exclusion", ingredient_ids=("ing_egg",))
    assert exclusion_hits(dishes["dish_0006"], no_seafood, ingredients) == ["ing_shrimp"]
    assert exclusion_hits(dishes["dish_0001"], no_seafood, ingredients) == []
    assert exclusion_hits(dishes["dish_0001"], no_egg, ingredients) == ["ing_egg"]
    assert exclusion_hits(dishes["dish_0005"], no_egg, ingredients) == ["ing_egg"]


MONDAY = date(2026, 10, 19)


def _dinners(*day_offsets, dish="dish_0001"):
    return [Dinner(date=MONDAY + timedelta(days=d), dish_ids=(dish,)) for d in day_offsets]


@pytest.mark.parametrize(
    "offsets, weeks, repeated_days",
    [
        ((0, 6), 1, [6]),  # 6 days apart: inside a one-week window
        ((0, 7), 1, []),  # same weekday next week: allowed with a one-week window
        ((0, 7), 2, [7]),
        ((0, 13), 2, [13]),
        ((0, 14), 2, []),
        ((0, 25), 4, [25]),  # four weeks covers the whole plan
    ],
)
def test_repeat_window_boundaries(offsets, weeks, repeated_days):
    repeats = find_repeats(_dinners(*offsets), weeks)
    assert [r.days_apart for r in repeats] == repeated_days


def test_every_pair_inside_the_window_is_reported():
    repeats = find_repeats(_dinners(0, 2, 4, 9), 1)
    assert [(r.first.day, r.second.day) for r in repeats] == [(19, 21), (19, 23), (21, 23), (23, 28)]


def test_repeats_across_previous_menu_history():
    previous = [Dinner(date=MONDAY - timedelta(days=3), dish_ids=("dish_0002",))]
    current = [Dinner(date=MONDAY, dish_ids=("dish_0002",))]
    [repeat] = find_repeats(previous + current, 1)
    assert repeat.days_apart == 3

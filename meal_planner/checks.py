"""Deterministic meal composition, ingredient exclusion and repetition checks.

These are the building blocks of the menu validator (Phase 4). Each returns
enough detail to explain its result to the user.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from .constraint_types import DishCount, DishTypeCount, IngredientExclusion
from .models import Dinner, Dish, Ingredient
from .vocab import DishType


@dataclass(frozen=True)
class CheckResult:
    passed: bool
    detail: str


def count_dish_types(dishes: Sequence[Dish]) -> Counter[DishType]:
    return Counter(d.dish_type for d in dishes)


def check_count(dishes: Sequence[Dish], rule: DishCount | DishTypeCount) -> CheckResult:
    if isinstance(rule, DishTypeCount):
        actual, what = count_dish_types(dishes)[rule.dish_type], f"{rule.dish_type} dishes"
    else:
        actual, what = len(dishes), "dishes"
    passed = (rule.min is None or actual >= rule.min) and (rule.max is None or actual <= rule.max)
    bounds = f"{rule.min if rule.min is not None else 0}-{rule.max if rule.max is not None else '∞'}"
    return CheckResult(passed, f"{actual} {what}, allowed {bounds}")


def exclusion_hits(dish: Dish, rule: IngredientExclusion, ingredients: Mapping[str, Ingredient]) -> list[str]:
    """Ingredient IDs in `dish` that the rule excludes (by ID or by category)."""
    hits = []
    for line in dish.ingredients:
        ing = ingredients.get(line.ingredient_id) if line.ingredient_id else None
        if line.ingredient_id in rule.ingredient_ids or (ing is not None and ing.category in rule.categories):
            hits.append(line.ingredient_id)
    return list(dict.fromkeys(hits))


@dataclass(frozen=True)
class Repeat:
    dish_id: str
    first: date
    second: date

    @property
    def days_apart(self) -> int:
        return (self.second - self.first).days


def find_repeats(dinners: Sequence[Dinner], weeks: int) -> list[Repeat]:
    """Pairs of dinners that serve the same dish less than `weeks` * 7 days apart.

    The window slides over calendar days: with weeks=1 a dish may return on the
    same weekday of the next week, but not earlier. `dinners` may include earlier
    menus so that repetition across plans is detected too.
    """
    window_days = weeks * 7
    last_seen: dict[str, date] = {}
    repeats = []
    for dinner in sorted(dinners, key=lambda d: d.date):
        for dish_id in dinner.dish_ids:
            previous = last_seen.get(dish_id)
            if previous is not None and (dinner.date - previous).days < window_days:
                repeats.append(Repeat(dish_id, previous, dinner.date))
            last_seen[dish_id] = dinner.date
    return repeats

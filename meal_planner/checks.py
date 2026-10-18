"""Deterministic meal composition, ingredient and repetition checks.

These are the building blocks of the menu validator (Phase 4). Each returns
enough detail to explain its result to the user.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from .constraint_types import DishCount, DishTypeCount, IngredientExclusion, MatchingDishCount, NoSharedIngredients
from .models import Dinner, Dish, Ingredient
from .vocab import DishType


@dataclass(frozen=True)
class CheckResult:
    passed: bool
    detail: str


def count_dish_types(dishes: Sequence[Dish]) -> Counter[DishType]:
    return Counter(d.dish_type for d in dishes)


CountRule = DishCount | DishTypeCount | MatchingDishCount


def counted_by(dish: Dish, rule: CountRule, ingredients: Mapping[str, Ingredient]) -> bool:
    """Whether `rule` counts `dish` (the solver and the validator both use this)."""
    if isinstance(rule, DishTypeCount):
        return dish.dish_type == rule.dish_type
    if isinstance(rule, MatchingDishCount):
        if rule.dish_types and dish.dish_type not in rule.dish_types:
            return False
        if not all(getattr(dish, tag) for tag in rule.tags):
            return False
        if not rule.has_ingredient_filter:
            return True
        ids = set(dish.style.main_ingredients) if rule.as_main_ingredient else {
            line.ingredient_id for line in dish.ingredients if line.ingredient_id}
        return any(
            i in rule.contains_ingredient_ids or (i in ingredients and ingredients[i].category in rule.contains_categories)
            for i in ids
        )
    return True


def describe_counted(rule: CountRule) -> str:
    if isinstance(rule, DishTypeCount):
        return f"{rule.dish_type} dishes"
    if isinstance(rule, MatchingDishCount):
        types = f" among {', '.join(rule.dish_types)}" if rule.dish_types else ""
        tagged = f" tagged {', '.join(rule.tags)}" if rule.tags else ""
        if not rule.has_ingredient_filter:
            return f"dishes{tagged}{types}"
        what = ", ".join([*rule.contains_categories, *rule.contains_ingredient_ids])
        return f"dishes{tagged} with {what}{' as main ingredient' if rule.as_main_ingredient else ''}{types}"
    return "dishes"


def check_count(dishes: Sequence[Dish], rule: CountRule, ingredients: Mapping[str, Ingredient] | None = None) -> CheckResult:
    actual = sum(1 for d in dishes if counted_by(d, rule, ingredients or {}))
    what = describe_counted(rule)
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


def counted_ingredients(dish: Dish, rule: NoSharedIngredients, ingredients: Mapping[str, Ingredient]) -> set[str]:
    """Ingredient IDs of `dish` that `rule` compares; ingredients unknown to the catalogue are left out."""
    result = set()
    for line in dish.ingredients:
        ing = ingredients.get(line.ingredient_id) if line.ingredient_id else None
        if ing is None or ing.category in rule.ignore_categories:
            continue
        if not rule.only_categories or ing.category in rule.only_categories:
            result.add(ing.ingredient_id)
    return result


def shared_ingredients(a: Dish, b: Dish, rule: NoSharedIngredients, ingredients: Mapping[str, Ingredient]) -> list[str]:
    return sorted(counted_ingredients(a, rule, ingredients) & counted_ingredients(b, rule, ingredients))


@dataclass(frozen=True)
class Repeat:
    dish_id: str
    first: date
    second: date

    @property
    def days_apart(self) -> int:
        return (self.second - self.first).days


def find_repeats(dinners: Sequence[Dinner], weeks: int) -> list[Repeat]:
    """Every pair of servings of the same dish less than `weeks` * 7 days apart.

    The window slides over calendar days: with weeks=1 a dish may return on the
    same weekday of the next week, but not earlier. `dinners` may include earlier
    menus so that repetition across plans is detected too.
    """
    window_days = weeks * 7
    served: dict[str, list[date]] = {}
    repeats = []
    for dinner in sorted(dinners, key=lambda d: d.date):
        for dish_id in dinner.dish_ids:
            earlier = served.setdefault(dish_id, [])
            repeats += [Repeat(dish_id, e, dinner.date) for e in earlier if (dinner.date - e).days < window_days]
            earlier.append(dinner.date)
    return repeats

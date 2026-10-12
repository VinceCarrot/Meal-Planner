"""Approximate calorie estimation from recipe ingredients.

The estimate is a planning signal, not a nutrition guarantee. Every ingredient
line that cannot be converted is listed with the reason, and the result says how
much of the recipe was covered; a partial sum is never presented as complete.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from .models import Dish, DishIngredient, Ingredient

# Mass units that need no per-ingredient data. Volume units are deliberately
# absent: converting them needs a density, which the user can supply through
# the ingredient's grams_per_unit (for example {ml: 1.03}).
GRAMS_PER_MASS_UNIT = {"g": 1.0, "克": 1.0, "kg": 1000.0, "公斤": 1000.0, "千克": 1000.0, "斤": 500.0, "两": 50.0}


@dataclass(frozen=True)
class MissingLine:
    ingredient: str  # ingredient_id, or the unmatched name
    reason: str


@dataclass(frozen=True)
class CalorieEstimate:
    known_kcal: float  # sum over the lines that could be converted
    lines_total: int
    lines_known: int
    missing: tuple[MissingLine, ...]
    servings: int | None

    @property
    def complete(self) -> bool:
        return not self.missing

    @property
    def coverage(self) -> float:
        """Share of ingredient lines included in `known_kcal` (0-1)."""
        return self.lines_known / self.lines_total if self.lines_total else 0.0

    @property
    def total_kcal(self) -> float | None:
        """Whole-dish calories, only when every line was converted."""
        return self.known_kcal if self.complete else None

    @property
    def per_serving_kcal(self) -> float | None:
        if self.total_kcal is None or not self.servings:
            return None
        return self.total_kcal / self.servings


def line_grams(line: DishIngredient, ingredient: Ingredient | None) -> tuple[float | None, str | None]:
    """Grams for one recipe line, or (None, reason)."""
    if line.quantity is None:
        return None, "no quantity" + (f" ({line.note})" if line.note else "")
    if line.unit in GRAMS_PER_MASS_UNIT:
        return line.quantity * GRAMS_PER_MASS_UNIT[line.unit], None
    if ingredient is not None and line.unit in ingredient.grams_per_unit:
        return line.quantity * ingredient.grams_per_unit[line.unit], None
    return None, f"no gram weight for unit '{line.unit}'"


def estimate_dish_calories(dish: Dish, ingredients: Mapping[str, Ingredient]) -> CalorieEstimate:
    known_kcal, known, missing = 0.0, 0, []
    for line in dish.ingredients:
        if line.ingredient_id is None:
            missing.append(MissingLine(line.unmatched_name, "ingredient not in catalogue"))
            continue
        ingredient = ingredients.get(line.ingredient_id)
        if ingredient is None:
            missing.append(MissingLine(line.ingredient_id, "unknown ingredient"))
            continue
        grams, reason = line_grams(line, ingredient)
        if grams is None:
            missing.append(MissingLine(line.ingredient_id, reason))
            continue
        if ingredient.kcal_per_100g is None:
            missing.append(MissingLine(line.ingredient_id, "no kcal_per_100g"))
            continue
        known_kcal += grams * ingredient.kcal_per_100g / 100
        known += 1
    return CalorieEstimate(
        known_kcal=known_kcal,
        lines_total=len(dish.ingredients),
        lines_known=known,
        missing=tuple(missing),
        servings=dish.servings,
    )

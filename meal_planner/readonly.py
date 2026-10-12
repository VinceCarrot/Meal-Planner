"""Read-only data access for AI workflows.

This is the only data object AI tools receive. It holds an in-memory snapshot,
has no reference to the data directory or `DataStore`, and returns immutable
records (ingredients are deep-copied because `grams_per_unit` is a dict), so the
ingredient master data cannot be changed through it. Pending and rejected dishes
are not visible as approved dishes.
"""

from .catalogue import Catalogue
from .models import Dish, Ingredient


class ReadOnlyCatalogue:
    __slots__ = ("_ingredients", "_dishes")

    def __init__(self, catalogue: Catalogue):
        self._ingredients = {i.ingredient_id: i for i in catalogue.ingredients.ingredients}
        self._dishes = {d.dish_id: d for d in catalogue.dishes.dishes}

    def ingredients(self) -> tuple[Ingredient, ...]:
        return tuple(i.model_copy(deep=True) for i in self._ingredients.values())

    def ingredient(self, ingredient_id: str) -> Ingredient | None:
        found = self._ingredients.get(ingredient_id)
        return found.model_copy(deep=True) if found else None

    def approved_dishes(self) -> tuple[Dish, ...]:
        return tuple(self._dishes.values())

    def approved_dish(self, dish_id: str) -> Dish | None:
        return self._dishes.get(dish_id)

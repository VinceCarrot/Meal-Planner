"""Read-only tools offered to agent calls (ADR-012).

Tools are built from a `ReadOnlyCatalogue` only, so no tool can reach the data
directory or write anything. They return plain JSON-compatible data.
"""

from .llm import Tool
from .models import Dish, Ingredient
from .readonly import ReadOnlyCatalogue


def catalogue_tools(view: ReadOnlyCatalogue) -> list[Tool]:
    def list_ingredients(category: str | None = None) -> list[dict]:
        """List catalogue ingredients, optionally only one category
        (vegetable, meat, poultry, seafood, egg, soy, mushroom, grain, seasoning, other)."""
        return [_ingredient(i) for i in view.ingredients() if category is None or i.category == category]

    def search_ingredients(keyword: str) -> list[dict]:
        """Find ingredients whose Chinese name, English name or alias contains the keyword."""
        keyword = keyword.strip().lower()
        return [
            _ingredient(i)
            for i in view.ingredients()
            if keyword and any(keyword in name.lower() for name in (i.name_zh, i.name_en or "", *i.aliases))
        ]

    def list_dishes(dish_type: str | None = None) -> list[dict]:
        """List approved dishes (optionally one dish_type: vegetarian, mixed, meat, soup) to avoid duplicates."""
        return [_dish(d) for d in view.approved_dishes() if dish_type is None or d.dish_type == dish_type]

    return [
        Tool("list_ingredients", list_ingredients.__doc__, list_ingredients),
        Tool("search_ingredients", search_ingredients.__doc__, search_ingredients),
        Tool("list_dishes", list_dishes.__doc__, list_dishes),
    ]


def _ingredient(i: Ingredient) -> dict:
    return {"ingredient_id": i.ingredient_id, "name_zh": i.name_zh, "aliases": list(i.aliases), "category": i.category.value}


def _dish(d: Dish) -> dict:
    return {
        "dish_id": d.dish_id,
        "name_zh": d.name_zh,
        "dish_type": d.dish_type.value,
        "main_ingredients": list(d.style.main_ingredients),
        "cooking_method": d.style.cooking_method.value if d.style.cooking_method else None,
    }

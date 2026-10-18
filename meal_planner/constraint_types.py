"""Registry of executable constraint types.

Each type is a typed parameter model selected by its `type` field. Adding a type
means adding a model here, registering it in `CONSTRAINT_TYPES`, and adding its
validator/objective code and tests; an LLM can only choose among these types.
The docstrings are shown to the constraint parser as the type descriptions.
Calorie constraints are deliberately absent (ADR-008).
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .vocab import DishType, IngredientCategory, IngredientId

Weeks = Annotated[int, Field(ge=1, le=4)]
Weekday = Annotated[int, Field(ge=1, le=5)]  # 1 = Monday ... 5 = Friday


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _unique(values, what: str):
    if len(set(values)) != len(values):
        raise ValueError(f"{what} must not repeat")


class _Range(Params):
    min: Annotated[int, Field(ge=0)] | None = None
    max: Annotated[int, Field(ge=0)] | None = None
    weekdays: tuple[Weekday, ...] = ()  # empty: every dinner

    @model_validator(mode="after")
    def _check_range(self):
        if self.min is None and self.max is None:
            raise ValueError("at least one of min or max is required")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must not exceed max")
        _unique(self.weekdays, "weekdays")
        return self

    def applies_on(self, weekday: int) -> bool:
        return not self.weekdays or weekday in self.weekdays


class DishCount(_Range):
    """Number of dishes in a dinner, soup included. weekdays (1=Monday ... 5=Friday) limits the rule to
    those dinners; empty means every dinner."""

    type: Literal["dish_count"]


class DishTypeCount(_Range):
    """Number of dishes of one dish type in a dinner. weekdays as in dish_count.
    Example: 周一、三、五要有一个汤 -> dish_type soup, min 1, max 1, weekdays [1, 3, 5]."""

    type: Literal["dish_type_count"]
    dish_type: DishType


class MatchingDishCount(_Range):
    """Number of dishes in a dinner whose dish type is in dish_types (empty: all types) and, if
    contains_categories or contains_ingredient_ids is given, that contain any of them. as_main_ingredient true
    counts a dish only when the ingredient is one of its main ingredients; false counts any use. weekdays as
    in dish_count. Examples: 每顿饭3-4个菜（不包含汤） -> dish_types [vegetarian, mixed, meat], min 3, max 4;
    每顿饭（不含汤）要有一道菜用绿叶菜 -> dish_types [vegetarian, mixed, meat], contains_categories
    [leafy_green], as_main_ingredient true, min 1."""

    type: Literal["matching_dish_count"]
    dish_types: tuple[DishType, ...] = ()
    contains_categories: tuple[IngredientCategory, ...] = ()
    contains_ingredient_ids: tuple[IngredientId, ...] = ()
    as_main_ingredient: bool = True

    @model_validator(mode="after")
    def _check_filter(self):
        if not self.dish_types and not self.contains_categories and not self.contains_ingredient_ids:
            raise ValueError("at least one of dish_types, contains_categories or contains_ingredient_ids is required")
        return self

    @property
    def has_ingredient_filter(self) -> bool:
        return bool(self.contains_categories or self.contains_ingredient_ids)


CountRule = Annotated[Union[DishCount, DishTypeCount, MatchingDishCount], Field(discriminator="type")]
COUNT_TYPES = (DishCount, DishTypeCount, MatchingDishCount)


class AnyOf(Params):
    """Each dinner must satisfy at least one of 2-4 alternative count rules (dish_count, dish_type_count or
    matching_dish_count; no nesting). Put weekdays on any_of itself, not on the alternatives.
    Example: 每顿饭要有一个大荤菜，或两个荤素搭配菜 -> alternatives
    [dish_type_count meat min 1, dish_type_count mixed min 2]."""

    type: Literal["any_of"]
    alternatives: Annotated[tuple[CountRule, ...], Field(min_length=2, max_length=4)]
    weekdays: tuple[Weekday, ...] = ()

    @model_validator(mode="after")
    def _check(self):
        if any(a.weekdays for a in self.alternatives):
            raise ValueError("alternatives must not set weekdays; set weekdays on any_of")
        _unique(self.weekdays, "weekdays")
        return self

    def applies_on(self, weekday: int) -> bool:
        return not self.weekdays or weekday in self.weekdays


class IngredientExclusion(Params):
    """Dishes containing these ingredients or ingredient categories are not used."""

    type: Literal["ingredient_exclusion"]
    ingredient_ids: tuple[IngredientId, ...] = ()
    categories: tuple[IngredientCategory, ...] = ()

    @model_validator(mode="after")
    def _check(self):
        if not self.ingredient_ids and not self.categories:
            raise ValueError("at least one ingredient_id or category is required")
        return self


class NoSharedIngredients(Params):
    """Two dishes in the same dinner must not use the same ingredient (compared by ingredient ID).
    Ingredients of ignore_categories never count (default: seasoning and aromatic). If only_categories is
    given, only ingredients of those categories count.
    Example: 每顿饭的食材不要重复（不包括调味菜） -> the defaults."""

    type: Literal["no_shared_ingredients"]
    ignore_categories: tuple[IngredientCategory, ...] = (IngredientCategory.SEASONING, IngredientCategory.AROMATIC)
    only_categories: tuple[IngredientCategory, ...] = ()


class ExactRepeatWindow(Params):
    """The same dish must not appear twice within this many weeks (4 = whole plan)."""

    type: Literal["exact_repeat_window"]
    weeks: Weeks


SimilarityFeature = Literal["overall", "main_ingredients", "ingredients", "cooking_method", "flavours", "cuisine"]


class DishSimilarity(Params):
    """Discourage similar dishes served close together. Compared pairs: dishes in the same dinner (when
    same_dinner is true) and dishes of different dinners less than window_days calendar days apart
    (1: same dinner only; 2: the next calendar day, so Friday and the next Monday are not adjacent; 7: one
    week). window_weeks is used when window_days is not given. feature selects what is compared: overall
    (weighted dish similarity) or one aspect: main_ingredients, ingredients (shared ingredients, seasonings
    and aromatics excluded), cooking_method, flavours, cuisine. Dishes of skip_dish_types are not compared.
    No max_similarity means the configured default.
    Examples: 每顿饭的菜品口味尽量不相似 -> soft, feature flavours, window_days 1, skip_dish_types [soup];
    相邻两天的菜品食材尽量不相似 -> soft, feature ingredients, window_days 2, same_dinner false."""

    type: Literal["dish_similarity"]
    max_similarity: Annotated[float, Field(gt=0, le=1)] | None = None
    window_weeks: Weeks = 1
    window_days: Annotated[int, Field(ge=1, le=28)] | None = None
    same_dinner: bool = True
    feature: SimilarityFeature = "overall"
    skip_dish_types: tuple[DishType, ...] = ()

    @model_validator(mode="after")
    def _check(self):
        if self.days == 1 and not self.same_dinner:
            raise ValueError("window_days 1 with same_dinner false compares nothing")
        return self

    @property
    def days(self) -> int:
        return self.window_days if self.window_days is not None else self.window_weeks * 7


class MealSimilarity(Params):
    """Discourage similar whole dinners within the window (normalized greedy-matching score)."""

    type: Literal["meal_similarity"]
    max_similarity: Annotated[float, Field(gt=0, le=1)] | None = None
    window_weeks: Weeks = 1


Execution = Annotated[
    Union[
        DishCount, DishTypeCount, MatchingDishCount, AnyOf, IngredientExclusion, NoSharedIngredients,
        ExactRepeatWindow, DishSimilarity, MealSimilarity,
    ],
    Field(discriminator="type"),
]

CONSTRAINT_TYPES: dict[str, type[Params]] = {
    "dish_count": DishCount,
    "dish_type_count": DishTypeCount,
    "matching_dish_count": MatchingDishCount,
    "any_of": AnyOf,
    "ingredient_exclusion": IngredientExclusion,
    "no_shared_ingredients": NoSharedIngredients,
    "exact_repeat_window": ExactRepeatWindow,
    "dish_similarity": DishSimilarity,
    "meal_similarity": MealSimilarity,
}

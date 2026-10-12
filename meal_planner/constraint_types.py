"""Registry of executable constraint types.

Each type is a typed parameter model selected by its `type` field. Adding a type
means adding a model here, registering it in `CONSTRAINT_TYPES`, and adding its
validator/objective code and tests; an LLM can only choose among these types.
Calorie constraints are deliberately absent (ADR-008).
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .vocab import DishType, IngredientCategory, IngredientId

Weeks = Annotated[int, Field(ge=1, le=4)]


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Range(Params):
    min: Annotated[int, Field(ge=0)] | None = None
    max: Annotated[int, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def _check_range(self):
        if self.min is None and self.max is None:
            raise ValueError("at least one of min or max is required")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must not exceed max")
        return self


class DishCount(_Range):
    """Number of dishes in every dinner, soup included."""

    type: Literal["dish_count"]


class DishTypeCount(_Range):
    """Number of dishes of one dish type in every dinner."""

    type: Literal["dish_type_count"]
    dish_type: DishType


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


class ExactRepeatWindow(Params):
    """The same dish must not appear twice within this many weeks (4 = whole plan)."""

    type: Literal["exact_repeat_window"]
    weeks: Weeks


class DishSimilarity(Params):
    """Discourage similar dishes within the window. No threshold means the configured default."""

    type: Literal["dish_similarity"]
    max_similarity: Annotated[float, Field(gt=0, le=1)] | None = None
    window_weeks: Weeks = 1


class MealSimilarity(Params):
    """Discourage similar whole dinners within the window (normalized greedy-matching score)."""

    type: Literal["meal_similarity"]
    max_similarity: Annotated[float, Field(gt=0, le=1)] | None = None
    window_weeks: Weeks = 1


Execution = Annotated[
    Union[DishCount, DishTypeCount, IngredientExclusion, ExactRepeatWindow, DishSimilarity, MealSimilarity],
    Field(discriminator="type"),
]

CONSTRAINT_TYPES: dict[str, type[Params]] = {
    "dish_count": DishCount,
    "dish_type_count": DishTypeCount,
    "ingredient_exclusion": IngredientExclusion,
    "exact_repeat_window": ExactRepeatWindow,
    "dish_similarity": DishSimilarity,
    "meal_similarity": MealSimilarity,
}

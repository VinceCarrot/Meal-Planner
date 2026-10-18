"""Versioned schemas for the YAML data files.

All records are immutable (frozen models, tuples instead of lists) so that data
handed to read-only callers, including AI tools, cannot be modified in place.
Unknown fields are rejected so that typos in hand-edited YAML are reported.
"""

from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .constraint_types import Execution
from .vocab import (
    IngredientCategory,
    DishType,
    CookingMethod,
    Flavour,
    DishSource,
    ReviewStatus,
    CalorieBasis,
    TaskScope,
    Strictness,
    ConstraintSource,
    ParseStatus,
    FeedbackScope,
    IngredientId,
)

SCHEMA_VERSION = 1
DINNERS_PER_MENU = 20

DishId = Annotated[str, Field(pattern=r"^dish_\d{4,}$")]
ConstraintId = Annotated[str, Field(pattern=r"^[CT]\d{3,}$")]  # C: persistent, T: task-scoped
FeedbackId = Annotated[str, Field(pattern=r"^F\d{3,}$")]
MenuId = Annotated[str, Field(pattern=r"^M\d{3,}$")]
NonEmptyStr = Annotated[str, Field(min_length=1)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- Ingredients -------------------------------------------------------------


class Ingredient(Record):
    ingredient_id: IngredientId
    name_zh: NonEmptyStr
    name_en: str | None = None
    aliases: tuple[NonEmptyStr, ...] = ()
    category: IngredientCategory
    kcal_per_100g: Annotated[float, Field(ge=0)] | None = None
    grams_per_unit: dict[NonEmptyStr, Annotated[float, Field(gt=0)]] = Field(default_factory=dict)
    notes: str | None = None


class IngredientsFile(Record):
    schema_version: Literal[1] = SCHEMA_VERSION
    ingredients: tuple[Ingredient, ...] = ()


# --- Dishes ------------------------------------------------------------------


class DishIngredient(Record):
    """One ingredient line of a recipe.

    `unmatched_name` holds an ingredient mention that has no catalogue entry yet
    (for example from AI generation or video import). It is allowed only in
    pending dishes and must be resolved by the user before approval.
    """

    ingredient_id: IngredientId | None = None
    unmatched_name: NonEmptyStr | None = None
    quantity: Annotated[float, Field(gt=0)] | None = None
    unit: NonEmptyStr | None = None
    note: str | None = None  # for example "适量"

    @model_validator(mode="after")
    def _check(self):
        if (self.ingredient_id is None) == (self.unmatched_name is None):
            raise ValueError("exactly one of ingredient_id or unmatched_name is required")
        if self.quantity is not None and self.unit is None:
            raise ValueError("unit is required when quantity is given")
        return self


class DishStyle(Record):
    main_ingredients: tuple[IngredientId, ...] = ()
    cooking_method: CookingMethod | None = None
    flavours: tuple[Flavour, ...] = ()
    cuisine: str | None = None


class Dish(Record):
    dish_id: DishId
    name_zh: NonEmptyStr
    name_en: str | None = None
    dish_type: DishType
    ingredients: Annotated[tuple[DishIngredient, ...], Field(min_length=1)]
    servings: Annotated[int, Field(gt=0)] | None = None
    steps: tuple[NonEmptyStr, ...] = ()
    calories_kcal: Annotated[float, Field(ge=0)] | None = None  # whole dish
    calorie_basis: CalorieBasis | None = None
    style: DishStyle = DishStyle()
    source: DishSource
    source_url: str | None = None
    review_status: ReviewStatus
    frequent: bool = True  # 常用菜: offered by menu generation (ADR-026)
    uncertainty_notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.calories_kcal is not None and self.calorie_basis is None:
            raise ValueError("calorie_basis is required when calories_kcal is given")
        return self


class DishesFile(Record):
    schema_version: Literal[1] = SCHEMA_VERSION
    dishes: tuple[Dish, ...] = ()


# --- Constraints -------------------------------------------------------------


_NO_EXECUTION = (ParseStatus.UNPARSED, ParseStatus.NEEDS_CLARIFICATION, ParseStatus.UNSUPPORTED)


class Constraint(Record):
    constraint_id: ConstraintId
    description: NonEmptyStr  # original natural-language text, never discarded
    scope: Annotated[tuple[TaskScope, ...], Field(min_length=1)]
    strictness: Strictness
    source: ConstraintSource
    execution: Execution | None = None  # typed parameters from the constraint registry
    parse_status: ParseStatus = ParseStatus.UNPARSED
    parse_notes: str | None = None  # limitation, ambiguity or conflict explanation
    # Task constraints only: persistent constraints this one explicitly replaces for the task.
    overrides: tuple[ConstraintId, ...] = ()
    active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def _check(self):
        if len(set(self.scope)) != len(self.scope):
            raise ValueError("scope contains duplicates")
        prefix = "C" if self.source == ConstraintSource.PERSISTENT else "T"
        if not self.constraint_id.startswith(prefix):
            raise ValueError(f"{self.source} constraint IDs start with '{prefix}'")
        if self.overrides and self.source != ConstraintSource.TASK:
            raise ValueError("only task constraints can override other constraints")
        if self.parse_status in (ParseStatus.EXECUTABLE, ParseStatus.APPROXIMATED) and self.execution is None:
            raise ValueError(f"parse_status '{self.parse_status}' requires execution")
        if self.parse_status in _NO_EXECUTION and self.execution is not None:
            raise ValueError(f"parse_status '{self.parse_status}' must not have execution")
        return self


class ConstraintsFile(Record):
    schema_version: Literal[1] = SCHEMA_VERSION
    constraints: tuple[Constraint, ...] = ()


# --- Preferences and feedback ------------------------------------------------


class Diner(Record):
    description: NonEmptyStr  # for example "成年女性" or "6岁儿童"
    count: Annotated[int, Field(gt=0)]


class Feedback(Record):
    feedback_id: FeedbackId
    dish_id: DishId
    kind: Literal["dislike"]
    scope: FeedbackScope
    menu_id: MenuId | None = None
    note: str | None = None
    created_at: datetime | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.scope == FeedbackScope.THIS_MENU and self.menu_id is None:
            raise ValueError("menu_id is required for scope 'this_menu'")
        return self


class PreferencesFile(Record):
    schema_version: Literal[1] = SCHEMA_VERSION
    default_diners: tuple[Diner, ...] = ()
    feedback: tuple[Feedback, ...] = ()


# --- Menus -------------------------------------------------------------------


def plan_dates(start_date: date) -> list[date]:
    """The 20 Monday-Friday dates of a four-week plan starting on a Monday."""
    return [start_date + timedelta(weeks=w, days=d) for w in range(4) for d in range(5)]


class Dinner(Record):
    date: date
    dish_ids: Annotated[tuple[DishId, ...], Field(min_length=1)]


class MenuVersion(Record):
    """One immutable version of a menu, stored at data/menus/<menu_id>/v<NNN>.yaml."""

    schema_version: Literal[1] = SCHEMA_VERSION
    menu_id: MenuId
    version: Annotated[int, Field(gt=0)]
    based_on_version: Annotated[int, Field(gt=0)] | None = None
    start_date: date
    diners: Annotated[tuple[Diner, ...], Field(min_length=1)]
    dinners: tuple[Dinner, ...]
    # Effective constraints used for this version, including task-scoped ones.
    constraint_snapshot: tuple[Constraint, ...] = ()
    # Structure defined with the validator in Phase 4.
    validation_report: dict[str, Any] | None = None
    change_note: str | None = None
    created_at: datetime

    @model_validator(mode="after")
    def _check(self):
        if self.start_date.weekday() != 0:
            raise ValueError(f"start_date {self.start_date} is not a Monday")
        expected = plan_dates(self.start_date)
        actual = [d.date for d in self.dinners]
        if actual != expected:
            raise ValueError(
                f"dinners must cover exactly the {DINNERS_PER_MENU} weekdays from "
                f"{expected[0]} to {expected[-1]} in order"
            )
        if self.based_on_version is not None and self.based_on_version >= self.version:
            raise ValueError("based_on_version must be lower than version")
        return self

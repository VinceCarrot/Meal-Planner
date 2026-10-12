"""Versioned schemas for the YAML data files.

All records are immutable (frozen models, tuples instead of lists) so that data
handed to read-only callers, including AI tools, cannot be modified in place.
Unknown fields are rejected so that typos in hand-edited YAML are reported.
"""

from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1
DINNERS_PER_MENU = 20

IngredientId = Annotated[str, Field(pattern=r"^ing_[a-z0-9_]+$")]
DishId = Annotated[str, Field(pattern=r"^dish_\d{4,}$")]
ConstraintId = Annotated[str, Field(pattern=r"^C\d{3,}$")]
FeedbackId = Annotated[str, Field(pattern=r"^F\d{3,}$")]
MenuId = Annotated[str, Field(pattern=r"^M\d{3,}$")]
NonEmptyStr = Annotated[str, Field(min_length=1)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- Controlled vocabularies -------------------------------------------------


class IngredientCategory(StrEnum):
    VEGETABLE = "vegetable"
    MEAT = "meat"
    POULTRY = "poultry"
    SEAFOOD = "seafood"
    EGG = "egg"
    SOY = "soy"
    MUSHROOM = "mushroom"
    GRAIN = "grain"
    SEASONING = "seasoning"
    OTHER = "other"


class DishType(StrEnum):
    VEGETARIAN = "vegetarian"
    MIXED = "mixed"
    MEAT = "meat"
    SOUP = "soup"


class CookingMethod(StrEnum):
    STIR_FRY = "stir_fry"  # 炒、爆、干煸
    STEAM = "steam"  # 蒸
    BRAISE = "braise"  # 红烧、焖、烧
    STEW = "stew"  # 炖、煲
    BOIL = "boil"  # 煮、汆、白灼
    DEEP_FRY = "deep_fry"  # 炸
    PAN_FRY = "pan_fry"  # 煎
    ROAST = "roast"  # 烤
    COLD_MIX = "cold_mix"  # 凉拌
    OTHER = "other"


class Flavour(StrEnum):
    LIGHT = "light"  # 清淡
    SALTY_SAVORY = "salty_savory"  # 咸鲜
    SOY_SAUCE = "soy_sauce"  # 酱香
    SWEET_SOUR = "sweet_sour"  # 酸甜
    SOUR = "sour"  # 酸
    SWEET = "sweet"  # 甜
    SPICY = "spicy"  # 辣
    NUMBING_SPICY = "numbing_spicy"  # 麻辣
    GARLICKY = "garlicky"  # 蒜香
    FISH_FRAGRANT = "fish_fragrant"  # 鱼香
    OTHER = "other"


class DishSource(StrEnum):
    MANUAL = "manual"
    AI_GENERATED = "ai_generated"
    VIDEO_IMPORTED = "video_imported"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class CalorieBasis(StrEnum):
    COMPUTED = "computed"  # derived from ingredient data
    ESTIMATED = "estimated"  # entered or estimated without full ingredient data


class TaskScope(StrEnum):
    MENU_GENERATION = "menu_generation"
    MENU_ADJUSTMENT = "menu_adjustment"


class Strictness(StrEnum):
    HARD = "hard"
    SOFT = "soft"


class ConstraintSource(StrEnum):
    PERSISTENT = "persistent"
    TASK = "task"


class ParseStatus(StrEnum):
    UNPARSED = "unparsed"  # entered but not yet parsed
    EXECUTABLE = "executable"
    APPROXIMATED = "approximated"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED = "unsupported"
    CONFLICT = "conflict"


class FeedbackScope(StrEnum):
    THIS_MENU = "this_menu"
    FUTURE_MENUS = "future_menus"
    PERSISTENT = "persistent"


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


class Constraint(Record):
    constraint_id: ConstraintId
    description: NonEmptyStr  # original natural-language text, never discarded
    scope: Annotated[tuple[TaskScope, ...], Field(min_length=1)]
    strictness: Strictness
    source: ConstraintSource
    # Typed parameters are validated against the constraint registry (Phase 2).
    execution: dict[str, Any] | None = None
    parse_status: ParseStatus = ParseStatus.UNPARSED
    parse_notes: str | None = None  # limitation, ambiguity or conflict explanation
    active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def _check(self):
        if len(set(self.scope)) != len(self.scope):
            raise ValueError("scope contains duplicates")
        evaluable = self.parse_status in (ParseStatus.EXECUTABLE, ParseStatus.APPROXIMATED)
        if evaluable and not (self.execution and "type" in self.execution):
            raise ValueError(f"parse_status '{self.parse_status}' requires execution with a 'type'")
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

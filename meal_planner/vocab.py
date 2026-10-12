"""Controlled vocabularies shared by the data schemas and the constraint registry."""

from enum import StrEnum
from typing import Annotated

from pydantic import Field

IngredientId = Annotated[str, Field(pattern=r"^ing_[a-z0-9_]+$")]


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

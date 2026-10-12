"""Targeted candidate-dish generation for catalogue gaps.

Claude drafts dishes in an agent call with read-only catalogue tools. Every
draft is treated as untrusted: it must match the schema, the requested dish
type, the hard exclusions and the ingredient catalogue, and must not duplicate an
existing dish name. Valid drafts are stored as pending dishes only; nothing here
writes approved dishes or ingredients. Ingredients that are not in the catalogue
may only appear as `unmatched_name` lines, which the user resolves in review.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, ValidationError

from .ai_tools import catalogue_tools
from .catalogue import Catalogue
from .checks import exclusion_hits
from .constraint_types import IngredientExclusion
from .constraints import EffectiveConstraintSet
from .llm import LLMBackend
from .models import Dish, DishesFile
from .planner import CatalogueGap
from .readonly import ReadOnlyCatalogue
from .settings import CandidateSettings
from .store import DataStore
from .vocab import CookingMethod, DishType, Flavour, Strictness


class DraftLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingredient_id: str | None = None
    unmatched_name: str | None = None
    quantity: float | None = None
    unit: str | None = None
    note: str | None = None


class DraftStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    main_ingredients: list[str]
    cooking_method: CookingMethod
    flavours: list[Flavour]
    cuisine: str | None = None


class DraftDish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_zh: str
    name_en: str | None = None
    dish_type: DishType
    servings: int
    ingredients: list[DraftLine]
    steps: list[str]
    style: DraftStyle
    uncertainty_notes: str | None = None


class DraftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dishes: list[DraftDish]


SYSTEM_PROMPT = """\
You create home-cooking dinner recipes for a family, in Chinese, as candidates for the user's dish catalogue.

Rules:
- Use the tools to look up ingredients. Use only ingredient IDs returned by the tools.
- If a recipe really needs an ingredient that the catalogue does not have, put its Chinese name in \
unmatched_name (with ingredient_id null); the user will decide later. Prefer catalogue ingredients.
- Check existing dishes with list_dishes and do not repeat them; vary cooking methods and flavours.
- Give quantities in g where possible; for seasonings without a fixed amount, leave quantity null and write e.g. "适量" in note.
- servings is the number of portions the recipe makes. Steps are short Chinese sentences.
- style.main_ingredients lists the 1-2 defining ingredient IDs.
- Put any doubt about quantities or method in uncertainty_notes.
"""


@dataclass(frozen=True)
class CandidateRequest:
    dish_type: DishType | None  # None: any type
    count: int
    reason: str


@dataclass(frozen=True)
class GenerationResult:
    added: tuple[Dish, ...]
    rejected: tuple[tuple[str, str], ...]  # (dish name or position, reason)


def requests_for_gaps(gaps: Sequence[CatalogueGap], settings: CandidateSettings) -> list[CandidateRequest]:
    return [
        CandidateRequest(
            dish_type=gap.dish_type,
            count=max(settings.minimum, math.ceil(settings.factor * gap.additional_dishes_needed)),
            reason=gap.describe(),
        )
        for gap in gaps
    ]


def hard_exclusions(effective: EffectiveConstraintSet) -> list[IngredientExclusion]:
    return [
        c.execution
        for c in effective.constraints
        if isinstance(c.execution, IngredientExclusion) and c.strictness == Strictness.HARD
    ]


def generate_candidates(
    store: DataStore,
    cat: Catalogue,
    llm: LLMBackend,
    request: CandidateRequest,
    exclusions: Sequence[IngredientExclusion] = (),
) -> tuple[Catalogue, GenerationResult]:
    """Ask for candidate dishes and store the valid ones as pending. Raises LLMError on call failure."""
    view = ReadOnlyCatalogue(cat)
    raw = llm.agent(SYSTEM_PROMPT, _prompt(request, exclusions, view), catalogue_tools(view), DraftOutput.model_json_schema())

    items = raw.get("dishes") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return cat, GenerationResult((), (("(all)", "output has no 'dishes' list"),))

    existing = {d.name_zh for d in cat.dishes.dishes + cat.pending_dishes.dishes}
    next_number = next_dish_number(cat)
    ingredient_ids = {i.ingredient_id for i in view.ingredients()}
    ingredients = {i.ingredient_id: i for i in view.ingredients()}
    added, rejected = [], []

    for n, item in enumerate(items, start=1):
        label = item.get("name_zh") if isinstance(item, dict) and isinstance(item.get("name_zh"), str) else f"#{n}"
        try:
            draft = DraftDish.model_validate(item)
            dish = Dish.model_validate(
                draft.model_dump()
                | {
                    "dish_id": f"dish_{next_number:04d}",
                    "source": "ai_generated",
                    "review_status": "pending",
                    "created_at": datetime.now().replace(microsecond=0),
                }
            )
        except ValidationError as e:
            err = e.errors()[0]
            rejected.append((label, f"invalid: {'.'.join(str(p) for p in err['loc'])}: {err['msg']}"))
            continue

        reason = _problem(dish, request, exclusions, ingredient_ids, ingredients, existing)
        if reason:
            rejected.append((label, reason))
            continue
        added.append(dish)
        existing.add(dish.name_zh)
        next_number += 1

    if added:
        cat = store.save_pending_dishes(cat, DishesFile(dishes=cat.pending_dishes.dishes + tuple(added)))
    return cat, GenerationResult(tuple(added), tuple(rejected))


def _problem(dish, request, exclusions, ingredient_ids, ingredients, existing) -> str | None:
    if request.dish_type is not None and dish.dish_type != request.dish_type:
        return f"dish_type is {dish.dish_type}, requested {request.dish_type}"
    refs = [line.ingredient_id for line in dish.ingredients if line.ingredient_id] + list(dish.style.main_ingredients)
    unknown = sorted({r for r in refs if r not in ingredient_ids})
    if unknown:
        return f"unknown ingredient_id {', '.join(unknown)}"
    for rule in exclusions:
        hits = exclusion_hits(dish, rule, ingredients)
        if hits:
            return f"contains excluded ingredient {', '.join(hits)}"
    if dish.name_zh in existing:
        return "a dish with this name already exists"
    return None


def next_dish_number(cat: Catalogue) -> int:
    numbers = [int(d.dish_id.split("_")[1]) for d in cat.dishes.dishes + cat.pending_dishes.dishes]
    return max(numbers, default=0) + 1


def _prompt(request: CandidateRequest, exclusions: Sequence[IngredientExclusion], view: ReadOnlyCatalogue) -> str:
    kind = f"{request.dish_type} dishes" if request.dish_type else "dishes of any type (vegetarian, mixed, meat, soup)"
    lines = [f"Create {request.count} new {kind}.", f"Why they are needed: {request.reason}"]
    for rule in exclusions:
        names = [i.name_zh for i in (view.ingredient(r) for r in rule.ingredient_ids) if i]
        parts = ([f"categories {', '.join(rule.categories)}"] if rule.categories else []) + ([", ".join(names)] if names else [])
        lines.append(f"Must not contain: {'; '.join(parts)}.")
    return "\n".join(lines)

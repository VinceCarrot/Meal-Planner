"""AI-filled ingredient form from a Chinese name (ADR-022).

Claude proposes the remaining fields of a new ingredient record; nothing is
saved here. The proposal is checked and normalized in code (ID format and
uniqueness, category, value ranges) and returned to the user, who edits it in
the form and saves it through the ordinary ingredient endpoint. Possible
duplicates of existing ingredients are reported as warnings, not refused.
"""

import re
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, ValidationError

from .llm import LLMBackend, LLMError
from .models import Ingredient
from .vocab import IngredientCategory

MAX_KCAL_PER_100G = 900  # pure fat; anything above is not a real food value
MAX_GRAMS_PER_UNIT = 5000


class UnitOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit: str
    grams: float


class SuggestionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_en: str
    aliases: list[str]
    category: IngredientCategory
    kcal_per_100g: float | None = None
    grams_per_unit: list[UnitOut]
    notes: str | None = None


SYSTEM_PROMPT = f"""\
You fill in an ingredient record for a Chinese family recipe catalogue, given the ingredient's Chinese name.

Fields:
- name_en: the common English name, lower case unless a proper noun (e.g. "chicken breast", "napa cabbage").
- aliases: other common Chinese names for the same ingredient (regional names, synonyms). Do not repeat the \
given name. Empty list if none.
- category: one of {", ".join(c.value for c in IngredientCategory)}. Meat is red meat (pork, beef, lamb); \
poultry is chicken, duck, goose; soy is tofu and other soy products; grain covers rice, flour, noodles; \
seasoning covers sauces, spices, oil, salt, sugar.
- kcal_per_100g: energy per 100 g of the raw edible part, from standard food composition tables. null if you \
are not confident.
- grams_per_unit: typical gram weight of the household units used for this ingredient in Chinese recipes, \
as a list of {{unit, grams}} with the Chinese unit (e.g. 个 150, 根 100, 瓣 5, 勺 15, ml 1.0). \
Only units that are actually used for this ingredient; empty list if it is always weighed in grams.
- notes: one short Chinese note only if something is worth knowing (e.g. kcal refers to dried weight); \
otherwise null.

If the name is ambiguous, choose the most common home-cooking meaning and say so in notes.
"""


def suggest_ingredient(
    llm: LLMBackend, name_zh: str, existing: Sequence[Ingredient], editing_id: str | None = None
) -> tuple[dict, list[str]]:
    """Return (proposed ingredient fields, warnings). Never writes anything.

    `editing_id`: the ingredient being edited; it keeps its ID and is not reported as its own duplicate.
    Raises ValueError for an empty name and LLMError if Claude's answer is unusable.
    """
    existing = [i for i in existing if i.ingredient_id != editing_id]
    name_zh = name_zh.strip()
    if not name_zh:
        raise ValueError("请先填写中文名")
    raw = llm.structured(SYSTEM_PROMPT, f"Chinese name: {name_zh}", SuggestionOut.model_json_schema())
    try:
        out = SuggestionOut.model_validate(raw)
    except ValidationError as e:
        err = e.errors()[0]
        raise LLMError(f"invalid ingredient suggestion: {'.'.join(str(p) for p in err['loc'])}: {err['msg']}") from None

    warnings: list[str] = []
    name_en = out.name_en.strip()
    aliases = _unique(a.strip() for a in out.aliases if a.strip() and a.strip() != name_zh)

    kcal = out.kcal_per_100g
    if kcal is not None and not 0 <= kcal <= MAX_KCAL_PER_100G:
        warnings.append(f"模型给出的热量 {kcal} kcal/100g 不合理，已留空")
        kcal = None

    units = {}
    for u in out.grams_per_unit:
        if u.unit.strip() and 0 < u.grams <= MAX_GRAMS_PER_UNIT:
            units[u.unit.strip()] = round(u.grams, 2)
        else:
            warnings.append(f"已忽略不合理的单位克重：{u.unit}={u.grams}")

    taken = {i.ingredient_id for i in existing}
    proposal = {
        "ingredient_id": editing_id or _free_id(_slug(name_en), taken),
        "name_zh": name_zh,
        "name_en": name_en or None,
        "aliases": aliases,
        "category": out.category.value,
        "kcal_per_100g": round(kcal, 1) if kcal is not None else None,
        "grams_per_unit": units,
        "notes": (out.notes or "").strip() or None,
    }
    Ingredient.model_validate(proposal)  # the proposal must be saveable as it stands
    warnings += _duplicates(name_zh, name_en, aliases, existing)
    return proposal, warnings


def _slug(name_en: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name_en.lower()).strip("_")
    return slug or "new"


def _free_id(slug: str, taken: set[str]) -> str:
    candidate, n = f"ing_{slug}", 2
    while candidate in taken:
        candidate, n = f"ing_{slug}_{n}", n + 1
    return candidate


def _unique(items) -> list[str]:
    return list(dict.fromkeys(items))


def _duplicates(name_zh: str, name_en: str, aliases: list[str], existing: Sequence[Ingredient]) -> list[str]:
    names = {name_zh, *aliases} | ({name_en.lower()} if name_en else set())
    found = []
    for i in existing:
        theirs = {i.name_zh, *i.aliases} | ({i.name_en.lower()} if i.name_en else set())
        if names & theirs:
            found.append(f"食材库中可能已有同一种食材：{i.name_zh}（{i.ingredient_id}）")
    return found

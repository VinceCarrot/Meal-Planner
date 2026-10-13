"""English translation of approved recipes for the PDF export (Phase 9, ADR-021).

Claude translates text only (names, units, notes, steps); quantities come from
the recipe data and never pass through the model. Each translation is checked:
the number of ingredient lines and steps must match, no Chinese characters may
remain, and numbers in a step (times, temperatures) must reappear in its
translation, otherwise a warning is kept. Translations are cached in
data/translations.yaml with a hash of the source recipe, so an edited recipe is
translated again and an unchanged one is not.
"""

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from .catalogue import DataError, DataIssue, parse_model
from .llm import LLMBackend
from .models import Dish, Ingredient, Record
from .yaml_io import YamlReadError, read_yaml, write_yaml_atomic

TRANSLATIONS_FILE = "translations.yaml"
BATCH_SIZE = 8  # dishes per Claude call
_CJK = re.compile(r"[㐀-鿿豈-﫿]")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


class DishTranslation(Record):
    dish_id: str
    source_hash: str
    name_en: str
    ingredient_names: tuple[str, ...]  # one per recipe line, in order
    units: tuple[str | None, ...]
    notes: tuple[str | None, ...]
    steps: tuple[str, ...]
    uncertainty_notes: str | None = None
    warnings: tuple[str, ...] = ()
    translated_at: datetime


class TranslationsFile(Record):
    schema_version: Literal[1] = 1
    translations: tuple[DishTranslation, ...] = ()


def load_translations(data_dir: Path) -> dict[str, DishTranslation]:
    path = Path(data_dir) / TRANSLATIONS_FILE
    if not path.exists():
        return {}
    try:
        raw = read_yaml(path)
    except YamlReadError as e:
        raise DataError([DataIssue(TRANSLATIONS_FILE, "", str(e))]) from None
    return {t.dish_id: t for t in parse_model(TranslationsFile, raw, TRANSLATIONS_FILE).translations}


def save_translations(data_dir: Path, translations: dict[str, DishTranslation]) -> None:
    data = TranslationsFile(translations=tuple(translations[k] for k in sorted(translations)))
    write_yaml_atomic(Path(data_dir) / TRANSLATIONS_FILE, data.model_dump(mode="json"))


def source_hash(dish: Dish, ingredients: dict[str, Ingredient]) -> str:
    content = {
        "name": dish.name_zh,
        "lines": [[_line_name(l, ingredients), l.unit, l.note] for l in dish.ingredients],
        "steps": list(dish.steps),
        "notes": dish.uncertainty_notes,
    }
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def _line_name(line, ingredients) -> str:
    if line.ingredient_id and line.ingredient_id in ingredients:
        return ingredients[line.ingredient_id].name_zh
    return line.unmatched_name or line.ingredient_id or ""


# --- Model output ------------------------------------------------------------------------


class LineOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    unit: str | None = None
    note: str | None = None


class DishOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dish_id: str
    name_en: str
    ingredients: list[LineOut]
    steps: list[str]
    uncertainty_notes: str | None = None


class TranslationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dishes: list[DishOut]


SYSTEM_PROMPT = """\
You translate Chinese home-cooking recipes into clear, natural English for a printed family recipe book.

Rules:
- Translate every field given; keep the same number and order of ingredient lines and steps.
- For each ingredient line give the English ingredient name, the English unit (e.g. g, ml, piece, tbsp, tsp, \
clove, slice; null if the line has no unit) and the English note (null if none). Do not write quantities in \
ingredient lines; they are added separately.
- Steps: keep every number, time, temperature and amount exactly; do not add or drop steps or details.
- If an English ingredient name is provided, use it.
- Output English only; do not include Chinese characters.
"""


def translate_dishes(
    llm: LLMBackend,
    dishes: Sequence[Dish],
    ingredients: dict[str, Ingredient],
    cache: dict[str, DishTranslation],
) -> tuple[dict[str, DishTranslation], dict[str, str]]:
    """Translate dishes whose cached translation is missing or stale.

    Returns the updated cache and {dish_id: error} for dishes that could not be translated.
    Raises LLMError if Claude cannot be called.
    """
    cache = dict(cache)
    todo = [d for d in dishes if d.dish_id not in cache or cache[d.dish_id].source_hash != source_hash(d, ingredients)]
    failed: dict[str, str] = {}
    for start in range(0, len(todo), BATCH_SIZE):
        batch = todo[start:start + BATCH_SIZE]
        raw = llm.structured(SYSTEM_PROMPT, _prompt(batch, ingredients), TranslationOutput.model_json_schema())
        items = raw.get("dishes") if isinstance(raw, dict) else None
        by_id = {i.get("dish_id"): i for i in items if isinstance(i, dict)} if isinstance(items, list) else {}
        for dish in batch:
            result = _check(dish, by_id.get(dish.dish_id), ingredients)
            if isinstance(result, str):
                failed[dish.dish_id] = result
            else:
                cache[dish.dish_id] = result
    return cache, failed


def _check(dish: Dish, item: dict | None, ingredients) -> DishTranslation | str:
    if item is None:
        return "no translation returned"
    try:
        out = DishOut.model_validate(item)
    except ValidationError as e:
        err = e.errors()[0]
        return f"invalid translation: {'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
    if len(out.ingredients) != len(dish.ingredients) or len(out.steps) != len(dish.steps):
        return (f"translation has {len(out.ingredients)} ingredient lines and {len(out.steps)} steps, "
                f"the recipe has {len(dish.ingredients)} and {len(dish.steps)}")
    texts = [out.name_en, out.uncertainty_notes or "", *out.steps, *(f"{l.name} {l.unit or ''} {l.note or ''}" for l in out.ingredients)]
    if any(_CJK.search(t) for t in texts):
        return "translation still contains Chinese characters"
    if not out.name_en.strip() or any(not l.name.strip() for l in out.ingredients):
        return "translation has empty names"

    warnings = [
        f"step {n}: number(s) {', '.join(missing)} not found in the translation"
        for n, (zh, en) in enumerate(zip(dish.steps, out.steps), start=1)
        if (missing := sorted(set(_NUMBER.findall(zh)) - set(_NUMBER.findall(en))))
    ]
    return DishTranslation(
        dish_id=dish.dish_id,
        source_hash=source_hash(dish, ingredients),
        name_en=out.name_en.strip(),
        ingredient_names=tuple(l.name.strip() for l in out.ingredients),
        units=tuple(l.unit.strip() if l.unit and l.unit.strip() else None for l in out.ingredients),
        notes=tuple(l.note.strip() if l.note and l.note.strip() else None for l in out.ingredients),
        steps=tuple(s.strip() for s in out.steps),
        uncertainty_notes=(out.uncertainty_notes or "").strip() or None,
        warnings=tuple(warnings),
        translated_at=datetime.now().replace(microsecond=0),
    )


def _prompt(batch: Sequence[Dish], ingredients) -> str:
    payload = [
        {
            "dish_id": d.dish_id,
            "name": d.name_zh,
            "ingredients": [
                {"name": _line_name(l, ingredients),
                 "english_name": ingredients[l.ingredient_id].name_en if l.ingredient_id in ingredients else None,
                 "unit": l.unit, "note": l.note}
                for l in d.ingredients
            ],
            "steps": list(d.steps),
            "uncertainty_notes": d.uncertainty_notes,
        }
        for d in batch
    ]
    return "Translate these recipes:\n" + json.dumps(payload, ensure_ascii=False, indent=1)

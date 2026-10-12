"""Natural-language constraint parsing.

The model proposes an interpretation; this module treats it as untrusted input.
Each result is validated against the constraint registry and the ingredient
catalogue. Anything invalid leaves the constraint `unparsed` with an explanation
instead of being guessed. `conflict` is never taken from the model; conflicts
are detected deterministically in `constraints.py`.
"""

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from .catalogue import constraint_ref_errors
from .constraint_types import CONSTRAINT_TYPES, Execution
from .llm import LLMBackend
from .models import Constraint
from .readonly import ReadOnlyCatalogue
from .vocab import DishType, IngredientCategory, ParseStatus


DISH_TYPE_LABELS = {
    DishType.VEGETARIAN: "素菜",
    DishType.MIXED: "荤素搭配",
    DishType.MEAT: "大荤",
    DishType.SOUP: "汤",
}


class ParsedConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    constraint_id: str
    parse_status: Literal["executable", "approximated", "needs_clarification", "unsupported"]
    strictness: Literal["hard", "soft"]
    execution: Execution | None
    notes: str


class ParserOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[ParsedConstraint]


SYSTEM_PROMPT = """\
You interpret household rules for a family dinner planner. The planner builds four weeks of \
Monday-Friday dinners (20 dinners) from an approved dish catalogue. Rules are usually written in Chinese.

For each rule, return exactly one result with the same constraint_id:
- executable: the rule maps exactly onto one supported type below.
- approximated: a supported type captures the rule only partly; say in notes what is not captured.
- needs_clarification: the rule is ambiguous, incomplete, or combines several rules; ask the needed question in notes.
- unsupported: no supported type can represent the rule; explain why in notes.

Rules:
- Never force a rule into an unrelated type. Calorie and nutrition rules are not supported yet.
- Use only ingredient IDs from the ingredient list. If a rule names an ingredient that is not listed, \
use an ingredient category if that matches the intent exactly; otherwise use needs_clarification.
- execution must be null unless parse_status is executable or approximated.
- strictness: "hard" for must/must-not rules (必须, 不吃, 不要, 一定), "soft" for preferences (尽量, 最好, 别太, 少).
- Write notes in the language of the rule, briefly.

Supported types:
{types}

Dish types: {dish_types}.
Ingredient categories: {categories}.

Ingredient list (id, name, aliases, category):
{ingredients}
"""


def parse_constraints(
    llm: LLMBackend, constraints: Sequence[Constraint], view: ReadOnlyCatalogue
) -> list[Constraint]:
    """Interpret `constraints` and return updated copies, in the same order.

    Raises LLMError if the model cannot be called; then nothing has changed.
    """
    if not constraints:
        return []
    raw = llm.structured(_system_prompt(view), _user_prompt(constraints), ParserOutput.model_json_schema())

    items = raw.get("results") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return [_unparsed(c, "parser output invalid: missing 'results' list") for c in constraints]

    by_id: dict[str, dict] = {}
    for item in items:
        cid = item.get("constraint_id") if isinstance(item, dict) else None
        if isinstance(cid, str):
            by_id[cid] = None if cid in by_id else item  # duplicates are not trusted

    ingredient_ids = {i.ingredient_id for i in view.ingredients()}
    return [_apply(c, by_id.get(c.constraint_id), c.constraint_id in by_id, ingredient_ids) for c in constraints]


def _apply(constraint: Constraint, item: dict | None, seen: bool, ingredient_ids: set[str]) -> Constraint:
    if not seen:
        return _unparsed(constraint, "parser returned no result for this constraint")
    if item is None:
        return _unparsed(constraint, "parser returned several results for this constraint")
    try:
        parsed = ParsedConstraint.model_validate(item)
    except ValidationError as e:
        return _unparsed(constraint, f"parser output invalid: {_first_error(e)}")

    evaluable = parsed.parse_status in ("executable", "approximated")
    if evaluable and parsed.execution is None:
        return _unparsed(constraint, f"parser output invalid: '{parsed.parse_status}' without execution")

    updated = _replace(
        constraint,
        parse_status=parsed.parse_status,
        strictness=parsed.strictness,
        execution=parsed.execution.model_dump() if evaluable else None,
        parse_notes=parsed.notes or None,
    )
    ref_errors = constraint_ref_errors(updated, ingredient_ids)
    if ref_errors:
        return _replace(
            constraint,
            parse_status=ParseStatus.NEEDS_CLARIFICATION,
            strictness=parsed.strictness,
            execution=None,
            parse_notes="parser referenced " + "; ".join(ref_errors),
        )
    return updated


def _unparsed(constraint: Constraint, note: str) -> Constraint:
    return _replace(constraint, parse_status=ParseStatus.UNPARSED, execution=None, parse_notes=note)


def _replace(constraint: Constraint, **changes) -> Constraint:
    """Copy with changes, re-running validation (model_copy would skip it)."""
    return Constraint.model_validate(constraint.model_dump() | changes)


def _first_error(e: ValidationError) -> str:
    err = e.errors()[0]
    return f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"


def _system_prompt(view: ReadOnlyCatalogue) -> str:
    types = "\n".join(f"- {name}: {model.__doc__.strip()}" for name, model in CONSTRAINT_TYPES.items())
    ingredients = "\n".join(
        f"{i.ingredient_id} {i.name_zh}" + (f" ({', '.join(i.aliases)})" if i.aliases else "") + f" [{i.category}]"
        for i in view.ingredients()
    )
    return SYSTEM_PROMPT.format(
        types=types,
        dish_types=", ".join(f"{t.value} ({DISH_TYPE_LABELS[t]})" for t in DishType),
        categories=", ".join(c.value for c in IngredientCategory),
        ingredients=ingredients or "(empty)",
    )


def _user_prompt(constraints: Sequence[Constraint]) -> str:
    return "Rules:\n" + "\n".join(f"{c.constraint_id}: {c.description}" for c in constraints)


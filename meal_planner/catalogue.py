"""In-memory data set and its cross-file validation.

Schema checks of single records live in `models.py`. This module adds the checks
that need more than one record or file: unique IDs, ingredient references,
review-status placement and feedback/menu references. Every problem is collected
and reported together, with the file and record it belongs to.
"""

from collections import Counter
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from .constraint_types import IngredientExclusion
from .models import (
    Constraint,
    ConstraintSource,
    ConstraintsFile,
    Dish,
    DishesFile,
    IngredientsFile,
    MenuVersion,
    PreferencesFile,
    ReviewStatus,
)

INGREDIENTS_FILE = "ingredients.yaml"
DISHES_FILE = "dishes.yaml"
PENDING_DISHES_FILE = "pending_dishes.yaml"
CONSTRAINTS_FILE = "constraints.yaml"
PREFERENCES_FILE = "preferences.yaml"

_ID_KEYS = ("ingredient_id", "dish_id", "constraint_id", "feedback_id", "date")
M = TypeVar("M", bound=BaseModel)


@dataclass(frozen=True)
class DataIssue:
    file: str
    location: str
    message: str

    def __str__(self) -> str:
        where = f"{self.file}: {self.location}" if self.location else self.file
        return f"{where}: {self.message}"


class DataError(Exception):
    def __init__(self, issues: list[DataIssue]):
        self.issues = issues
        super().__init__("\n".join(str(i) for i in issues))


@dataclass(frozen=True)
class Catalogue:
    ingredients: IngredientsFile
    dishes: DishesFile
    pending_dishes: DishesFile
    constraints: ConstraintsFile
    preferences: PreferencesFile

    @property
    def ingredient_ids(self) -> set[str]:
        return {i.ingredient_id for i in self.ingredients.ingredients}

    @property
    def approved_dish_ids(self) -> set[str]:
        return {d.dish_id for d in self.dishes.dishes}


def parse_model(model: type[M], raw: Any, file: str) -> M:
    """Validate raw YAML data against a file schema, raising DataError on failure."""
    if not isinstance(raw, dict):
        raise DataError([DataIssue(file, "", "expected a mapping with 'schema_version' at the top level")])
    try:
        return model.model_validate(raw)
    except ValidationError as e:
        raise DataError(
            [DataIssue(file, _location(raw, err["loc"]), err["msg"]) for err in e.errors()]
        ) from None


def check_catalogue(cat: Catalogue, menu_ids: set[str] | None = None) -> list[DataIssue]:
    issues: list[DataIssue] = []
    ingredient_ids = cat.ingredient_ids
    approved_ids = cat.approved_dish_ids

    issues += _duplicates(INGREDIENTS_FILE, "ingredient_id", [i.ingredient_id for i in cat.ingredients.ingredients])
    issues += _duplicates(DISHES_FILE, "dish_id", [d.dish_id for d in cat.dishes.dishes])
    issues += _duplicates(PENDING_DISHES_FILE, "dish_id", [d.dish_id for d in cat.pending_dishes.dishes])
    issues += _duplicates(CONSTRAINTS_FILE, "constraint_id", [c.constraint_id for c in cat.constraints.constraints])
    issues += _duplicates(PREFERENCES_FILE, "feedback_id", [f.feedback_id for f in cat.preferences.feedback])

    for dish_id in sorted(approved_ids & {d.dish_id for d in cat.pending_dishes.dishes}):
        issues.append(DataIssue(PENDING_DISHES_FILE, f"dishes[{dish_id}]", "dish_id is already used in dishes.yaml (if an approval was interrupted, remove it from pending_dishes.yaml)"))

    for dish in cat.dishes.dishes:
        loc = f"dishes[{dish.dish_id}]"
        if dish.review_status != ReviewStatus.APPROVED:
            issues.append(DataIssue(DISHES_FILE, loc, f"review_status is '{dish.review_status}'; only approved dishes belong here"))
        if any(line.unmatched_name for line in dish.ingredients):
            issues.append(DataIssue(DISHES_FILE, loc, "approved dishes cannot contain unmatched ingredients"))
        issues += _ingredient_refs(DISHES_FILE, dish, ingredient_ids)

    for dish in cat.pending_dishes.dishes:
        if dish.review_status == ReviewStatus.APPROVED:
            issues.append(DataIssue(PENDING_DISHES_FILE, f"dishes[{dish.dish_id}]", "approved dishes belong in dishes.yaml"))
        issues += _ingredient_refs(PENDING_DISHES_FILE, dish, ingredient_ids)

    for c in cat.constraints.constraints:
        if c.source != ConstraintSource.PERSISTENT:
            issues.append(DataIssue(CONSTRAINTS_FILE, f"constraints[{c.constraint_id}]", "only persistent constraints are stored here"))
        issues += [DataIssue(CONSTRAINTS_FILE, f"constraints[{c.constraint_id}]", msg) for msg in constraint_ref_errors(c, ingredient_ids)]

    for f in cat.preferences.feedback:
        loc = f"feedback[{f.feedback_id}]"
        if f.dish_id not in approved_ids:
            issues.append(DataIssue(PREFERENCES_FILE, loc, f"unknown approved dish '{f.dish_id}'"))
        if menu_ids is not None and f.menu_id is not None and f.menu_id not in menu_ids:
            issues.append(DataIssue(PREFERENCES_FILE, loc, f"unknown menu '{f.menu_id}'"))

    return issues


def check_menu(menu: MenuVersion, cat: Catalogue, file: str) -> list[DataIssue]:
    approved_ids = cat.approved_dish_ids
    issues = []
    for dinner in menu.dinners:
        for dish_id in dinner.dish_ids:
            if dish_id not in approved_ids:
                issues.append(DataIssue(file, f"dinners[{dinner.date}]", f"unknown approved dish '{dish_id}'"))
        if len(set(dinner.dish_ids)) != len(dinner.dish_ids):
            issues.append(DataIssue(file, f"dinners[{dinner.date}]", "the same dish appears twice in one dinner"))
    return issues


def constraint_ref_errors(constraint: Constraint, ingredient_ids: set[str]) -> list[str]:
    """Catalogue references in a constraint's parameters that do not exist."""
    if not isinstance(constraint.execution, IngredientExclusion):
        return []
    return [f"unknown ingredient_id '{i}'" for i in constraint.execution.ingredient_ids if i not in ingredient_ids]


def _ingredient_refs(file: str, dish: Dish, ingredient_ids: set[str]) -> list[DataIssue]:
    loc = f"dishes[{dish.dish_id}]"
    refs = [line.ingredient_id for line in dish.ingredients if line.ingredient_id]
    refs += list(dish.style.main_ingredients)
    return [
        DataIssue(file, loc, f"unknown ingredient_id '{ref}'")
        for ref in dict.fromkeys(refs)
        if ref not in ingredient_ids
    ]


def _duplicates(file: str, key: str, ids: list[str]) -> list[DataIssue]:
    return [DataIssue(file, "", f"duplicate {key} '{i}'") for i, n in Counter(ids).items() if n > 1]


def _location(raw: Any, loc: tuple) -> str:
    """Render a pydantic error location, naming records by their ID when possible."""
    text = ""
    node = raw
    for key in loc:
        if isinstance(key, int):
            item = node[key] if isinstance(node, list) and key < len(node) else None
            rid = next((item[k] for k in _ID_KEYS if isinstance(item, dict) and k in item), None)
            text += f"[{rid if rid is not None else key}]"
            node = item
        else:
            text += f".{key}" if text else str(key)
            node = node.get(key) if isinstance(node, dict) else None
    return text

"""Deterministic dish and whole-meal similarity.

Dish similarity is a weighted average of per-feature scores in 0-1. A feature
missing on either dish is left out and the remaining weights are renormalized,
so missing data never counts as evidence of dissimilarity; `coverage` reports
how much of the total weight was actually compared. With no comparable feature
the score is None (not evaluable).

Whole-meal similarity uses the baseline greedy matching (requirements §6.2).
Do not replace it without an explicit design decision.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import Field, model_validator

from .models import Dish, Ingredient, Record
from .vocab import CookingMethod, Flavour, IngredientCategory

FEATURES = ("main_ingredients", "ingredients", "cooking_method", "flavours", "cuisine")


class SimilarityWeights(Record):
    """Tunable assumptions (ADR-015), not validated truths."""

    main_ingredients: float = Field(0.35, ge=0)
    ingredients: float = Field(0.20, ge=0)  # core ingredient combination, seasonings excluded
    cooking_method: float = Field(0.20, ge=0)
    flavours: float = Field(0.15, ge=0)
    cuisine: float = Field(0.10, ge=0)

    @model_validator(mode="after")
    def _check(self):
        if sum(getattr(self, f) for f in FEATURES) <= 0:
            raise ValueError("at least one similarity weight must be positive")
        return self


@dataclass(frozen=True)
class DishSimilarity:
    score: float | None  # None: no feature could be compared
    components: Mapping[str, float]  # per-feature score, compared features only
    missing: tuple[str, ...]  # features missing on at least one dish
    coverage: float  # share of total weight that was compared (0-1)


def dish_similarity(
    a: Dish, b: Dish, ingredients: Mapping[str, Ingredient], weights: SimilarityWeights = SimilarityWeights()
) -> DishSimilarity:
    if a.dish_id == b.dish_id:
        return DishSimilarity(1.0, {f: 1.0 for f in FEATURES}, (), 1.0)

    candidates = {
        "main_ingredients": _jaccard(set(a.style.main_ingredients), set(b.style.main_ingredients)),
        "ingredients": _jaccard(_core_ingredients(a, ingredients), _core_ingredients(b, ingredients)),
        "cooking_method": _same(_known_method(a), _known_method(b)),
        "flavours": _jaccard(_known_flavours(a), _known_flavours(b)),
        "cuisine": _same(_normalized(a.style.cuisine), _normalized(b.style.cuisine)),
    }
    components = {f: s for f, s in candidates.items() if s is not None}
    missing = tuple(f for f in FEATURES if candidates[f] is None)

    total_weight = sum(getattr(weights, f) for f in FEATURES)
    used_weight = sum(getattr(weights, f) for f in components)
    if used_weight == 0:
        return DishSimilarity(None, components, missing, 0.0)
    score = sum(getattr(weights, f) * s for f, s in components.items()) / used_weight
    return DishSimilarity(score, components, missing, used_weight / total_weight)


def _jaccard(x: set, y: set) -> float | None:
    if not x or not y:
        return None
    return len(x & y) / len(x | y)


def _same(x, y) -> float | None:
    if x is None or y is None:
        return None
    return 1.0 if x == y else 0.0


# Used in small amounts in most dishes, so they say little about how alike two dishes are.
_NOT_CORE = {IngredientCategory.SEASONING, IngredientCategory.AROMATIC}


def _core_ingredients(dish: Dish, ingredients: Mapping[str, Ingredient]) -> set[str]:
    ids = {line.ingredient_id for line in dish.ingredients if line.ingredient_id}
    return {i for i in ids if i in ingredients and ingredients[i].category not in _NOT_CORE}


def _known_method(dish: Dish) -> CookingMethod | None:
    method = dish.style.cooking_method
    return None if method in (None, CookingMethod.OTHER) else method


def _known_flavours(dish: Dish) -> set[Flavour]:
    return set(dish.style.flavours) - {Flavour.OTHER}


def _normalized(text: str | None) -> str | None:
    text = (text or "").strip().lower()
    return text or None


# --- Whole-meal similarity -------------------------------------------------------


@dataclass(frozen=True)
class MealSimilarity:
    total: float  # sum of matched pair scores (the baseline definition)
    normalized: float  # total / larger meal size: unmatched extra dishes count as 0
    mean_matched: float | None  # total / number of matched pairs
    pairs: tuple[tuple[str, str, float], ...]  # (dish in meal A, dish in meal B, score), in match order
    unknown_pairs: int  # dish pairs whose similarity could not be evaluated


def greedy_match(scores: Sequence[Sequence[float | None]]) -> list[tuple[int, int, float]]:
    """Repeatedly take the highest-scoring remaining pair and remove both dishes.

    Pairs with an unknown (None) score are never matched. Ties are broken by row
    and then column index, so the result is deterministic.
    """
    candidates = sorted(
        ((s, i, j) for i, row in enumerate(scores) for j, s in enumerate(row) if s is not None),
        key=lambda c: (-c[0], c[1], c[2]),
    )
    used_rows, used_cols, matches = set(), set(), []
    for s, i, j in candidates:
        if i not in used_rows and j not in used_cols:
            matches.append((i, j, s))
            used_rows.add(i)
            used_cols.add(j)
    return matches


def meal_similarity(
    meal_a: Sequence[Dish],
    meal_b: Sequence[Dish],
    ingredients: Mapping[str, Ingredient],
    weights: SimilarityWeights = SimilarityWeights(),
) -> MealSimilarity:
    scores = [[dish_similarity(a, b, ingredients, weights).score for b in meal_b] for a in meal_a]
    matches = greedy_match(scores)
    total = sum(s for _, _, s in matches)
    size = max(len(meal_a), len(meal_b))
    return MealSimilarity(
        total=total,
        normalized=total / size if size else 0.0,
        mean_matched=total / len(matches) if matches else None,
        pairs=tuple((meal_a[i].dish_id, meal_b[j].dish_id, s) for i, j, s in matches),
        unknown_pairs=sum(s is None for row in scores for s in row),
    )

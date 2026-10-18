"""Everything one planning run needs, shared by the solver, repair and validator."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from .catalogue import Catalogue
from .models import Dinner, Dish, Ingredient, plan_dates
from .settings import PlannerSettings, Settings
from .similarity import DishSimilarity, MealSimilarity, SimilarityWeights, dish_similarity, meal_similarity
from .vocab import FeedbackScope


@dataclass
class PlanContext:
    start_date: date
    dishes: dict[str, Dish]  # approved dishes only: pending and rejected are never selectable
    ingredients: dict[str, Ingredient]
    weights: SimilarityWeights
    settings: PlannerSettings
    history: tuple[Dinner, ...] = ()  # earlier menus, for repetition across plans
    disliked: frozenset[str] = frozenset()
    # Dishes the planner may newly choose; None means every approved dish. Validation always
    # knows all approved dishes, so a menu that contains other approved dishes is still valid.
    selectable: frozenset[str] | None = None
    _similarity: dict[tuple[str, str], DishSimilarity] = field(default_factory=dict, repr=False)

    @property
    def dates(self) -> list[date]:
        return plan_dates(self.start_date)

    def is_selectable(self, dish_id: str) -> bool:
        return self.selectable is None or dish_id in self.selectable

    def similarity(self, a: str, b: str, feature: str = "overall") -> float | None:
        """Overall weighted score, or one feature's score; None when it cannot be compared."""
        key = (a, b) if a <= b else (b, a)
        if key not in self._similarity:
            self._similarity[key] = dish_similarity(self.dishes[key[0]], self.dishes[key[1]], self.ingredients, self.weights)
        result = self._similarity[key]
        return result.score if feature == "overall" else result.components.get(feature)

    def meal_similarity(self, a: Sequence[str], b: Sequence[str]) -> MealSimilarity:
        return meal_similarity([self.dishes[i] for i in a], [self.dishes[i] for i in b], self.ingredients, self.weights)


def make_context(
    catalogue: Catalogue, settings: Settings, start_date: date, history: Sequence[Dinner] = (), menu_id: str | None = None,
    frequent_only: bool = False,
) -> PlanContext:
    """`menu_id`: the menu being adjusted, whose `this_menu` dislike feedback also applies.
    `frequent_only`: the planner may only choose dishes marked frequent (常用菜).
    """
    disliked = {
        f.dish_id
        for f in catalogue.preferences.feedback
        if f.kind == "dislike"
        and (f.scope in (FeedbackScope.FUTURE_MENUS, FeedbackScope.PERSISTENT) or (menu_id and f.menu_id == menu_id))
    }
    return PlanContext(
        start_date=start_date,
        dishes={d.dish_id: d for d in catalogue.dishes.dishes},
        ingredients={i.ingredient_id: i for i in catalogue.ingredients.ingredients},
        weights=settings.similarity_weights,
        settings=settings.planner,
        history=tuple(history),
        disliked=frozenset(disliked),
        selectable=frozenset(d.dish_id for d in catalogue.dishes.dishes if d.frequent) if frequent_only else None,
    )

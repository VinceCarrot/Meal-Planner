"""Everything one planning run needs, shared by the solver, repair and validator."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from .catalogue import Catalogue
from .models import Dinner, Dish, Ingredient, plan_dates
from .settings import PlannerSettings, Settings
from .similarity import MealSimilarity, SimilarityWeights, dish_similarity, meal_similarity
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
    _similarity: dict[tuple[str, str], float | None] = field(default_factory=dict, repr=False)

    @property
    def dates(self) -> list[date]:
        return plan_dates(self.start_date)

    def similarity(self, a: str, b: str) -> float | None:
        key = (a, b) if a <= b else (b, a)
        if key not in self._similarity:
            result = dish_similarity(self.dishes[key[0]], self.dishes[key[1]], self.ingredients, self.weights)
            self._similarity[key] = result.score
        return self._similarity[key]

    def meal_similarity(self, a: Sequence[str], b: Sequence[str]) -> MealSimilarity:
        return meal_similarity([self.dishes[i] for i in a], [self.dishes[i] for i in b], self.ingredients, self.weights)


def make_context(
    catalogue: Catalogue, settings: Settings, start_date: date, history: Sequence[Dinner] = (), menu_id: str | None = None
) -> PlanContext:
    """`menu_id`: the menu being adjusted, whose `this_menu` dislike feedback also applies."""
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
    )

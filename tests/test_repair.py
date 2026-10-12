from datetime import date

import pytest

from meal_planner.demo import synthetic_catalogue
from meal_planner.checks import exclusion_hits
from meal_planner.constraints import build_effective_set
from meal_planner.models import Constraint, Dinner
from meal_planner.plan_context import make_context
from meal_planner.repair import repair_meal_similarity
from meal_planner.settings import Settings
from meal_planner.validator import validate_menu
from meal_planner.vocab import TaskScope

START = date(2026, 10, 19)
GEN = TaskScope.MENU_GENERATION


@pytest.fixture
def ctx():
    s = Settings()
    return make_context(synthetic_catalogue(100), Settings(planner=s.planner.model_copy(update={"repair_max_steps": 15})), START)


def _effective(*specs):
    return build_effective_set([
        Constraint(constraint_id=f"C{n:03d}", description="r", scope=[GEN], strictness=s,
                   source="persistent", execution=e, parse_status="executable")
        for n, (s, e) in enumerate(specs, start=1)
    ], [], GEN)


SPECS = [
    ("hard", {"type": "dish_count", "min": 3, "max": 3}),
    ("hard", {"type": "dish_type_count", "dish_type": "soup", "min": 1, "max": 1}),
    ("hard", {"type": "ingredient_exclusion", "categories": ["seafood"]}),
    ("soft", {"type": "meal_similarity", "max_similarity": 0.5, "window_weeks": 1}),
]


@pytest.fixture
def same_dinner_every_day(ctx):
    rule = _effective(*SPECS[2:3]).constraints[0].execution
    allowed = [k for k in sorted(ctx.dishes) if not exclusion_hits(ctx.dishes[k], rule, ctx.ingredients)]
    soup = next(k for k in allowed if ctx.dishes[k].dish_type == "soup")
    veg = [k for k in allowed if ctx.dishes[k].dish_type == "vegetarian"][:2]
    return [Dinner(date=d, dish_ids=(veg[0], veg[1], soup)) for d in ctx.dates]


def test_repair_reduces_meal_similarity_and_keeps_hard_constraints(ctx, same_dinner_every_day):
    effective = _effective(*SPECS)
    dinners, stats = repair_meal_similarity(ctx, effective, same_dinner_every_day)

    assert stats.steps > 0
    assert stats.penalty_after < stats.penalty_before
    report = validate_menu(dinners, ctx, effective)
    assert report.hard_ok and report.penalty_total == stats.penalty_after


def test_repair_leaves_locked_dishes_alone(ctx, same_dinner_every_day):
    locked_day = ctx.dates[0]
    dinners, _ = repair_meal_similarity(
        ctx, _effective(*SPECS), same_dinner_every_day, editable=lambda d, k: d != locked_day
    )
    assert dinners[0] == same_dinner_every_day[0]


def test_repair_does_nothing_without_meal_similarity_rules(ctx, same_dinner_every_day):
    dinners, stats = repair_meal_similarity(ctx, _effective(*SPECS[:3]), same_dinner_every_day)
    assert dinners == same_dinner_every_day and stats.steps == 0

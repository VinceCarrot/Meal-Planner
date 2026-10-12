from datetime import date

import pytest

from fakes import FakeLLM
from meal_planner.demo import synthetic_catalogue, write_catalogue
from meal_planner.candidates import (
    CandidateRequest,
    generate_candidates,
    hard_exclusions,
    requests_for_gaps,
)
from meal_planner.constraint_types import IngredientExclusion
from meal_planner.constraints import build_effective_set
from meal_planner.llm import LLMError
from meal_planner.models import Constraint
from meal_planner.plan_context import make_context
from meal_planner.planner import CatalogueGap, plan_menu
from meal_planner.review import ReviewAction, ReviewDecision, apply_review
from meal_planner.settings import CandidateSettings, Settings
from meal_planner.store import DataStore
from meal_planner.vocab import TaskScope

SOUP_REQUEST = CandidateRequest("soup", 3, "need more soups")


def draft(name, dish_type="soup", lines=None, **extra):
    return {
        "name_zh": name,
        "dish_type": dish_type,
        "servings": 4,
        "ingredients": lines or [{"ingredient_id": "ing_tofu", "quantity": 200, "unit": "g"},
                                 {"ingredient_id": "ing_soy_sauce", "note": "适量"}],
        "steps": ["煮开", "调味"],
        "style": {"main_ingredients": ["ing_tofu"], "cooking_method": "boil", "flavours": ["light"]},
        **extra,
    }


def test_requests_scale_with_the_gap():
    small = CatalogueGap("C002", "soup", 15, 1, 20)  # 5 dishes short
    large = CatalogueGap("C003", "meat", 2, 1, 20)  # 18 dishes short
    settings = CandidateSettings()
    assert [r.count for r in requests_for_gaps([small, large], settings)] == [8, 27]
    assert requests_for_gaps([CatalogueGap("C001", None, 79, 1, 80)], settings)[0].count == 5


def test_valid_drafts_become_pending_candidates(store, data_dir):
    before_dishes = (data_dir / "dishes.yaml").read_bytes()
    before_ingredients = (data_dir / "ingredients.yaml").read_bytes()
    llm = FakeLLM({"dishes": [draft("豆腐清汤"), draft("番茄豆腐羹", lines=[
        {"ingredient_id": "ing_tomato", "quantity": 1, "unit": "个"},
        {"unmatched_name": "淀粉", "quantity": 10, "unit": "g"},
    ])]})

    cat, result = generate_candidates(store, store.load(), llm, SOUP_REQUEST)

    assert [d.dish_id for d in result.added] == ["dish_0103", "dish_0104"]
    assert all(d.source == "ai_generated" and d.review_status == "pending" for d in result.added)
    assert result.added[1].ingredients[1].unmatched_name == "淀粉"  # flagged, not created
    assert {d.dish_id for d in store.load().pending_dishes.dishes} >= {"dish_0103", "dish_0104"}
    assert (data_dir / "dishes.yaml").read_bytes() == before_dishes
    assert (data_dir / "ingredients.yaml").read_bytes() == before_ingredients


def test_agent_gets_read_only_tools_and_the_request(store):
    llm = FakeLLM({"dishes": []})
    no_seafood = IngredientExclusion(type="ingredient_exclusion", categories=("seafood",), ingredient_ids=("ing_egg",))
    generate_candidates(store, store.load(), llm, SOUP_REQUEST, [no_seafood])
    call = llm.calls[0]
    assert {t.name for t in call["tools"]} == {"list_ingredients", "search_ingredients", "list_dishes"}
    assert "Create 3 new soup dishes" in call["prompt"]
    assert "Must not contain: categories seafood; 鸡蛋." in call["prompt"]


@pytest.mark.parametrize(
    "item, reason",
    [
        (draft("怪汤", servings="many"), "invalid: servings"),
        (draft("无料汤", lines=[{"quantity": 1, "unit": "g"}]), "invalid"),
        (draft("称重汤", lines=[{"ingredient_id": "ing_tofu", "quantity": 100}]), "unit is required"),
        (draft("榴莲汤", lines=[{"ingredient_id": "ing_durian", "quantity": 100, "unit": "g"}]), "unknown ingredient_id ing_durian"),
        (draft("清炒豆腐", dish_type="vegetarian"), "requested soup"),
        (draft("虾仁汤", lines=[{"ingredient_id": "ing_shrimp", "quantity": 100, "unit": "g"}]), "excluded ingredient ing_shrimp"),
        (draft("紫菜蛋花汤"), "already exists"),
        ({**draft("多字段汤"), "rating": 5}, "invalid"),
    ],
)
def test_invalid_drafts_are_rejected_with_a_reason(store, data_dir, item, reason):
    before = (data_dir / "pending_dishes.yaml").read_bytes()
    no_seafood = IngredientExclusion(type="ingredient_exclusion", categories=("seafood",))

    _, result = generate_candidates(store, store.load(), FakeLLM({"dishes": [item]}), SOUP_REQUEST, [no_seafood])

    assert result.added == ()
    [(_, why)] = result.rejected
    assert reason in why
    assert (data_dir / "pending_dishes.yaml").read_bytes() == before


def test_duplicate_names_within_one_batch(store):
    _, result = generate_candidates(store, store.load(), FakeLLM({"dishes": [draft("豆腐汤"), draft("豆腐汤")]}), SOUP_REQUEST)
    assert len(result.added) == 1 and result.rejected[0][1] == "a dish with this name already exists"


@pytest.mark.parametrize("response", [None, {}, {"dishes": "x"}])
def test_malformed_output(store, response):
    _, result = generate_candidates(store, store.load(), FakeLLM(response), SOUP_REQUEST)
    assert result.added == () and "no 'dishes' list" in result.rejected[0][1]


def test_llm_failure_writes_nothing(store, data_dir):
    before = (data_dir / "pending_dishes.yaml").read_bytes()
    with pytest.raises(LLMError):
        generate_candidates(store, store.load(), FakeLLM(error=LLMError("timeout")), SOUP_REQUEST)
    assert (data_dir / "pending_dishes.yaml").read_bytes() == before


def test_gap_generation_review_and_replanning(tmp_path):
    """Catalogue shortage -> targeted candidates -> user approval -> feasible plan."""
    data_dir = tmp_path / "data"
    write_catalogue(synthetic_catalogue(100), data_dir)
    store = DataStore(data_dir)
    rules = [
        ("hard", {"type": "dish_count", "min": 4, "max": 4}),
        ("hard", {"type": "dish_type_count", "dish_type": "soup", "min": 1, "max": 1}),
        ("hard", {"type": "exact_repeat_window", "weeks": 4}),
        ("hard", {"type": "ingredient_exclusion", "categories": ["seafood"]}),
    ]
    effective = build_effective_set([
        Constraint(constraint_id=f"C{n:03d}", description="r", scope=["menu_generation"], strictness=s,
                   source="persistent", execution=e, parse_status="executable")
        for n, (s, e) in enumerate(rules, start=1)
    ], [], TaskScope.MENU_GENERATION)
    settings = Settings(planner=Settings().planner.model_copy(update={"time_limit_s": 10}))
    start = date(2026, 10, 19)

    cat = store.load()
    first = plan_menu(make_context(cat, settings, start), effective)
    assert first.status == "infeasible"
    [request] = requests_for_gaps(first.gaps, settings.candidates)
    assert request.dish_type == "soup"

    names = [f"新汤{n}" for n in range(request.count)]
    lines = [{"ingredient_id": "ing_cabbage", "quantity": 200, "unit": "g"}, {"ingredient_id": "ing_tofu", "quantity": 100, "unit": "g"}]
    llm = FakeLLM({"dishes": [draft(name, lines=lines) for name in names]})
    cat, generated = generate_candidates(store, cat, llm, request, hard_exclusions(effective))
    assert len(generated.added) == request.count

    cat = apply_review(store, cat, [ReviewDecision(d.dish_id, ReviewAction.APPROVE) for d in generated.added])
    second = plan_menu(make_context(store.load(), settings, start), effective)
    assert second.status == "feasible"

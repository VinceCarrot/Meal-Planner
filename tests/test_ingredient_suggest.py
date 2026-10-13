import pytest

from fakes import FakeLLM
from meal_planner.ingredient_suggest import suggest_ingredient
from meal_planner.llm import LLMError
from meal_planner.models import Ingredient

EXISTING = [
    Ingredient(ingredient_id="ing_tofu", name_zh="豆腐", name_en="tofu", category="soy"),
    Ingredient(ingredient_id="ing_broccoli", name_zh="西兰花", name_en="broccoli", category="vegetable"),
]
GOOD = {
    "name_en": "Broccoli", "aliases": ["青花菜", "西兰花", " "], "category": "vegetable",
    "kcal_per_100g": 34, "grams_per_unit": [{"unit": "颗", "grams": 400}], "notes": None,
}


def test_proposal_is_normalized_and_unique():
    proposal, warnings = suggest_ingredient(FakeLLM(GOOD), " 西兰花 ", EXISTING)

    assert proposal == {
        "ingredient_id": "ing_broccoli_2", "name_zh": "西兰花", "name_en": "Broccoli", "aliases": ["青花菜"],
        "category": "vegetable", "kcal_per_100g": 34, "grams_per_unit": {"颗": 400}, "notes": None,
    }
    assert warnings == ["食材库中可能已有同一种食材：西兰花（ing_broccoli）"]
    Ingredient.model_validate(proposal)


def test_editing_keeps_id_and_is_not_its_own_duplicate():
    proposal, warnings = suggest_ingredient(FakeLLM(GOOD), "西兰花", EXISTING, editing_id="ing_broccoli")
    assert proposal["ingredient_id"] == "ing_broccoli" and warnings == []


def test_unreasonable_values_are_dropped_with_warnings():
    bad = GOOD | {"name_en": "okra", "aliases": [], "kcal_per_100g": 5000, "grams_per_unit": [{"unit": "个", "grams": -3}, {"unit": "勺", "grams": 15}]}
    proposal, warnings = suggest_ingredient(FakeLLM(bad), "秋葵", EXISTING)
    assert proposal["kcal_per_100g"] is None and proposal["grams_per_unit"] == {"勺": 15}
    assert len(warnings) == 2


def test_non_ascii_english_name_gets_a_valid_id():
    proposal, _ = suggest_ingredient(FakeLLM(GOOD | {"name_en": "芋头"}), "芋头", EXISTING)
    assert proposal["ingredient_id"] == "ing_new" and proposal["name_en"] == "芋头"


@pytest.mark.parametrize("raw", [
    None, "text", GOOD | {"category": "fruit"}, GOOD | {"extra": 1}, {k: v for k, v in GOOD.items() if k != "name_en"},
])
def test_malformed_output_raises_llm_error(raw):
    with pytest.raises(LLMError):
        suggest_ingredient(FakeLLM(raw), "秋葵", EXISTING)


def test_empty_name_is_refused_without_calling_claude():
    llm = FakeLLM(GOOD)
    with pytest.raises(ValueError):
        suggest_ingredient(llm, "  ", EXISTING)
    assert llm.calls == []

import pytest

from fakes import FakeLLM
from meal_planner.dish_suggest import suggest_dish
from meal_planner.llm import LLMError
from meal_planner.models import Ingredient

INGREDIENTS = [
    Ingredient(ingredient_id="ing_tomato", name_zh="番茄", name_en="tomato", aliases=("西红柿",), category="vegetable"),
    Ingredient(ingredient_id="ing_egg", name_zh="鸡蛋", name_en="egg", category="egg"),
]
GOOD = {
    "name_en": "Stir-fried tomato and egg", "dish_type": "vegetarian", "servings": 3,
    "ingredients": [
        {"name": "西红柿", "ingredient_id": None, "quantity": 300, "unit": "g", "note": None, "main": True},
        {"name": "鸡蛋", "ingredient_id": "ing_egg", "quantity": 3, "unit": "个", "note": None, "main": True},
        {"name": "盐", "ingredient_id": None, "quantity": None, "unit": None, "note": "适量", "main": False},
        {"name": "糖", "ingredient_id": "ing_sugar", "quantity": 5, "unit": None, "note": None, "main": False},
    ],
    "steps": ["1. 鸡蛋打散", "第二步：番茄切块", "  ", "（3）先炒蛋再炒番茄，加 2.5 克盐"],
    "cooking_method": "stir_fry", "flavours": ["sweet_sour", "sweet_sour"], "cuisine": "家常",
    "uncertainty_notes": " ",
}


def test_generated_proposal_is_normalized():
    llm = FakeLLM(GOOD)
    proposal, source, sources, warnings = suggest_dish(llm, " 番茄炒蛋 ", "", INGREDIENTS, set())

    assert source == "generated" and sources == [] and llm.calls[0]["web_search"] is False
    assert "Method text" not in llm.calls[0]["prompt"] and "source_url" not in proposal
    assert "from your knowledge" in llm.calls[0]["system"] and "ing_tomato 番茄 (西红柿)" in llm.calls[0]["system"]
    assert proposal["name_zh"] == "番茄炒蛋"
    assert proposal["steps"] == ["鸡蛋打散", "番茄切块", "先炒蛋再炒番茄，加 2.5 克盐"]
    lines = proposal["ingredients"]
    assert lines[0] == {"ingredient_id": "ing_tomato", "unmatched_name": None, "quantity": 300, "unit": "g", "note": None}
    assert lines[2] == {"ingredient_id": None, "unmatched_name": "盐", "quantity": None, "unit": None, "note": "适量"}
    # unknown ID is not trusted; a quantity without unit is dropped
    assert lines[3] == {"ingredient_id": None, "unmatched_name": "糖", "quantity": None, "unit": None, "note": None}
    assert proposal["style"] == {"main_ingredients": ["ing_tomato", "ing_egg"], "cooking_method": "stir_fry",
                                 "flavours": ["sweet_sour"], "cuisine": "家常"}
    assert proposal["uncertainty_notes"] is None and proposal["calories_kcal"] is None
    assert len(warnings) == 2 and "盐、糖" in warnings[1]


def test_user_method_is_sent_for_parsing():
    llm = FakeLLM(GOOD)
    _, source, _, warnings = suggest_dish(llm, "番茄炒蛋", "鸡蛋打散炒熟盛出，番茄炒软后倒回鸡蛋", INGREDIENTS, {"番茄炒蛋"},
                                          web_search=True)

    assert source == "parsed" and llm.calls[0]["web_search"] is False  # search only replaces a missing method
    assert "鸡蛋打散炒熟盛出" in llm.calls[0]["prompt"] and "do not add steps" in llm.calls[0]["system"]
    assert not any("未经核实" in w for w in warnings)
    assert any("同名菜品" in w for w in warnings)


def test_web_search_returns_checked_reference_links():
    raw = GOOD | {"sources": ["https://a.example/r/1", " https://a.example/r/1 ", "javascript:alert(1)", "ftp://x",
                              "https://b.example/r/2"]}
    llm = FakeLLM(raw)
    proposal, source, sources, warnings = suggest_dish(llm, "番茄炒蛋", " ", INGREDIENTS, set(), web_search=True)

    assert source == "searched" and llm.calls[0]["web_search"] is True and "WebSearch" in llm.calls[0]["system"]
    assert sources == ["https://a.example/r/1", "https://b.example/r/2"]
    assert proposal["source_url"] == "https://a.example/r/1"
    assert "参考网上菜谱" in warnings[0]


def test_web_search_without_usable_sources_is_reported():
    proposal, _, sources, warnings = suggest_dish(FakeLLM(GOOD), "番茄炒蛋", "", INGREDIENTS, set(), web_search=True)
    assert sources == [] and proposal["source_url"] is None and "没有找到可用的菜谱" in warnings[0]


@pytest.mark.parametrize("raw", [
    None, "text", GOOD | {"dish_type": "dessert"}, GOOD | {"extra": 1}, GOOD | {"steps": [" ", "2."]},
    GOOD | {"ingredients": []}, {k: v for k, v in GOOD.items() if k != "steps"},
])
def test_malformed_output_raises_llm_error(raw):
    with pytest.raises(LLMError):
        suggest_dish(FakeLLM(raw), "番茄炒蛋", "", INGREDIENTS, set())


def test_bad_input_is_refused_without_calling_claude():
    llm = FakeLLM(GOOD)
    with pytest.raises(ValueError):
        suggest_dish(llm, "  ", "", INGREDIENTS, set())
    with pytest.raises(ValueError):
        suggest_dish(llm, "番茄炒蛋", "x" * 9000, INGREDIENTS, set())
    assert llm.calls == []

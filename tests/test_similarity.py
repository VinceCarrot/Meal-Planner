import pytest
from pydantic import ValidationError

from meal_planner.models import Dish, Ingredient
from meal_planner.similarity import (
    SimilarityWeights,
    dish_similarity,
    greedy_match,
    meal_similarity,
)


@pytest.fixture
def cat(store):
    return store.load()


@pytest.fixture
def dishes(cat):
    return {d.dish_id: d for d in cat.dishes.dishes}


@pytest.fixture
def ingredients(cat):
    return {i.ingredient_id: i for i in cat.ingredients.ingredients}


def _copy(dish, dish_id="dish_0999", **changes):
    return Dish.model_validate(dish.model_dump() | {"dish_id": dish_id} | changes)


# --- Dish similarity ---------------------------------------------------------------


def test_same_dish_is_identical(dishes, ingredients):
    result = dish_similarity(dishes["dish_0001"], dishes["dish_0001"], ingredients)
    assert (result.score, result.coverage) == (1.0, 1.0)


def test_same_recipe_under_another_id_scores_one(dishes, ingredients):
    result = dish_similarity(dishes["dish_0001"], _copy(dishes["dish_0001"]), ingredients)
    assert result.score == pytest.approx(1.0) and result.missing == ()


def test_nothing_in_common_scores_zero(dishes, ingredients):
    # 番茄炒蛋 vs 红烧肉: different ingredients, method and flavours; 红烧肉 has no cuisine
    result = dish_similarity(dishes["dish_0001"], dishes["dish_0002"], ingredients)
    assert result.score == 0.0
    assert result.missing == ("cuisine",)
    assert result.coverage == pytest.approx(0.9)


def test_shared_cooking_method_only(dishes, ingredients):
    # 番茄炒蛋 vs 清炒青菜: both stir-fried, nothing else shared, cuisine missing on 清炒青菜
    result = dish_similarity(dishes["dish_0001"], dishes["dish_0003"], ingredients)
    assert result.components == {"main_ingredients": 0, "ingredients": 0, "cooking_method": 1, "flavours": 0}
    assert result.score == pytest.approx(0.20 / 0.90)


def test_partial_ingredient_overlap(dishes, ingredients):
    # 番茄炒蛋 {tomato, egg} vs 紫菜蛋花汤 {seaweed, egg}: Jaccard 1/3 on ingredients
    result = dish_similarity(dishes["dish_0001"], dishes["dish_0005"], ingredients)
    assert result.components["main_ingredients"] == pytest.approx(1 / 3)
    assert result.components["ingredients"] == pytest.approx(1 / 3)


def test_seasonings_do_not_count_as_shared_ingredients(dishes, ingredients):
    a = _copy(dishes["dish_0003"], ingredients=[{"ingredient_id": "ing_bok_choy"}, {"ingredient_id": "ing_soy_sauce"}])
    b = _copy(dishes["dish_0004"], "dish_0998", ingredients=[{"ingredient_id": "ing_potato"}, {"ingredient_id": "ing_soy_sauce"}])
    assert dish_similarity(a, b, ingredients).components["ingredients"] == 0.0


def test_aromatics_do_not_count_as_shared_ingredients(dishes, ingredients):
    garlic = Ingredient(ingredient_id="ing_garlic", name_zh="大蒜", category="aromatic")
    ingredients = ingredients | {"ing_garlic": garlic}
    a = _copy(dishes["dish_0003"], ingredients=[{"ingredient_id": "ing_bok_choy"}, {"ingredient_id": "ing_garlic"}])
    b = _copy(dishes["dish_0004"], "dish_0998", ingredients=[{"ingredient_id": "ing_potato"}, {"ingredient_id": "ing_garlic"}])
    assert dish_similarity(a, b, ingredients).components["ingredients"] == 0.0


def test_missing_features_are_left_out_not_counted_as_different(dishes, ingredients):
    bare = _copy(dishes["dish_0001"], style={})
    result = dish_similarity(bare, _copy(dishes["dish_0001"], "dish_0998", style={}), ingredients)
    assert result.components == {"ingredients": 1.0}
    assert result.score == 1.0
    assert result.coverage == pytest.approx(0.20)
    assert set(result.missing) == {"main_ingredients", "cooking_method", "flavours", "cuisine"}


def test_no_comparable_feature_is_not_evaluable(dishes, ingredients):
    only_seasoning = [{"ingredient_id": "ing_soy_sauce"}]
    a = _copy(dishes["dish_0001"], style={}, ingredients=only_seasoning)
    b = _copy(dishes["dish_0002"], "dish_0998", style={"cooking_method": "other"}, ingredients=only_seasoning)
    result = dish_similarity(a, b, ingredients)
    assert result.score is None and result.coverage == 0.0


def test_similarity_is_symmetric_and_repeatable(dishes, ingredients):
    for a in dishes.values():
        for b in dishes.values():
            assert dish_similarity(a, b, ingredients) == dish_similarity(b, a, ingredients)


def test_weights_are_configurable(dishes, ingredients):
    method_only = SimilarityWeights(main_ingredients=0, ingredients=0, cooking_method=1, flavours=0, cuisine=0)
    assert dish_similarity(dishes["dish_0001"], dishes["dish_0003"], ingredients, method_only).score == 1.0


def test_weights_must_not_all_be_zero():
    with pytest.raises(ValidationError):
        SimilarityWeights(main_ingredients=0, ingredients=0, cooking_method=0, flavours=0, cuisine=0)
    with pytest.raises(ValidationError):
        SimilarityWeights(cuisine=-0.1)


# --- Whole-meal similarity ---------------------------------------------------------


def test_greedy_matching_is_the_baseline_not_the_optimum():
    # Greedy takes 0.9 first and is left with 0.0 (total 0.9); the optimal matching would be 0.8 + 0.8.
    assert greedy_match([[0.9, 0.8], [0.8, 0.0]]) == [(0, 0, 0.9), (1, 1, 0.0)]


def test_greedy_ties_are_broken_by_position():
    assert greedy_match([[0.5, 0.5], [0.5, 0.5]]) == [(0, 0, 0.5), (1, 1, 0.5)]


def test_unknown_scores_are_never_matched():
    assert greedy_match([[None, 0.2], [None, None]]) == [(0, 1, 0.2)]


def test_identical_meals(dishes, ingredients):
    meal = [dishes["dish_0001"], dishes["dish_0002"], dishes["dish_0005"]]
    result = meal_similarity(meal, list(reversed(meal)), ingredients)
    assert result.total == pytest.approx(3.0)
    assert result.normalized == pytest.approx(1.0)
    assert {(a, b) for a, b, _ in result.pairs} == {("dish_0001", "dish_0001"), ("dish_0002", "dish_0002"), ("dish_0005", "dish_0005")}


def test_unequal_meal_sizes_are_normalized(dishes, ingredients):
    small = [dishes["dish_0001"], dishes["dish_0005"]]
    large = small + [dishes["dish_0002"]]
    result = meal_similarity(small, large, ingredients)
    assert result.total == pytest.approx(2.0)
    assert result.mean_matched == pytest.approx(1.0)
    assert result.normalized == pytest.approx(2 / 3)
    assert len(result.pairs) == 2


def test_unknown_dish_pairs_are_counted(dishes, ingredients):
    bare = _copy(dishes["dish_0001"], style={}, ingredients=[{"ingredient_id": "ing_soy_sauce"}])
    result = meal_similarity([bare], [dishes["dish_0002"]], ingredients)
    assert result.unknown_pairs == 1 and result.pairs == () and result.mean_matched is None

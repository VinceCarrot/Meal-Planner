import pytest

from meal_planner.calories import estimate_dish_calories
from meal_planner.models import Dish, Ingredient


@pytest.fixture
def cat(store):
    return store.load()


@pytest.fixture
def ingredients(cat):
    return {i.ingredient_id: i for i in cat.ingredients.ingredients}


def _dish(cat, dish_id):
    return next(d for d in cat.dishes.dishes + cat.pending_dishes.dishes if d.dish_id == dish_id)


def _with_lines(*lines, servings=None):
    return Dish(dish_id="dish_9999", name_zh="测试", dish_type="mixed", ingredients=lines,
                servings=servings, source="manual", review_status="approved")


def test_complete_estimate_uses_unit_weights(cat, ingredients):
    # 2 个番茄 x 150 g x 18 kcal/100 g + 3 个鸡蛋 x 50 g x 144 kcal/100 g
    est = estimate_dish_calories(_dish(cat, "dish_0001"), ingredients)
    assert est.complete and est.coverage == 1.0
    assert est.total_kcal == pytest.approx(54 + 216)
    assert est.per_serving_kcal == pytest.approx(270 / 4)


def test_line_without_quantity_makes_estimate_partial(cat, ingredients):
    est = estimate_dish_calories(_dish(cat, "dish_0002"), ingredients)
    assert not est.complete
    assert est.total_kcal is None and est.per_serving_kcal is None
    assert est.known_kcal == pytest.approx(500 * 3.95)
    assert est.coverage == 0.5
    assert [(m.ingredient, m.reason) for m in est.missing] == [("ing_soy_sauce", "no quantity (适量)")]


def test_missing_nutrition_is_reported(cat, ingredients):
    est = estimate_dish_calories(_dish(cat, "dish_0005"), ingredients)
    assert [(m.ingredient, m.reason) for m in est.missing] == [("ing_seaweed", "no kcal_per_100g")]
    assert est.known_kcal == pytest.approx(72)  # the egg is still counted


def test_unmatched_ingredient_in_candidate_is_reported(cat, ingredients):
    est = estimate_dish_calories(_dish(cat, "dish_0102"), ingredients)
    assert ("香菇", "ingredient not in catalogue") in [(m.ingredient, m.reason) for m in est.missing]


@pytest.mark.parametrize(
    "quantity, unit, kcal",
    [(0.5, "kg", 395 * 5), (1, "斤", 395 * 5), (2, "两", 395), (100, "克", 395)],
)
def test_mass_units(ingredients, quantity, unit, kcal):
    dish = _with_lines({"ingredient_id": "ing_pork_belly", "quantity": quantity, "unit": unit})
    assert estimate_dish_calories(dish, ingredients).total_kcal == pytest.approx(kcal)


def test_unit_without_gram_weight_is_not_guessed(ingredients):
    dish = _with_lines({"ingredient_id": "ing_soy_sauce", "quantity": 2, "unit": "勺"})
    est = estimate_dish_calories(dish, ingredients)
    assert est.total_kcal is None
    assert est.missing[0].reason == "no gram weight for unit '勺'"


def test_volume_unit_uses_ingredient_density_when_given():
    soy = Ingredient(ingredient_id="ing_soy_sauce", name_zh="生抽", category="seasoning",
                     kcal_per_100g=63, grams_per_unit={"ml": 1.2})
    dish = _with_lines({"ingredient_id": "ing_soy_sauce", "quantity": 10, "unit": "ml"})
    assert estimate_dish_calories(dish, {"ing_soy_sauce": soy}).total_kcal == pytest.approx(12 * 0.63)


def test_estimate_is_repeatable(cat, ingredients):
    dish = _dish(cat, "dish_0004")
    assert estimate_dish_calories(dish, ingredients) == estimate_dish_calories(dish, ingredients)

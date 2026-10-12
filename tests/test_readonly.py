"""The AI-facing data view cannot change ingredient master data or expose pending dishes."""

import pytest
from pydantic import ValidationError

from meal_planner.readonly import ReadOnlyCatalogue


@pytest.fixture
def view(store):
    return ReadOnlyCatalogue(store.load())


def test_view_exposes_only_read_operations(view):
    public = {name for name in dir(view) if not name.startswith("_")}
    assert public == {"ingredients", "ingredient", "approved_dishes", "approved_dish"}


def test_view_cannot_gain_new_attributes(view):
    with pytest.raises(AttributeError):
        view.store = object()


def test_returned_ingredients_cannot_be_modified(view):
    ing = view.ingredient("ing_tomato")
    with pytest.raises(ValidationError):
        ing.kcal_per_100g = 0
    with pytest.raises(AttributeError):
        ing.aliases.append("洋柿子")


def test_mutating_a_returned_copy_does_not_affect_the_view(view):
    view.ingredient("ing_tomato").grams_per_unit["个"] = 1
    view.ingredients()[0].grams_per_unit.clear()
    assert view.ingredient("ing_tomato").grams_per_unit == {"个": 150}


def test_pending_dishes_are_not_visible_as_approved(view):
    approved = {d.dish_id for d in view.approved_dishes()}
    assert "dish_0101" not in approved and "dish_0102" not in approved
    assert view.approved_dish("dish_0101") is None
    assert view.approved_dish("dish_0001").name_zh == "番茄炒蛋"


def test_using_the_view_leaves_ingredient_file_unchanged(view, data_dir):
    before = (data_dir / "ingredients.yaml").read_bytes()
    for ing in view.ingredients():
        ing.grams_per_unit["x"] = 1
    view.approved_dishes()
    assert (data_dir / "ingredients.yaml").read_bytes() == before
    assert not (data_dir / "ingredients.yaml.bak").exists()

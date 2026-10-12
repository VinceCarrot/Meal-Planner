import pytest

from meal_planner.ai_tools import catalogue_tools
from meal_planner.readonly import ReadOnlyCatalogue
from meal_planner.store import DataStore


@pytest.fixture
def tools(store):
    return {t.name: t.fn for t in catalogue_tools(ReadOnlyCatalogue(store.load()))}


def test_tools_return_catalogue_data(tools):
    assert {i["ingredient_id"] for i in tools["list_ingredients"]("seafood")} == {"ing_shrimp"}
    assert [i["ingredient_id"] for i in tools["search_ingredients"]("西红柿")] == ["ing_tomato"]
    assert tools["search_ingredients"]("  ") == []
    soups = tools["list_dishes"]("soup")
    assert [d["dish_id"] for d in soups] == ["dish_0005"]


def test_pending_dishes_are_not_listed(tools):
    assert not {"dish_0101", "dish_0102"} & {d["dish_id"] for d in tools["list_dishes"]()}


def test_tools_hold_no_path_to_the_data_files(store):
    for tool in catalogue_tools(ReadOnlyCatalogue(store.load())):
        captured = [cell.cell_contents for cell in tool.fn.__closure__ or ()]
        assert captured and all(isinstance(c, ReadOnlyCatalogue) for c in captured), tool.name
        assert not any(isinstance(c, DataStore) for c in captured)


def test_using_every_tool_leaves_ingredients_unchanged(tools, data_dir):
    before = (data_dir / "ingredients.yaml").read_bytes()
    for result in (tools["list_ingredients"](), tools["search_ingredients"]("蛋"), tools["list_dishes"]()):
        for item in result:
            item.clear()  # mutating returned data must not reach the catalogue
    assert tools["list_ingredients"]()[0]["ingredient_id"] == "ing_tomato"
    assert (data_dir / "ingredients.yaml").read_bytes() == before

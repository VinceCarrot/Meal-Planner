import pytest

from conftest import edit_yaml, make_menu
from meal_planner.catalogue import DataError
from meal_planner.models import DishesFile, IngredientsFile
from meal_planner.yaml_io import YamlReadError, create_yaml, read_yaml, write_yaml_atomic


def test_save_replaces_file_and_keeps_backup(store, data_dir):
    cat = store.load()
    before = (data_dir / "dishes.yaml").read_bytes()
    trimmed = DishesFile(dishes=cat.dishes.dishes[:-1])

    updated = store.save_dishes(cat, trimmed)

    assert (data_dir / "dishes.yaml.bak").read_bytes() == before
    assert store.load().approved_dish_ids == updated.approved_dish_ids
    assert "dish_0006" not in updated.approved_dish_ids


def test_invalid_save_does_not_touch_the_file(store, data_dir):
    cat = store.load()
    before = (data_dir / "dishes.yaml").read_bytes()
    bad_line = cat.dishes.dishes[0].ingredients[0].model_copy(update={"ingredient_id": "ing_unknown"})
    bad_dish = cat.dishes.dishes[0].model_copy(update={"ingredients": (bad_line,)})

    with pytest.raises(DataError, match="unknown ingredient_id 'ing_unknown'"):
        store.save_dishes(cat, DishesFile(dishes=(bad_dish,) + cat.dishes.dishes[1:]))

    assert (data_dir / "dishes.yaml").read_bytes() == before
    assert not (data_dir / "dishes.yaml.bak").exists()


def test_removing_an_ingredient_still_in_use_is_rejected(store, data_dir):
    cat = store.load()
    before = (data_dir / "ingredients.yaml").read_bytes()
    remaining = tuple(i for i in cat.ingredients.ingredients if i.ingredient_id != "ing_egg")

    with pytest.raises(DataError, match="ing_egg"):
        store.save_ingredients(cat, IngredientsFile(ingredients=remaining))

    assert (data_dir / "ingredients.yaml").read_bytes() == before


def test_user_ingredient_edit_is_saved(store):
    cat = store.load()
    edited = cat.ingredients.ingredients[0].model_copy(update={"notes": "选熟透的"})
    store.save_ingredients(cat, IngredientsFile(ingredients=(edited,) + cat.ingredients.ingredients[1:]))
    assert store.load().ingredients.ingredients[0].notes == "选熟透的"


def test_failed_serialization_leaves_original_and_no_temp_file(tmp_path):
    path = tmp_path / "x.yaml"
    path.write_text("a: 1\n", encoding="utf-8")
    with pytest.raises(Exception):
        write_yaml_atomic(path, {"a": object()})
    assert path.read_text(encoding="utf-8") == "a: 1\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.yaml"]


def test_corrupt_file_error_mentions_backup(tmp_path):
    path = tmp_path / "x.yaml"
    write_yaml_atomic(path, {"a": 1})
    write_yaml_atomic(path, {"a": 2})
    path.write_text("a: [broken\n", encoding="utf-8")
    with pytest.raises(YamlReadError, match="backup exists: x.yaml.bak"):
        read_yaml(path)
    assert read_yaml(tmp_path / "x.yaml.bak") == {"a": 1}


def test_create_yaml_never_overwrites(tmp_path):
    path = tmp_path / "v001.yaml"
    create_yaml(path, {"a": 1})
    with pytest.raises(FileExistsError):
        create_yaml(path, {"a": 2})
    assert read_yaml(path) == {"a": 1}


# --- Menu versions -------------------------------------------------------------


def test_menu_versions_are_appended_and_loaded(store, data_dir):
    cat = store.load()
    store.save_menu_version(cat, make_menu(version=1))
    store.save_menu_version(cat, make_menu(version=2, based_on_version=1, dish_ids=("dish_0003", "dish_0005")))

    assert (data_dir / "menus/M001/v001.yaml").exists()
    assert store.menu_versions("M001") == [1, 2]
    assert store.load_menu(cat, "M001").version == 2
    assert store.load_menu(cat, "M001", 1).dinners[0].dish_ids == ("dish_0001", "dish_0005")


def test_existing_menu_version_cannot_be_replaced(store):
    cat = store.load()
    store.save_menu_version(cat, make_menu(version=1))
    with pytest.raises(DataError, match="must be 2"):
        store.save_menu_version(cat, make_menu(version=1))


def test_menu_version_numbers_cannot_skip(store):
    with pytest.raises(DataError, match="must be 1"):
        store.save_menu_version(store.load(), make_menu(version=2))


def test_menu_cannot_use_pending_or_unknown_dishes(store, data_dir):
    with pytest.raises(DataError, match="unknown approved dish 'dish_0101'"):
        store.save_menu_version(store.load(), make_menu(dish_ids=("dish_0101",)))
    assert not (data_dir / "menus").exists()


def test_menu_file_location_must_match_content(store, data_dir):
    cat = store.load()
    store.save_menu_version(cat, make_menu())
    edit_yaml(data_dir / "menus/M001/v001.yaml", lambda d: d.update(menu_id="M002"))
    with pytest.raises(DataError, match="file location says M001 v1"):
        store.load_menu(cat, "M001")


def test_feedback_menu_reference_is_checked(store, data_dir):
    edit_yaml(
        data_dir / "preferences.yaml",
        lambda d: d["feedback"][0].update(scope="this_menu", menu_id="M001"),
    )
    with pytest.raises(DataError, match="unknown menu 'M001'"):
        store.load()

    (data_dir / "menus/M001").mkdir(parents=True)
    store.load()

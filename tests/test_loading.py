from pathlib import Path

import pytest

from conftest import edit_yaml
from meal_planner.catalogue import DataError
from meal_planner.store import DataStore

REPO_DATA = Path(__file__).parent.parent / "data"


def _issues(store) -> list[str]:
    with pytest.raises(DataError) as exc:
        store.load()
    return [str(i) for i in exc.value.issues]


def test_sample_data_loads(store):
    cat = store.load()
    assert len(cat.ingredients.ingredients) == 10
    assert cat.approved_dish_ids == {f"dish_000{i}" for i in range(1, 7)}
    assert {d.dish_id for d in cat.pending_dishes.dishes} == {"dish_0101", "dish_0102"}
    assert len(cat.constraints.constraints) == 3


def test_shipped_initial_data_files_are_valid():
    cat = DataStore(REPO_DATA).load()
    assert cat.ingredients.ingredients == ()


def test_invalid_yaml_syntax_names_the_file(store, data_dir):
    (data_dir / "dishes.yaml").write_text("dishes: [unclosed\n", encoding="utf-8")
    [issue] = _issues(store)
    assert issue.startswith("dishes.yaml") and "invalid YAML" in issue


def test_missing_file_is_reported(store, data_dir):
    (data_dir / "constraints.yaml").unlink()
    [issue] = _issues(store)
    assert "constraints.yaml" in issue and "not found" in issue


def test_empty_file_is_reported(store, data_dir):
    (data_dir / "preferences.yaml").write_text("", encoding="utf-8")
    [issue] = _issues(store)
    assert "preferences.yaml" in issue and "expected a mapping" in issue


def test_schema_errors_name_the_record_and_field(store, data_dir):
    def change(data):
        del data["dishes"][2]["dish_type"]
        data["dishes"][3]["style"]["cooking_method"] = "microwave"

    edit_yaml(data_dir / "dishes.yaml", change)
    issues = _issues(store)
    assert any(i.startswith("dishes.yaml: dishes[dish_0003].dish_type: Field required") for i in issues)
    assert any("dishes[dish_0004].style.cooking_method" in i for i in issues)


def test_misspelled_field_is_rejected(store, data_dir):
    edit_yaml(data_dir / "ingredients.yaml", lambda d: d["ingredients"][0].update(kcal_per_100=18))
    [issue] = _issues(store)
    assert "ingredients[ing_tomato].kcal_per_100" in issue


def test_unsupported_schema_version(store, data_dir):
    edit_yaml(data_dir / "constraints.yaml", lambda d: d.update(schema_version=2))
    [issue] = _issues(store)
    assert "schema_version" in issue


def test_errors_from_several_files_are_reported_together(store, data_dir):
    edit_yaml(data_dir / "ingredients.yaml", lambda d: d["ingredients"][0].update(category="fruit"))
    edit_yaml(data_dir / "preferences.yaml", lambda d: d["default_diners"][0].update(count=0))
    issues = _issues(store)
    assert any(i.startswith("ingredients.yaml") for i in issues)
    assert any(i.startswith("preferences.yaml") for i in issues)


def test_duplicate_ingredient_ids(store, data_dir):
    edit_yaml(data_dir / "ingredients.yaml", lambda d: d["ingredients"].append(dict(d["ingredients"][0])))
    assert _issues(store) == ["ingredients.yaml: duplicate ingredient_id 'ing_tomato'"]


def test_dish_id_shared_between_approved_and_pending(store, data_dir):
    edit_yaml(data_dir / "pending_dishes.yaml", lambda d: d["dishes"][0].update(dish_id="dish_0001"))
    assert _issues(store) == ["pending_dishes.yaml: dishes[dish_0001]: dish_id is already used in dishes.yaml"]


def test_unknown_ingredient_references(store, data_dir):
    def change(data):
        data["dishes"][0]["ingredients"][0]["ingredient_id"] = "ing_tomatoe"
        data["dishes"][1]["style"]["main_ingredients"] = ["ing_pork"]

    edit_yaml(data_dir / "dishes.yaml", change)
    assert _issues(store) == [
        "dishes.yaml: dishes[dish_0001]: unknown ingredient_id 'ing_tomatoe'",
        "dishes.yaml: dishes[dish_0002]: unknown ingredient_id 'ing_pork'",
    ]


def test_unknown_ingredient_in_pending_dish_is_reported(store, data_dir):
    edit_yaml(data_dir / "pending_dishes.yaml", lambda d: d["dishes"][0]["ingredients"][0].update(ingredient_id="ing_x"))
    assert _issues(store) == ["pending_dishes.yaml: dishes[dish_0101]: unknown ingredient_id 'ing_x'"]


def test_non_approved_dish_in_approved_file(store, data_dir):
    edit_yaml(data_dir / "dishes.yaml", lambda d: d["dishes"][0].update(review_status="pending"))
    [issue] = _issues(store)
    assert "dishes[dish_0001]" in issue and "only approved dishes" in issue


def test_approved_dish_in_pending_file(store, data_dir):
    edit_yaml(data_dir / "pending_dishes.yaml", lambda d: d["dishes"][0].update(review_status="approved"))
    [issue] = _issues(store)
    assert "approved dishes belong in dishes.yaml" in issue


def test_unmatched_ingredient_not_allowed_in_approved_dish(store, data_dir):
    line = {"unmatched_name": "香菇"}
    edit_yaml(data_dir / "dishes.yaml", lambda d: d["dishes"][2]["ingredients"].append(line))
    [issue] = _issues(store)
    assert "dishes[dish_0003]" in issue and "unmatched" in issue


def test_task_constraint_not_allowed_in_persistent_file(store, data_dir):
    edit_yaml(data_dir / "constraints.yaml", lambda d: d["constraints"][0].update(constraint_id="T001", source="task"))
    assert _issues(store) == ["constraints.yaml: constraints[T001]: only persistent constraints are stored here"]


def test_feedback_must_reference_approved_dish(store, data_dir):
    edit_yaml(data_dir / "preferences.yaml", lambda d: d["feedback"][0].update(dish_id="dish_0101"))
    assert _issues(store) == ["preferences.yaml: feedback[F001]: unknown approved dish 'dish_0101'"]


def test_exclusion_constraint_must_reference_known_ingredients(store, data_dir):
    execution = {"type": "ingredient_exclusion", "ingredient_ids": ["ing_durian"]}
    edit_yaml(data_dir / "constraints.yaml", lambda d: d["constraints"][1].update(execution=execution, parse_status="executable"))
    assert _issues(store) == ["constraints.yaml: constraints[C002]: unknown ingredient_id 'ing_durian'"]

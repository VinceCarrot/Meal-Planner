from meal_planner.demo import create_demo_data
from meal_planner.store import DataStore


def test_demo_data_is_valid_and_never_overwritten(tmp_path):
    data = tmp_path / "demo_data"
    create_demo_data(data)
    cat = DataStore(data).load()
    assert len(cat.dishes.dishes) == 100 and len(cat.constraints.constraints) == 6
    assert len({d.name_zh for d in cat.dishes.dishes}) == 100

    (data / "dishes.yaml").write_text("schema_version: 1\ndishes: []\n", encoding="utf-8")
    create_demo_data(data)
    assert DataStore(data).load().dishes.dishes == ()

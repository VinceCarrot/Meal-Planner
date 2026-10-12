import shutil
from datetime import date, datetime
from pathlib import Path

import pytest
import yaml

from meal_planner.models import Diner, Dinner, MenuVersion, plan_dates
from meal_planner.store import DataStore

FIXTURES = Path(__file__).parent / "fixtures"
PLAN_START = date(2026, 10, 19)  # a Monday


@pytest.fixture
def data_dir(tmp_path) -> Path:
    """A private copy of the sample data set; tests never touch the fixtures or real data."""
    target = tmp_path / "data"
    shutil.copytree(FIXTURES / "sample", target)
    return target


@pytest.fixture
def store(data_dir) -> DataStore:
    return DataStore(data_dir)


def edit_yaml(path: Path, change) -> None:
    """Load a YAML file, let `change` modify the parsed data in place, write it back."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def make_menu(version: int = 1, dish_ids=("dish_0001", "dish_0005"), **overrides) -> MenuVersion:
    fields = dict(
        menu_id="M001",
        version=version,
        start_date=PLAN_START,
        diners=(Diner(description="成年女性", count=3),),
        dinners=tuple(Dinner(date=d, dish_ids=dish_ids) for d in plan_dates(PLAN_START)),
        created_at=datetime(2026, 10, 12, 20, 0),
    )
    fields.update(overrides)
    return MenuVersion(**fields)

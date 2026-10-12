import pydantic
import yaml

import meal_planner


def test_package_and_core_dependencies_import():
    assert meal_planner.__doc__
    assert pydantic.VERSION.startswith("2.")
    assert yaml.safe_load("a: 1") == {"a": 1}

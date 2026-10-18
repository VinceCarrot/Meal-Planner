"""Frequent dishes (常用菜): only they are offered to menu generation (ADR-026)."""

import dataclasses
from datetime import date

import pytest
import yaml

from meal_planner.constraints import build_effective_set
from meal_planner.demo import synthetic_catalogue, write_catalogue
from meal_planner.models import Constraint, Dinner, DishesFile
from meal_planner.plan_context import make_context
from meal_planner.planner import plan_menu
from meal_planner.settings import Settings
from meal_planner.validator import PlanStatus, validate_menu
from meal_planner.vocab import TaskScope
from meal_planner.web import create_app

from fakes import FakeLLM

START = date(2026, 10, 19)
GEN = TaskScope.MENU_GENERATION


def _effective(*executions):
    constraints = [
        Constraint(constraint_id=f"C{n:03d}", description=f"rule {n}", scope=[GEN], strictness="hard",
                   source="persistent", execution=e, parse_status="executable")
        for n, e in enumerate(executions, start=1)
    ]
    return build_effective_set(constraints, [], GEN)


THREE_DISHES = {"type": "dish_count", "min": 3, "max": 3}


@pytest.fixture
def settings():
    s = Settings()
    return Settings(planner=s.planner.model_copy(update={"time_limit_s": 10}))


@pytest.fixture
def catalogue():
    cat = synthetic_catalogue(100)
    # Every other dish is not frequent.
    dishes = tuple(d.model_copy(update={"frequent": n % 2 == 0}) for n, d in enumerate(cat.dishes.dishes))
    return dataclasses.replace(cat, dishes=DishesFile(dishes=dishes))


def test_dishes_are_frequent_by_default():
    assert all(d.frequent for d in synthetic_catalogue(10).dishes.dishes)


def test_generation_uses_only_frequent_dishes(catalogue, settings):
    ctx = make_context(catalogue, settings, START, frequent_only=True)
    result = plan_menu(ctx, _effective(THREE_DISHES, {"type": "exact_repeat_window", "weeks": 1}))
    assert result.status == PlanStatus.FEASIBLE
    used = {k for d in result.dinners for k in d.dish_ids}
    assert used and all(ctx.dishes[k].frequent for k in used)


def test_without_the_restriction_other_dishes_may_be_chosen(catalogue, settings):
    ctx = make_context(catalogue, settings, START)
    assert ctx.selectable is None and all(ctx.is_selectable(k) for k in ctx.dishes)


def test_a_menu_with_other_approved_dishes_is_still_valid(catalogue, settings):
    """Validation knows every approved dish; the restriction only limits what the planner picks."""
    ctx = make_context(catalogue, settings, START, frequent_only=True)
    other = [d.dish_id for d in catalogue.dishes.dishes if not d.frequent]
    dinners = list(plan_menu(ctx, _effective(THREE_DISHES)).dinners)
    dinners[0] = Dinner(date=dinners[0].date, dish_ids=tuple(other[:3]))
    assert not validate_menu(dinners, ctx, _effective(THREE_DISHES)).structural_errors


def test_too_few_frequent_dishes_is_reported_not_silently_widened(catalogue, settings):
    only_two = tuple(d.model_copy(update={"frequent": n < 2}) for n, d in enumerate(catalogue.dishes.dishes))
    ctx = make_context(dataclasses.replace(catalogue, dishes=DishesFile(dishes=only_two)), settings, START, frequent_only=True)
    result = plan_menu(ctx, _effective(THREE_DISHES))
    assert result.status == PlanStatus.INFEASIBLE and result.dinners is None
    assert any("98 approved dish(es) not marked 常用" in m for m in result.messages)


# --- API --------------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    data = tmp_path / "data"
    write_catalogue(synthetic_catalogue(30), data)
    return create_app(data, llm_factory=lambda s, t: FakeLLM()).test_client(), data


def test_frequent_flag_is_saved_immediately(client):
    client, data = client
    response = client.put("/api/dishes/dish_0001/frequent", json={"frequent": False})
    assert response.status_code == 200 and response.get_json() == {"dish_id": "dish_0001", "frequent": False}

    saved = yaml.safe_load((data / "dishes.yaml").read_text(encoding="utf-8"))["dishes"]
    assert [d["frequent"] for d in saved if d["dish_id"] == "dish_0001"] == [False]
    dishes = {d["dish_id"]: d for d in client.get("/api/dishes").get_json()}
    assert dishes["dish_0001"]["frequent"] is False and dishes["dish_0002"]["frequent"] is True

    # Editing the dish keeps the flag the form sends back (the form drops the computed calories).
    form = {k: v for k, v in dishes["dish_0001"].items() if k != "calories"}
    edited = client.put("/api/dishes/dish_0001", json=form | {"name_zh": "改名了"}).get_json()
    assert edited["frequent"] is False and edited["name_zh"] == "改名了"


def test_frequent_flag_rejects_bad_input(client):
    client, _ = client
    assert client.put("/api/dishes/dish_0001/frequent", json={"frequent": "no"}).status_code == 400
    assert client.put("/api/dishes/dish_9999/frequent", json={"frequent": True}).status_code == 404


def test_generation_endpoint_uses_frequent_dishes_only(client):
    client, data = client
    for n in range(1, 31, 2):
        client.put(f"/api/dishes/dish_{n:04d}/frequent", json={"frequent": False})
    constraints = {"schema_version": 1, "constraints": [{
        "constraint_id": "C001", "description": "每顿3个菜", "scope": ["menu_generation"], "strictness": "hard",
        "source": "persistent", "execution": THREE_DISHES, "parse_status": "executable"}]}
    (data / "constraints.yaml").write_text(yaml.safe_dump(constraints, allow_unicode=True), encoding="utf-8")

    planned = client.post("/api/menus/plan", json={"start_date": "2026-10-19"}).get_json()
    used = {x["dish_id"] for d in planned["dinners"] for x in d["dishes"]}
    assert used and all(int(k[5:]) % 2 == 0 for k in used)


# --- Lunchbox tag (ADR-027) -------------------------------------------------------------


def test_dishes_are_not_lunchbox_by_default():
    assert not any(d.lunchbox for d in synthetic_catalogue(10).dishes.dishes)


def test_lunchbox_tag_is_saved_immediately_and_independently(client):
    client, data = client
    response = client.put("/api/dishes/dish_0002/lunchbox", json={"lunchbox": True})
    assert response.status_code == 200 and response.get_json() == {"dish_id": "dish_0002", "lunchbox": True}

    saved = {d["dish_id"]: d for d in yaml.safe_load((data / "dishes.yaml").read_text(encoding="utf-8"))["dishes"]}
    assert saved["dish_0002"]["lunchbox"] is True and saved["dish_0002"]["frequent"] is True
    assert saved["dish_0003"]["lunchbox"] is False

    form = {k: v for k, v in client.get("/api/dishes").get_json()[1].items() if k != "calories"}
    assert client.put("/api/dishes/dish_0002", json=form | {"servings": 2}).get_json()["lunchbox"] is True


def test_lunchbox_tag_rejects_bad_input(client):
    client, _ = client
    assert client.put("/api/dishes/dish_0002/lunchbox", json={"lunchbox": 1}).status_code == 400
    assert client.put("/api/dishes/dish_0002/lunchbox", json={"frequent": True}).status_code == 400
    assert client.put("/api/dishes/dish_9999/lunchbox", json={"lunchbox": True}).status_code == 404

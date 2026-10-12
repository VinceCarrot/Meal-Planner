from datetime import date

import pytest

from meal_planner.adjust import menu_changes, propose_replacement, save_adjusted_version
from meal_planner.catalogue import DataError
from meal_planner.demo import synthetic_catalogue, write_catalogue
from meal_planner.menus import plan_new_menu, prepare, save_new_menu, task_constraints_from_input
from meal_planner.models import (
    Constraint,
    ConstraintsFile,
    Diner,
    DishesFile,
    DishIngredient,
    DishStyle,
    Ingredient,
    IngredientsFile,
)
from meal_planner.plan_context import make_context
from meal_planner.settings import Settings
from meal_planner.store import DataStore
from meal_planner.validator import PlanStatus
from meal_planner.vocab import FeedbackScope, TaskScope

START = date(2026, 10, 19)
ADJ = TaskScope.MENU_ADJUSTMENT
RULES = [
    ({"type": "dish_count", "min": 4, "max": 4}),
    ({"type": "dish_type_count", "dish_type": "soup", "min": 1, "max": 1}),
    ({"type": "dish_type_count", "dish_type": "meat", "min": 1}),
    ({"type": "exact_repeat_window", "weeks": 2}),
]


@pytest.fixture
def settings():
    return Settings(planner=Settings().planner.model_copy(update={"time_limit_s": 10}))


@pytest.fixture
def saved(tmp_path, settings):
    """A data directory with one saved menu M001 v1."""
    store = DataStore(tmp_path / "data")
    write_catalogue(synthetic_catalogue(100), store.data_dir)
    cat = store.load()
    persistent = tuple(
        Constraint(constraint_id=f"C{n:03d}", description=f"rule {n}", scope=["menu_generation", "menu_adjustment"],
                   strictness="hard", source="persistent", execution=e, parse_status="executable")
        for n, e in enumerate(RULES, start=1)
    )
    cat = store.save_constraints(cat, ConstraintsFile(constraints=persistent))
    ctx, effective, result = plan_new_menu(store, cat, settings, START, [])
    menu, _ = save_new_menu(store, cat, ctx, effective, [Diner(description="成年女性", count=3)], result.dinners)
    return store, menu


def _task(*executions, overrides=()):
    return [
        Constraint(constraint_id=f"T{n:03d}", description=f"task {n}", scope=[ADJ], strictness="hard", source="task",
                   execution=e, parse_status="executable" if e else "unparsed", overrides=overrides)
        for n, e in enumerate(executions, start=1)
    ]


def _propose(store, menu, settings, target, task_constraints=()):
    cat = store.load()
    ctx, effective = prepare(store, cat, settings, menu.start_date, list(task_constraints), ADJ, exclude_menu=menu.menu_id)
    return ctx, effective, propose_replacement(ctx, effective, menu, *target)


def _target(menu, day=7, position=1):
    dinner = menu.dinners[day]
    return dinner.date, dinner.dish_ids[position]


def test_single_dish_is_replaced_and_everything_else_is_kept(saved, settings):
    store, menu = saved
    target_date, target_dish = _target(menu)

    _, _, proposal = _propose(store, menu, settings, (target_date, target_dish))

    assert proposal.status == PlanStatus.FEASIBLE and proposal.scope == "dish"
    [change] = proposal.changes
    assert change.date == target_date and change.removed == (target_dish,) and len(change.added) == 1
    for before, after in zip(menu.dinners, proposal.dinners):
        if before.date != target_date:
            assert before == after
        else:
            assert set(before.dish_ids) - {target_dish} <= set(after.dish_ids)
            assert target_dish not in after.dish_ids


def test_scope_widens_to_the_dinner_only_when_needed(saved, settings):
    store, menu = saved
    target_date, target_dish = _target(menu)
    # Put a dish with a unique ingredient (okra) next to the target dish, then exclude okra:
    # replacing the target dish alone cannot satisfy the rule; rebuilding that dinner can.
    cat = store.load()
    by_id = {d.dish_id: d for d in cat.dishes.dishes}
    neighbour = next(k for k in menu.dinners[7].dish_ids if k != target_dish and by_id[k].dish_type != "soup")
    neighbour_dish = by_id[neighbour]
    okra = Ingredient(ingredient_id="ing_okra", name_zh="秋葵", category="vegetable")
    cat = store.save_ingredients(cat, IngredientsFile(ingredients=cat.ingredients.ingredients + (okra,)))
    okra_dish = neighbour_dish.model_copy(update={
        "dish_id": "dish_0999", "name_zh": "秋葵菜", "ingredients": (DishIngredient(ingredient_id="ing_okra"),),
        "style": DishStyle(main_ingredients=("ing_okra",)),
    })
    cat = store.save_dishes(cat, DishesFile(dishes=cat.dishes.dishes + (okra_dish,)))
    dinners = list(menu.dinners)
    dinners[7] = dinners[7].model_copy(update={"dish_ids": tuple("dish_0999" if k == neighbour else k for k in dinners[7].dish_ids)})
    ctx, effective = prepare(store, cat, settings, START, [], ADJ, exclude_menu="M001")
    menu, _ = save_adjusted_version(store, cat, ctx, effective, menu, dinners, "放入秋葵菜")

    exclusion = {"type": "ingredient_exclusion", "ingredient_ids": ["ing_okra"]}
    _, _, proposal = _propose(store, menu, settings, (target_date, target_dish), _task(exclusion))

    assert [a.scope for a in proposal.attempts] == ["dish", "dinner"]
    assert proposal.attempts[0].status != PlanStatus.FEASIBLE
    assert proposal.scope == "dinner" and proposal.status == PlanStatus.FEASIBLE
    assert {c.date for c in proposal.changes} == {target_date}  # other dinners untouched
    assert "dish_0999" not in proposal.dinners[7].dish_ids


def test_impossible_adjustment_reports_every_scope_and_changes_nothing(saved, settings):
    store, menu = saved
    two_soups = {"type": "dish_type_count", "dish_type": "soup", "min": 2, "max": 2}

    _, _, proposal = _propose(store, menu, settings, _target(menu), _task(two_soups, overrides=("C002",)))

    assert proposal.status == PlanStatus.INFEASIBLE and proposal.dinners is None
    assert [a.scope for a in proposal.attempts] == ["dish", "dinner", "week", "menu"]
    assert "more approved soup dishes needed" in proposal.attempts[-1].message
    assert store.menu_versions("M001") == [1]


def test_unresolved_constraint_blocks_without_widening(saved, settings):
    store, menu = saved
    _, _, proposal = _propose(store, menu, settings, _target(menu), _task(None))
    assert proposal.status == PlanStatus.BLOCKED and len(proposal.attempts) == 1


def test_target_must_be_on_the_menu(saved, settings):
    store, menu = saved
    with pytest.raises(ValueError):
        _propose(store, menu, settings, (menu.dinners[0].date, "dish_9999"))


def test_saving_creates_a_new_version_and_records_feedback(saved, settings):
    store, menu = saved
    target = _target(menu)
    v1_file = (store.data_dir / "menus/M001/v001.yaml").read_bytes()
    ctx, effective, proposal = _propose(store, menu, settings, target)

    new, report = save_adjusted_version(store, store.load(), ctx, effective, menu, proposal.dinners, "不喜欢这道菜",
                                        (target[1], FeedbackScope.THIS_MENU, "太咸"))

    assert (new.version, new.based_on_version, new.change_note) == (2, 1, "不喜欢这道菜")
    assert report.status == PlanStatus.FEASIBLE and new.validation_report["status"] == "feasible"
    assert (store.data_dir / "menus/M001/v001.yaml").read_bytes() == v1_file
    assert store.menu_versions("M001") == [1, 2]
    assert [c.date for c in menu_changes(menu.dinners, store.load_menu(store.load(), "M001").dinners)] == [target[0]]
    [feedback] = store.load().preferences.feedback
    assert (feedback.dish_id, feedback.scope, feedback.menu_id, feedback.note) == (target[1], "this_menu", "M001", "太咸")


def test_this_menu_feedback_only_applies_to_its_menu(saved, settings):
    store, menu = saved
    target = _target(menu)
    ctx, effective, proposal = _propose(store, menu, settings, target)
    save_adjusted_version(store, store.load(), ctx, effective, menu, proposal.dinners, "x", (target[1], FeedbackScope.THIS_MENU, None))

    cat = store.load()
    assert target[1] in make_context(cat, settings, START, menu_id="M001").disliked
    assert target[1] not in make_context(cat, settings, START, menu_id="M002").disliked
    assert target[1] not in make_context(cat, settings, START).disliked


def test_saved_adjustment_is_revalidated(saved, settings):
    store, menu = saved
    ctx, effective, _ = _propose(store, menu, settings, _target(menu))
    broken = list(menu.dinners)
    broken[3] = broken[3].model_copy(update={"dish_ids": broken[3].dish_ids[:1]})

    new, report = save_adjusted_version(store, store.load(), ctx, effective, menu, broken, "手动改坏")

    assert report.status == PlanStatus.BEST_EFFORT and new.validation_report["status"] == "best_effort"


def test_generation_task_constraints_are_not_accepted_for_adjustment(saved):
    store, _ = saved
    for_generation = Constraint(constraint_id="T001", description="x", scope=["menu_generation"], strictness="hard", source="task")
    with pytest.raises(DataError, match="menu_adjustment"):
        task_constraints_from_input([for_generation.model_dump(mode="json")], ADJ, store.load())

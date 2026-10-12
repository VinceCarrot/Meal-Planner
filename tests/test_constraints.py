import pytest

from fakes import FakeLLM, result
from meal_planner.constraints import (
    TaskConstraintInput,
    add_persistent,
    build_effective_set,
    edit_persistent,
    find_conflicts,
    make_task_constraints,
    parse_unparsed_persistent,
    remove_persistent,
)
from meal_planner.llm import LLMError
from meal_planner.models import Constraint
from meal_planner.vocab import TaskScope

GEN = TaskScope.MENU_GENERATION
ADJ = TaskScope.MENU_ADJUSTMENT
SOUP_ONCE = {"type": "dish_type_count", "dish_type": "soup", "min": 1, "max": 1}


def _c(cid, execution=None, status=None, strictness="hard", scope=(GEN, ADJ), **extra):
    source = "persistent" if cid.startswith("C") else "task"
    status = status or ("executable" if execution else "unparsed")
    return Constraint(
        constraint_id=cid, description=f"rule {cid}", scope=scope, strictness=strictness,
        source=source, execution=execution, parse_status=status, **extra,
    )


def _task(cid, execution, task=GEN, **extra):
    return _c(cid, execution, scope=(task,), **extra)


# --- Persistent constraint editing -------------------------------------------------


def test_add_persistent_saves_an_unparsed_constraint(store):
    cat, added = add_persistent(store, store.load(), "每顿至少一个大荤")
    assert added.constraint_id == "C004"
    assert added.parse_status == "unparsed"
    assert store.load().constraints.constraints[-1] == added


def test_editing_description_discards_interpretation(store):
    cat = edit_persistent(store, store.load(), "C001", description="每顿两个汤")
    c001 = cat.constraints.constraints[0]
    assert (c001.parse_status, c001.execution, c001.description) == ("unparsed", None, "每顿两个汤")


def test_editing_strictness_keeps_interpretation(store):
    cat = edit_persistent(store, store.load(), "C001", strictness="soft", active=False)
    c001 = store.load().constraints.constraints[0]
    assert (c001.strictness, c001.active, c001.execution.dish_type) == ("soft", False, "soup")


def test_remove_persistent(store):
    remove_persistent(store, store.load(), "C003")
    assert [c.constraint_id for c in store.load().constraints.constraints] == ["C001", "C002"]
    with pytest.raises(KeyError):
        remove_persistent(store, store.load(), "C003")


def test_parse_unparsed_persistent_sends_only_unparsed(store):
    llm = FakeLLM({"results": [result("C002", execution={"type": "exact_repeat_window", "weeks": 2})]})
    parse_unparsed_persistent(store, store.load(), llm)
    assert "C002:" in llm.calls[0]["prompt"] and "C001:" not in llm.calls[0]["prompt"]
    c002 = store.load().constraints.constraints[1]
    assert (c002.parse_status, c002.execution.weeks) == ("executable", 2)


def test_parse_failure_leaves_file_unchanged(store, data_dir):
    before = (data_dir / "constraints.yaml").read_bytes()
    with pytest.raises(LLMError):
        parse_unparsed_persistent(store, store.load(), FakeLLM(error=LLMError("timeout")))
    assert (data_dir / "constraints.yaml").read_bytes() == before


# --- Task constraints and the effective set ---------------------------------------


def test_task_constraints_are_scoped_to_their_task():
    [t] = make_task_constraints([TaskConstraintInput("这次不要红烧", overrides=("C001",))], ADJ)
    assert (t.constraint_id, t.source, t.scope, t.overrides) == ("T001", "task", (ADJ,), ("C001",))


def test_generation_task_constraints_cannot_be_used_for_adjustment():
    [t] = make_task_constraints([TaskConstraintInput("每顿4个菜")], GEN)
    with pytest.raises(ValueError, match="not a task constraint for menu_adjustment"):
        build_effective_set([], [t], ADJ)


def test_persistent_scope_selects_constraints_per_task():
    gen_only = _c("C001", SOUP_ONCE, scope=(GEN,))
    both = _c("C002", {"type": "exact_repeat_window", "weeks": 2})
    inactive = _c("C003", {"type": "dish_count", "min": 3}, active=False)
    persistent = [gen_only, both, inactive]
    assert [c.constraint_id for c in build_effective_set(persistent, [], GEN).constraints] == ["C001", "C002"]
    assert [c.constraint_id for c in build_effective_set(persistent, [], ADJ).constraints] == ["C002"]


def test_task_constraints_do_not_change_persistent_ones(store, data_dir):
    cat = store.load()
    before_file = (data_dir / "constraints.yaml").read_bytes()
    persistent = cat.constraints.constraints
    t = _task("T001", {**SOUP_ONCE, "min": 2, "max": 2}, overrides=("C001",))

    effective = build_effective_set(persistent, [t], GEN)

    assert effective.overridden == (persistent[0],)
    assert cat.constraints.constraints is persistent and persistent[0].execution.max == 1
    assert (data_dir / "constraints.yaml").read_bytes() == before_file


def test_explicit_override_applies_only_to_its_task():
    c001 = _c("C001", SOUP_ONCE)
    t = _task("T001", {**SOUP_ONCE, "min": 0, "max": 0}, overrides=("C001",))

    with_override = build_effective_set([c001], [t], GEN)
    assert with_override.ready
    assert [c.constraint_id for c in with_override.constraints] == ["T001"]
    assert with_override.status_of("C001") == "executable"

    next_task = build_effective_set([c001], [], GEN)
    assert [c.constraint_id for c in next_task.constraints] == ["C001"]


def test_implicit_conflict_is_surfaced_not_resolved():
    c001 = _c("C001", SOUP_ONCE)
    t = _task("T001", {**SOUP_ONCE, "min": 2, "max": 2})

    effective = build_effective_set([c001], [t], GEN)

    assert not effective.ready
    [issue] = effective.issues
    assert issue.kind == "conflict" and issue.constraint_ids == ("C001", "T001")
    assert effective.status_of("C001") == effective.status_of("T001") == "conflict"
    assert {c.constraint_id for c in effective.constraints} == {"C001", "T001"}


def test_unknown_override_is_reported():
    t = _task("T001", SOUP_ONCE, overrides=("C009",))
    [issue] = build_effective_set([], [t], GEN).issues
    assert issue.kind == "unknown_override" and "C009" in issue.message


def test_unparsed_and_ambiguous_constraints_block_the_task():
    unparsed = _c("C001")
    ambiguous = _c("C002", status="needs_clarification", parse_notes="单调指什么？")
    effective = build_effective_set([unparsed, ambiguous], [], GEN)
    assert [(i.kind, i.constraint_ids) for i in effective.issues] == [
        ("unparsed", ("C001",)),
        ("needs_clarification", ("C002",)),
    ]
    assert "单调指什么" in effective.issues[1].message


def test_unsupported_constraints_are_reported_but_do_not_block():
    effective = build_effective_set([_c("C001", status="unsupported", parse_notes="热量")], [], GEN)
    assert effective.ready
    assert [c.constraint_id for c in effective.unsupported] == ["C001"]


# --- Deterministic conflict detection ----------------------------------------------


def test_compatible_counts_do_not_conflict():
    constraints = [
        _c("C001", {"type": "dish_count", "min": 3, "max": 4}),
        _c("C002", {"type": "dish_count", "min": 4}),
        _c("C003", SOUP_ONCE),
        _c("C004", {"type": "dish_type_count", "dish_type": "meat", "min": 1}),
        _c("C005", {"type": "dish_type_count", "dish_type": "meat", "max": 2}),
    ]
    assert find_conflicts(constraints) == []


def test_disjoint_dish_counts_conflict():
    a = _c("C001", {"type": "dish_count", "min": 3, "max": 4})
    b = _c("C002", {"type": "dish_count", "min": 5})
    [issue] = find_conflicts([a, b])
    assert issue.constraint_ids == ("C001", "C002") and "3-4 vs 5-∞" in issue.message


def test_type_minimums_exceeding_total_maximum_conflict():
    constraints = [
        _c("C001", {"type": "dish_count", "max": 3}),
        _c("C002", SOUP_ONCE),
        _c("C003", {"type": "dish_type_count", "dish_type": "meat", "min": 1}),
        _c("C004", {"type": "dish_type_count", "dish_type": "vegetarian", "min": 2}),
    ]
    [issue] = find_conflicts(constraints)
    assert set(issue.constraint_ids) == {"C001", "C002", "C003", "C004"}
    assert "at least 4 dishes" in issue.message


def test_unparsed_constraints_are_not_checked_for_conflicts():
    assert find_conflicts([_c("C001"), _c("C002", status="unsupported")]) == []

import pytest

from fakes import FakeLLM, result
from meal_planner.constraint_parser import parse_constraints
from meal_planner.constraints import make_task_constraints, TaskConstraintInput
from meal_planner.constraint_types import CONSTRAINT_TYPES
from meal_planner.llm import LLMError
from meal_planner.readonly import ReadOnlyCatalogue
from meal_planner.vocab import TaskScope


@pytest.fixture
def view(store):
    return ReadOnlyCatalogue(store.load())


def _task(*descriptions):
    return make_task_constraints([TaskConstraintInput(d) for d in descriptions], TaskScope.MENU_GENERATION)


def _parse_one(view, description, response_item):
    [c] = _task(description)
    [parsed] = parse_constraints(FakeLLM({"results": [response_item]}), [c], view)
    return parsed


@pytest.mark.parametrize(
    "description, execution",
    [
        ("每顿饭3到4个菜", {"type": "dish_count", "min": 3, "max": 4}),
        ("每顿饭恰好一个汤", {"type": "dish_type_count", "dish_type": "soup", "min": 1, "max": 1}),
        ("每顿至少一个大荤", {"type": "dish_type_count", "dish_type": "meat", "min": 1}),
        ("每顿至少两个素菜", {"type": "dish_type_count", "dish_type": "vegetarian", "min": 2}),
        ("不吃海鲜", {"type": "ingredient_exclusion", "categories": ["seafood"]}),
        ("不吃豆腐", {"type": "ingredient_exclusion", "ingredient_ids": ["ing_tofu"]}),
        ("两周内不重复同一道菜", {"type": "exact_repeat_window", "weeks": 2}),
        ("同一周的菜别太像", {"type": "dish_similarity", "window_weeks": 1}),
        ("连续几天的晚餐整体别太像", {"type": "meal_similarity", "max_similarity": 0.6}),
    ],
)
def test_executable_examples_are_accepted(view, description, execution):
    parsed = _parse_one(view, description, result("T001", execution=execution, notes="ok"))
    assert parsed.parse_status == "executable"
    assert parsed.execution.type == execution["type"]
    assert parsed.description == description
    assert parsed.parse_notes == "ok"


def test_registry_covers_the_supported_types():
    assert set(CONSTRAINT_TYPES) == {
        "dish_count", "dish_type_count", "matching_dish_count", "any_of", "ingredient_exclusion",
        "no_shared_ingredients", "exact_repeat_window", "dish_similarity", "meal_similarity",
    }


def test_prompt_contains_rules_types_and_ingredients(view):
    llm = FakeLLM({"results": [result("T001", "unsupported", notes="x")]})
    parse_constraints(llm, _task("孩子要多吃蔬菜"), view)
    call = llm.calls[0]
    assert "T001: 孩子要多吃蔬菜" in call["prompt"]
    assert all(name in call["system"] for name in CONSTRAINT_TYPES)
    assert "ing_shrimp 虾仁 [seafood]" in call["system"]
    assert "results" in call["schema"]["properties"]


def test_parser_proposes_strictness(view):
    parsed = _parse_one(view, "尽量两周不重复", result("T001", strictness="soft", execution={"type": "exact_repeat_window", "weeks": 2}))
    assert parsed.strictness == "soft"


def test_unsupported_is_reported_honestly(view):
    parsed = _parse_one(view, "每顿不超过600千卡", result("T001", "unsupported", notes="暂不支持热量约束"))
    assert parsed.parse_status == "unsupported"
    assert parsed.execution is None
    assert parsed.parse_notes == "暂不支持热量约束"


def test_needs_clarification_keeps_the_question(view):
    parsed = _parse_one(view, "口味别太单调", result("T001", "needs_clarification", "soft", notes="单调指什么？"))
    assert (parsed.parse_status, parsed.parse_notes) == ("needs_clarification", "单调指什么？")


def test_execution_on_non_evaluable_result_is_dropped(view):
    item = result("T001", "unsupported", execution={"type": "exact_repeat_window", "weeks": 1}, notes="x")
    assert _parse_one(view, "x", item).execution is None


@pytest.mark.parametrize(
    "item, expected_note",
    [
        (result("T001", execution={"type": "calorie_target", "kcal": 600}), "parser output invalid"),
        (result("T001", execution={"type": "dish_count", "min": 5, "max": 3}), "parser output invalid"),
        (result("T001", execution=None), "without execution"),
        (result("T001", "conflict", execution={"type": "dish_count", "min": 3}), "parser output invalid"),
        ({**result("T001", execution={"type": "dish_count", "min": 3}), "confidence": 0.9}, "parser output invalid"),
        (result("T001", strictness="must", execution={"type": "dish_count", "min": 3}), "parser output invalid"),
        ("not an object", "no result"),
    ],
)
def test_malformed_parser_output_leaves_constraint_unparsed(view, item, expected_note):
    parsed = _parse_one(view, "每顿3个菜", item)
    assert parsed.parse_status == "unparsed"
    assert parsed.execution is None
    assert expected_note in parsed.parse_notes


@pytest.mark.parametrize("response", [None, {}, {"results": "x"}, ["T001"]])
def test_missing_results_list(view, response):
    [parsed] = parse_constraints(FakeLLM(response), _task("每顿3个菜"), view)
    assert parsed.parse_status == "unparsed" and "missing 'results'" in parsed.parse_notes


def test_missing_and_duplicate_results(view):
    constraints = _task("每顿3个菜", "不吃海鲜")
    dup = result("T002", execution={"type": "ingredient_exclusion", "categories": ["seafood"]})
    first, second = parse_constraints(FakeLLM({"results": [dup, dup]}), constraints, view)
    assert "no result" in first.parse_notes
    assert "several results" in second.parse_notes


def test_results_for_unknown_ids_are_ignored(view):
    item = result("C001", execution={"type": "dish_count", "min": 3})
    [parsed] = parse_constraints(FakeLLM({"results": [item]}), _task("每顿3个菜"), view)
    assert parsed.parse_status == "unparsed"


def test_unknown_ingredient_id_needs_clarification(view):
    item = result("T001", execution={"type": "ingredient_exclusion", "ingredient_ids": ["ing_durian"]})
    parsed = _parse_one(view, "不吃榴莲", item)
    assert parsed.parse_status == "needs_clarification"
    assert parsed.execution is None
    assert "ing_durian" in parsed.parse_notes


def test_llm_failure_propagates(view):
    with pytest.raises(LLMError):
        parse_constraints(FakeLLM(error=LLMError("not logged in")), _task("每顿3个菜"), view)


def test_nothing_to_parse_makes_no_call(view):
    llm = FakeLLM()
    assert parse_constraints(llm, [], view) == []
    assert llm.calls == []

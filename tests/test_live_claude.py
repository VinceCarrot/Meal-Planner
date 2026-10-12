"""End-to-end checks against the real Claude Code CLI (uses the Claude subscription).

Skipped by default. Run with:  MEAL_PLANNER_LIVE_LLM=1 pytest tests/test_live_claude.py
Assertions only cover unambiguous cases, since model wording varies.
"""

import os

import pytest

from meal_planner.candidates import CandidateRequest, generate_candidates
from meal_planner.constraint_parser import parse_constraints
from meal_planner.constraints import TaskConstraintInput, make_task_constraints
from meal_planner.llm import Tool, create_backend
from meal_planner.readonly import ReadOnlyCatalogue
from meal_planner.vocab import TaskScope

pytestmark = pytest.mark.skipif(not os.environ.get("MEAL_PLANNER_LIVE_LLM"), reason="set MEAL_PLANNER_LIVE_LLM=1")


def test_live_constraint_parsing(store):
    view = ReadOnlyCatalogue(store.load())
    inputs = ["每顿饭恰好一个汤", "不吃海鲜", "每顿饭不超过600千卡"]
    constraints = make_task_constraints([TaskConstraintInput(d) for d in inputs], TaskScope.MENU_GENERATION)

    soup, seafood, calories = parse_constraints(create_backend(), constraints, view)

    assert soup.parse_status == "executable"
    assert soup.execution.model_dump() == {"type": "dish_type_count", "dish_type": "soup", "min": 1, "max": 1}
    assert seafood.parse_status == "executable" and seafood.execution.type == "ingredient_exclusion"
    assert "seafood" in seafood.execution.categories or "ing_shrimp" in seafood.execution.ingredient_ids
    assert calories.parse_status in ("unsupported", "needs_clarification") and calories.execution is None


def test_live_agent_uses_read_only_tool(store):
    view = ReadOnlyCatalogue(store.load())
    calls = []

    def find_ingredients(keyword: str) -> list[dict]:
        """Find catalogue ingredients whose Chinese name or alias contains the keyword."""
        calls.append(keyword)
        return [
            {"ingredient_id": i.ingredient_id, "name_zh": i.name_zh}
            for i in view.ingredients()
            if keyword in i.name_zh or any(keyword in a for a in i.aliases)
        ]

    schema = {
        "type": "object",
        "properties": {"ingredient_ids": {"type": "array", "items": {"type": "string"}}},
        "required": ["ingredient_ids"],
        "additionalProperties": False,
    }
    output = create_backend().agent(
        "Look up ingredient IDs with the find_ingredients tool. Never guess IDs.",
        "西红柿和虾仁的 ingredient_id 分别是什么？",
        [Tool("find_ingredients", "Search the ingredient catalogue by Chinese name or alias.", find_ingredients)],
        schema,
    )
    assert calls
    assert set(output["ingredient_ids"]) == {"ing_tomato", "ing_shrimp"}


def test_live_candidate_generation(store):
    cat = store.load()
    llm = create_backend()  # account default model, as configured for dish_generation
    _, result = generate_candidates(store, cat, llm, CandidateRequest("soup", 2, "测试：需要两道新的汤"))

    assert result.added, result.rejected
    for dish in result.added:
        assert dish.dish_type == "soup" and dish.review_status == "pending" and dish.steps
    assert store.load().approved_dish_ids == cat.approved_dish_ids

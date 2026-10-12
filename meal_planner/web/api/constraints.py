"""Persistent constraints and task-constraint parsing."""

from flask import Blueprint

from ...constraint_parser import parse_constraints
from ...constraints import (
    TaskConstraintInput,
    add_persistent,
    build_effective_set,
    edit_persistent,
    make_task_constraints,
    parse_unparsed_persistent,
    remove_persistent,
)
from ...menus import task_constraints_from_input
from ...readonly import ReadOnlyCatalogue
from ...settings import LLMTask
from ...vocab import Strictness, TaskScope
from ..helpers import NotFound, body, dump, llm, load
from ..serialize import effective_view

bp = Blueprint("constraints", __name__)


@bp.get("/constraints")
def list_constraints():
    _, cat = load()
    return [dump(c) for c in cat.constraints.constraints]


@bp.post("/constraints")
def add_constraint():
    store, cat = load()
    data = body()
    scope = [TaskScope(s) for s in data.get("scope") or [TaskScope.MENU_GENERATION, TaskScope.MENU_ADJUSTMENT]]
    _, added = add_persistent(store, cat, str(data["description"]).strip(), scope)
    return dump(added), 201


@bp.put("/constraints/<constraint_id>")
def update_constraint(constraint_id):
    store, cat = load()
    data = body()
    try:
        cat = edit_persistent(
            store, cat, constraint_id,
            description=data.get("description"),
            scope=[TaskScope(s) for s in data["scope"]] if data.get("scope") else None,
            strictness=Strictness(data["strictness"]) if data.get("strictness") else None,
            active=data.get("active"),
        )
    except KeyError:
        raise NotFound(f"约束 {constraint_id} 不存在") from None
    return dump(next(c for c in cat.constraints.constraints if c.constraint_id == constraint_id))


@bp.delete("/constraints/<constraint_id>")
def delete_constraint(constraint_id):
    store, cat = load()
    try:
        remove_persistent(store, cat, constraint_id)
    except KeyError:
        raise NotFound(f"约束 {constraint_id} 不存在") from None
    return {"deleted": constraint_id}


@bp.post("/constraints/parse")
def parse_persistent():
    """Parse every persistent constraint that is still unparsed."""
    store, cat = load()
    cat = parse_unparsed_persistent(store, cat, llm(LLMTask.CONSTRAINT_PARSING))
    return [dump(c) for c in cat.constraints.constraints]


@bp.post("/task-constraints/parse")
def parse_task():
    """Parse constraints for one task; nothing is saved."""
    _, cat = load()
    data = body()
    task = TaskScope(data["task"])
    inputs = [
        TaskConstraintInput(str(i["description"]).strip(), tuple(i.get("overrides") or ()))
        for i in data["items"]
        if str(i.get("description", "")).strip()
    ]
    parsed = parse_constraints(llm(LLMTask.CONSTRAINT_PARSING), make_task_constraints(inputs, task), ReadOnlyCatalogue(cat))
    return [dump(c) for c in parsed]


@bp.post("/constraints/effective")
def effective():
    """The effective constraint set for a task, with blocking issues, before planning."""
    _, cat = load()
    data = body()
    task = TaskScope(data["task"])
    task_constraints = task_constraints_from_input(data.get("task_constraints", []), task, cat)
    return effective_view(build_effective_set(cat.constraints.constraints, task_constraints, task))

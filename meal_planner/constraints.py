"""Persistent and task-scoped constraints, and the effective set for one task.

Persistent constraints live in constraints.yaml and are edited only through the
functions here. Task constraints exist only in memory for one generation or
adjustment task and never change the persistent list. A task constraint replaces
a persistent one only through an explicit `overrides` entry; any other
contradiction is reported as a conflict for the user to resolve.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from .catalogue import Catalogue
from .constraint_parser import parse_constraints
from .constraint_types import DishCount, DishTypeCount
from .llm import LLMBackend
from .models import Constraint, ConstraintsFile
from .readonly import ReadOnlyCatalogue
from .store import DataStore
from .vocab import ConstraintSource, ParseStatus, Strictness, TaskScope

ALL_TASKS = (TaskScope.MENU_GENERATION, TaskScope.MENU_ADJUSTMENT)


# --- Persistent constraints ----------------------------------------------------


def add_persistent(
    store: DataStore, cat: Catalogue, description: str, scope: Sequence[TaskScope] = ALL_TASKS
) -> tuple[Catalogue, Constraint]:
    """Add a new, not yet parsed persistent constraint.

    Strictness starts as hard so that nothing is silently relaxed; parsing
    proposes the intended strictness and the user can change it.
    """
    existing = cat.constraints.constraints
    constraint = Constraint(
        constraint_id=_next_id("C", existing),
        description=description,
        scope=tuple(scope),
        strictness=Strictness.HARD,
        source=ConstraintSource.PERSISTENT,
    )
    cat = store.save_constraints(cat, ConstraintsFile(constraints=existing + (constraint,)))
    return cat, constraint


def edit_persistent(
    store: DataStore,
    cat: Catalogue,
    constraint_id: str,
    *,
    description: str | None = None,
    scope: Sequence[TaskScope] | None = None,
    strictness: Strictness | None = None,
    active: bool | None = None,
) -> Catalogue:
    """Change a persistent constraint. A new description discards the old interpretation."""
    current = _find(cat.constraints.constraints, constraint_id)
    changes = {k: v for k, v in dict(scope=scope, strictness=strictness, active=active).items() if v is not None}
    if description is not None and description != current.description:
        changes |= dict(description=description, parse_status=ParseStatus.UNPARSED, execution=None, parse_notes=None)
    updated = Constraint.model_validate(current.model_dump() | changes)
    return _save_replacing(store, cat, {constraint_id: updated})


def remove_persistent(store: DataStore, cat: Catalogue, constraint_id: str) -> Catalogue:
    _find(cat.constraints.constraints, constraint_id)
    kept = tuple(c for c in cat.constraints.constraints if c.constraint_id != constraint_id)
    return store.save_constraints(cat, ConstraintsFile(constraints=kept))


def parse_unparsed_persistent(store: DataStore, cat: Catalogue, llm: LLMBackend) -> Catalogue:
    """Parse every persistent constraint that is still `unparsed` and save the results."""
    todo = [c for c in cat.constraints.constraints if c.parse_status == ParseStatus.UNPARSED]
    parsed = parse_constraints(llm, todo, ReadOnlyCatalogue(cat))
    return _save_replacing(store, cat, {c.constraint_id: c for c in parsed})


def _save_replacing(store: DataStore, cat: Catalogue, replacements: dict[str, Constraint]) -> Catalogue:
    constraints = tuple(replacements.get(c.constraint_id, c) for c in cat.constraints.constraints)
    return store.save_constraints(cat, ConstraintsFile(constraints=constraints))


# --- Task constraints ----------------------------------------------------------


@dataclass(frozen=True)
class TaskConstraintInput:
    description: str
    overrides: tuple[str, ...] = ()  # persistent constraint IDs explicitly replaced for this task


def make_task_constraints(inputs: Sequence[TaskConstraintInput], task: TaskScope) -> list[Constraint]:
    """Create unparsed task constraints for one task; they are never saved to constraints.yaml."""
    return [
        Constraint(
            constraint_id=f"T{n:03d}",
            description=item.description,
            scope=(task,),
            strictness=Strictness.HARD,
            source=ConstraintSource.TASK,
            overrides=item.overrides,
        )
        for n, item in enumerate(inputs, start=1)
    ]


# --- Effective constraint set --------------------------------------------------


@dataclass(frozen=True)
class ConstraintIssue:
    """Something the user must resolve before the task can be planned."""

    kind: str  # conflict | unparsed | needs_clarification | unknown_override
    constraint_ids: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class EffectiveConstraintSet:
    task: TaskScope
    constraints: tuple[Constraint, ...]  # applied to this task
    overridden: tuple[Constraint, ...]  # persistent constraints explicitly replaced for this task
    issues: tuple[ConstraintIssue, ...] = field(default=())

    @property
    def ready(self) -> bool:
        return not self.issues

    @property
    def unsupported(self) -> tuple[Constraint, ...]:
        """Constraints that cannot be evaluated; planning may proceed but must report them."""
        return tuple(c for c in self.constraints if c.parse_status == ParseStatus.UNSUPPORTED)

    def status_of(self, constraint_id: str) -> ParseStatus:
        if any(i.kind == "conflict" and constraint_id in i.constraint_ids for i in self.issues):
            return ParseStatus.CONFLICT
        return _find(self.constraints + self.overridden, constraint_id).parse_status


def build_effective_set(
    persistent: Sequence[Constraint], task_constraints: Sequence[Constraint], task: TaskScope
) -> EffectiveConstraintSet:
    """Combine persistent constraints with one task's constraints. Inputs are not modified."""
    for c in task_constraints:
        if c.source != ConstraintSource.TASK or task not in c.scope:
            raise ValueError(f"{c.constraint_id} is not a task constraint for {task}")

    applicable = [c for c in persistent if c.active and task in c.scope]
    applicable_ids = {c.constraint_id for c in applicable}
    task_active = [c for c in task_constraints if c.active]

    issues: list[ConstraintIssue] = []
    override_ids: set[str] = set()
    for c in task_active:
        for target in c.overrides:
            if target in applicable_ids:
                override_ids.add(target)
            else:
                issues.append(ConstraintIssue("unknown_override", (c.constraint_id,), f"overrides '{target}', which is not an active persistent constraint for this task"))

    effective = [c for c in applicable if c.constraint_id not in override_ids] + task_active
    for c in effective:
        if c.parse_status == ParseStatus.UNPARSED:
            issues.append(ConstraintIssue("unparsed", (c.constraint_id,), "not parsed yet"))
        elif c.parse_status == ParseStatus.NEEDS_CLARIFICATION:
            issues.append(ConstraintIssue("needs_clarification", (c.constraint_id,), c.parse_notes or "needs clarification"))
    issues += find_conflicts(effective)

    return EffectiveConstraintSet(
        task=task,
        constraints=tuple(effective),
        overridden=tuple(c for c in applicable if c.constraint_id in override_ids),
        issues=tuple(issues),
    )


def find_conflicts(constraints: Sequence[Constraint]) -> list[ConstraintIssue]:
    """Deterministic checks for count rules that cannot all hold in the same dinner."""
    counts = [(c, c.execution) for c in constraints if isinstance(c.execution, DishCount)]
    type_counts = [(c, c.execution) for c in constraints if isinstance(c.execution, DishTypeCount)]
    issues = []

    for i, (a, ea) in enumerate(counts):
        for b, eb in counts[i + 1:]:
            if _disjoint(ea, eb):
                issues.append(_conflict((a, b), f"dish count {_range(ea)} vs {_range(eb)}"))
    for i, (a, ea) in enumerate(type_counts):
        for b, eb in type_counts[i + 1:]:
            if ea.dish_type == eb.dish_type and _disjoint(ea, eb):
                issues.append(_conflict((a, b), f"{ea.dish_type} count {_range(ea)} vs {_range(eb)}"))

    # The per-type minimums together must fit within every total-dish maximum.
    required = {}
    for c, e in type_counts:
        if e.min and e.min > required.get(e.dish_type, (None, 0))[1]:
            required[e.dish_type] = (c, e.min)
    total_min = sum(m for _, m in required.values())
    for c, e in counts:
        if e.max is not None and total_min > e.max:
            involved = (c, *(rc for rc, _ in required.values()))
            issues.append(_conflict(involved, f"dish types need at least {total_min} dishes, but at most {e.max} are allowed"))
    return issues


def _disjoint(a, b) -> bool:
    return (a.min is not None and b.max is not None and a.min > b.max) or (
        b.min is not None and a.max is not None and b.min > a.max
    )


def _range(e) -> str:
    return f"{e.min if e.min is not None else 0}-{e.max if e.max is not None else '∞'}"


def _conflict(constraints: Sequence[Constraint], what: str) -> ConstraintIssue:
    ids = tuple(c.constraint_id for c in constraints)
    return ConstraintIssue("conflict", ids, f"{', '.join(ids)} cannot all hold: {what}")


def _find(constraints: Sequence[Constraint], constraint_id: str) -> Constraint:
    for c in constraints:
        if c.constraint_id == constraint_id:
            return c
    raise KeyError(f"constraint '{constraint_id}' not found")


def _next_id(prefix: str, existing: Sequence[Constraint]) -> str:
    numbers = [int(c.constraint_id[1:]) for c in existing if c.constraint_id.startswith(prefix)]
    return f"{prefix}{max(numbers, default=0) + 1:03d}"

"""Batch review of pending candidate dishes: approve, edit or reject.

A batch is validated as a whole and written only if every decision is valid.
Approved dishes move from pending_dishes.yaml to dishes.yaml; rejected dishes
stay in pending_dishes.yaml with status `rejected` as a record and can never be
approved. Edits keep the dish's ID, source and creation time.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .catalogue import PENDING_DISHES_FILE, Catalogue, DataError, DataIssue
from .models import Dish, DishesFile
from .store import DataStore
from .vocab import ReviewStatus


class ReviewAction(StrEnum):
    APPROVE = "approve"  # optionally with an edited version
    EDIT = "edit"  # save changes, keep pending
    REJECT = "reject"


@dataclass(frozen=True)
class ReviewDecision:
    dish_id: str
    action: ReviewAction
    edited: Dish | None = None


def apply_review(store: DataStore, cat: Catalogue, decisions: Sequence[ReviewDecision]) -> Catalogue:
    pending = {d.dish_id: d for d in cat.pending_dishes.dishes}
    now = datetime.now().replace(microsecond=0)
    issues, updated, approved, seen = [], {}, [], set()

    for decision in decisions:
        loc = f"dishes[{decision.dish_id}]"
        current = pending.get(decision.dish_id)
        if current is None:
            issues.append(DataIssue(PENDING_DISHES_FILE, loc, "no such pending dish"))
            continue
        if current.review_status != ReviewStatus.PENDING:
            issues.append(DataIssue(PENDING_DISHES_FILE, loc, f"already {current.review_status}"))
            continue
        if decision.dish_id in seen:
            issues.append(DataIssue(PENDING_DISHES_FILE, loc, "more than one decision for this dish"))
            continue
        seen.add(decision.dish_id)
        if decision.edited is not None and decision.edited.dish_id != decision.dish_id:
            issues.append(DataIssue(PENDING_DISHES_FILE, loc, "an edit cannot change the dish_id"))
            continue

        base = current if decision.edited is None else _edited(current, decision.edited)
        if decision.action == ReviewAction.APPROVE:
            unmatched = [line.unmatched_name for line in base.ingredients if line.unmatched_name]
            if unmatched:
                issues.append(DataIssue(PENDING_DISHES_FILE, loc, f"resolve ingredients not in the catalogue first: {', '.join(unmatched)}"))
                continue
            approved.append(base.model_copy(update={"review_status": ReviewStatus.APPROVED, "updated_at": now}))
        elif decision.action == ReviewAction.EDIT:
            updated[decision.dish_id] = base.model_copy(update={"updated_at": now})
        else:
            updated[decision.dish_id] = current.model_copy(update={"review_status": ReviewStatus.REJECTED, "updated_at": now})

    if issues:
        raise DataError(issues)

    approved_ids = {d.dish_id for d in approved}
    remaining = tuple(updated.get(d.dish_id, d) for d in cat.pending_dishes.dishes if d.dish_id not in approved_ids)
    return store.save_dishes_and_pending(
        cat,
        DishesFile(dishes=cat.dishes.dishes + tuple(approved)),
        DishesFile(dishes=remaining),
    )


def _edited(current: Dish, edited: Dish) -> Dish:
    """The user's edited content, keeping identity and provenance from the stored candidate."""
    data = edited.model_dump() | {
        "dish_id": current.dish_id,
        "source": current.source,
        "source_url": current.source_url,
        "created_at": current.created_at,
        "review_status": ReviewStatus.PENDING,
    }
    return Dish.model_validate(data)

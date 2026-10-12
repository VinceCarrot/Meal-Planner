import pytest

from conftest import edit_yaml
from meal_planner.catalogue import DataError
from meal_planner.review import ReviewAction, ReviewDecision, apply_review
from meal_planner.vocab import DishSource, ReviewStatus

APPROVE, EDIT, REJECT = ReviewAction.APPROVE, ReviewAction.EDIT, ReviewAction.REJECT


def _pending(cat, dish_id):
    return next(d for d in cat.pending_dishes.dishes if d.dish_id == dish_id)


def test_batch_approve_and_reject(store):
    apply_review(store, store.load(), [ReviewDecision("dish_0101", APPROVE), ReviewDecision("dish_0102", REJECT)])

    cat = store.load()
    approved = next(d for d in cat.dishes.dishes if d.dish_id == "dish_0101")
    assert approved.review_status == "approved" and approved.updated_at is not None
    assert approved.source == "ai_generated"  # provenance is kept
    assert [(d.dish_id, d.review_status) for d in cat.pending_dishes.dishes] == [("dish_0102", "rejected")]


def test_edit_keeps_dish_pending(store):
    cat = store.load()
    edited = _pending(cat, "dish_0101").model_copy(update={"name_zh": "番茄豆腐汤（少油）"})
    apply_review(store, cat, [ReviewDecision("dish_0101", EDIT, edited)])

    dish = _pending(store.load(), "dish_0101")
    assert (dish.name_zh, dish.review_status) == ("番茄豆腐汤（少油）", "pending")


def test_edit_and_approve_resolving_unknown_ingredient(store):
    cat = store.load()
    candidate = _pending(cat, "dish_0102")
    resolved = candidate.ingredients[0], candidate.ingredients[1].model_copy(update={"ingredient_id": "ing_tofu", "unmatched_name": None})
    edited = candidate.model_copy(update={"ingredients": resolved, "source": DishSource.MANUAL, "review_status": ReviewStatus.APPROVED})

    apply_review(store, cat, [ReviewDecision("dish_0102", APPROVE, edited)])

    dish = next(d for d in store.load().dishes.dishes if d.dish_id == "dish_0102")
    assert dish.ingredients[1].ingredient_id == "ing_tofu"
    assert dish.source == "video_imported" and dish.source_url == candidate.source_url  # edits cannot rewrite provenance


@pytest.mark.parametrize(
    "decisions, message",
    [
        ([ReviewDecision("dish_0102", APPROVE)], "resolve ingredients not in the catalogue first: 香菇"),
        ([ReviewDecision("dish_0999", APPROVE)], "no such pending dish"),
        ([ReviewDecision("dish_0101", APPROVE), ReviewDecision("dish_0101", REJECT)], "more than one decision"),
    ],
)
def test_invalid_batches_write_nothing(store, data_dir, decisions, message):
    before = {f: (data_dir / f).read_bytes() for f in ("dishes.yaml", "pending_dishes.yaml")}
    with pytest.raises(DataError, match=message):
        apply_review(store, store.load(), [ReviewDecision("dish_0101", APPROVE)] + decisions)
    assert {f: (data_dir / f).read_bytes() for f in before} == before


def test_edit_cannot_change_id(store):
    cat = store.load()
    edited = _pending(cat, "dish_0101").model_copy(update={"dish_id": "dish_0001"})
    with pytest.raises(DataError, match="cannot change the dish_id"):
        apply_review(store, cat, [ReviewDecision("dish_0101", APPROVE, edited)])


def test_edit_with_unknown_ingredient_is_rejected(store):
    cat = store.load()
    candidate = _pending(cat, "dish_0101")
    bad_line = candidate.ingredients[0].model_copy(update={"ingredient_id": "ing_durian"})
    edited = candidate.model_copy(update={"ingredients": (bad_line,)})
    with pytest.raises(DataError, match="unknown ingredient_id 'ing_durian'"):
        apply_review(store, cat, [ReviewDecision("dish_0101", APPROVE, edited)])


def test_rejected_dishes_cannot_be_approved_later(store):
    apply_review(store, store.load(), [ReviewDecision("dish_0101", REJECT)])
    with pytest.raises(DataError, match="already rejected"):
        apply_review(store, store.load(), [ReviewDecision("dish_0101", APPROVE)])
    assert "dish_0101" not in store.load().approved_dish_ids


def test_interrupted_approval_is_detected_on_load(store, data_dir):
    # Simulate a crash after dishes.yaml was written but before pending_dishes.yaml was.
    cat = store.load()
    approved = _pending(cat, "dish_0101").model_copy(update={"review_status": ReviewStatus.APPROVED}).model_dump(mode="json")
    edit_yaml(data_dir / "dishes.yaml", lambda d: d["dishes"].append(approved))
    with pytest.raises(DataError, match="if an approval was interrupted"):
        store.load()

"""Approved dishes, candidate generation and batch review."""

from datetime import datetime

from flask import Blueprint

from ...candidates import CandidateRequest, generate_candidates, hard_exclusions, next_dish_number
from ...catalogue import DataError, DataIssue
from ...constraints import build_effective_set
from ...menus import task_constraints_from_input
from ...models import Dish, DishesFile
from ...review import ReviewAction, ReviewDecision, apply_review
from ...settings import LLMTask
from ...vocab import DishSource, DishType, ReviewStatus, TaskScope
from ..helpers import NotFound, body, llm, load
from ..serialize import dish_view

bp = Blueprint("dishes", __name__)

MAX_CANDIDATES_PER_REQUEST = 30


def _ingredients(cat):
    return {i.ingredient_id: i for i in cat.ingredients.ingredients}


@bp.get("/dishes")
def list_dishes():
    _, cat = load()
    ingredients = _ingredients(cat)
    return [dish_view(d, ingredients) for d in cat.dishes.dishes]


@bp.post("/dishes")
def add_dish():
    """A dish entered by the user is approved directly (source: manual)."""
    store, cat = load()
    dish = Dish.model_validate(body() | {
        "dish_id": f"dish_{next_dish_number(cat):04d}",
        "source": DishSource.MANUAL,
        "source_url": None,
        "review_status": ReviewStatus.APPROVED,
        "created_at": datetime.now().replace(microsecond=0),
        "updated_at": None,
    })
    cat = store.save_dishes(cat, DishesFile(dishes=cat.dishes.dishes + (dish,)))
    return dish_view(dish, _ingredients(cat)), 201


@bp.put("/dishes/<dish_id>")
def edit_dish(dish_id):
    store, cat = load()
    current = next((d for d in cat.dishes.dishes if d.dish_id == dish_id), None)
    if current is None:
        raise NotFound(f"菜品 {dish_id} 不存在")
    dish = Dish.model_validate(body() | {
        "dish_id": dish_id,
        "source": current.source,
        "source_url": current.source_url,
        "review_status": ReviewStatus.APPROVED,
        "created_at": current.created_at,
        "updated_at": datetime.now().replace(microsecond=0),
    })
    items = tuple(dish if d.dish_id == dish_id else d for d in cat.dishes.dishes)
    cat = store.save_dishes(cat, DishesFile(dishes=items))
    return dish_view(dish, _ingredients(cat))


@bp.get("/pending")
def list_pending():
    _, cat = load()
    ingredients = _ingredients(cat)
    dishes = cat.pending_dishes.dishes
    return {
        "pending": [dish_view(d, ingredients) for d in dishes if d.review_status == ReviewStatus.PENDING],
        "rejected": [dish_view(d, ingredients) for d in dishes if d.review_status == ReviewStatus.REJECTED],
    }


@bp.post("/review")
def review():
    store, cat = load()
    decisions = [
        ReviewDecision(
            dish_id=str(item["dish_id"]),
            action=ReviewAction(item["action"]),
            edited=Dish.model_validate(item["edited"]) if item.get("edited") else None,
        )
        for item in body()["decisions"]
    ]
    apply_review(store, cat, decisions)
    return {"applied": len(decisions)}


@bp.post("/candidates/generate")
def generate():
    """Generate candidates for catalogue gaps; hard exclusions of the current task are respected."""
    store, cat = load()
    data = body()
    task_constraints = task_constraints_from_input(data.get("task_constraints", []), TaskScope.MENU_GENERATION, cat)
    effective = build_effective_set(cat.constraints.constraints, task_constraints, TaskScope.MENU_GENERATION)
    requests = []
    for n, item in enumerate(data["requests"]):
        count = int(item["count"])
        if not 1 <= count <= MAX_CANDIDATES_PER_REQUEST:
            raise DataError([DataIssue("request", f"requests[{n}].count", f"必须在 1 到 {MAX_CANDIDATES_PER_REQUEST} 之间")])
        dish_type = DishType(item["dish_type"]) if item.get("dish_type") else None
        requests.append(CandidateRequest(dish_type, count, str(item.get("reason", ""))))

    backend = llm(LLMTask.DISH_GENERATION)
    added, rejected = [], []
    for request in requests:
        cat, result = generate_candidates(store, cat, backend, request, hard_exclusions(effective))
        added += result.added
        rejected += result.rejected
    ingredients = _ingredients(cat)
    return {"added": [dish_view(d, ingredients) for d in added], "rejected": [list(r) for r in rejected]}

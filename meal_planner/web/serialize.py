"""JSON views of domain objects for the Web UI."""

from ..calories import estimate_dish_calories
from ..candidates import requests_for_gaps
from ..catalogue import Catalogue
from ..constraints import EffectiveConstraintSet
from ..models import Dinner, Dish, MenuVersion
from ..planner import PlanResult
from ..settings import CandidateSettings


def dish_view(dish: Dish, ingredients: dict) -> dict:
    est = estimate_dish_calories(dish, ingredients)
    return dish.model_dump(mode="json") | {
        "calories": {
            "known_kcal": round(est.known_kcal),
            "complete": est.complete,
            "coverage": round(est.coverage, 2),
            "per_serving_kcal": round(est.per_serving_kcal) if est.per_serving_kcal is not None else None,
            "missing": [f"{m.ingredient}: {m.reason}" for m in est.missing],
        }
    }


def dinners_view(dinners, dishes: dict, calories=None) -> list[dict]:
    kcal = {c.date: c for c in calories or ()}
    return [
        {
            "date": d.date.isoformat(),
            "dishes": [_dish_ref(i, dishes) for i in d.dish_ids],
            "known_kcal": kcal[d.date].known_kcal if d.date in kcal else None,
            "kcal_complete": kcal[d.date].complete if d.date in kcal else None,
        }
        for d in dinners
    ]


def _dish_ref(dish_id: str, dishes: dict) -> dict:
    dish = dishes.get(dish_id)
    if dish is None:
        return {"dish_id": dish_id, "name_zh": f"（未知菜品 {dish_id}）", "dish_type": None}
    return {"dish_id": dish_id, "name_zh": dish.name_zh, "dish_type": dish.dish_type.value}


def effective_view(effective: EffectiveConstraintSet) -> dict:
    rows = [
        c.model_dump(mode="json") | {"status": effective.status_of(c.constraint_id).value, "applied": True}
        for c in effective.constraints
    ] + [c.model_dump(mode="json") | {"status": "overridden", "applied": False} for c in effective.overridden]
    return {
        "ready": effective.ready,
        "constraints": rows,
        "issues": [{"kind": i.kind, "constraint_ids": list(i.constraint_ids), "message": i.message} for i in effective.issues],
    }


def plan_view(result: PlanResult, dishes: dict, effective: EffectiveConstraintSet, candidates: CandidateSettings) -> dict:
    report = result.report
    suggested = requests_for_gaps(result.gaps, candidates)
    return {
        "status": result.status.value,
        "messages": list(result.messages),
        "gaps": [
            {
                "constraint_id": g.constraint_id,
                "dish_type": g.dish_type.value if g.dish_type else None,
                "additional_dishes_needed": g.additional_dishes_needed,
                "suggested_count": request.count,
                "description": g.describe(),
            }
            for g, request in zip(result.gaps, suggested)
        ],
        "relaxation_candidates": list(result.relaxation_candidates),
        "dinners": dinners_view(result.dinners or (), dishes, report.calories if report else None),
        "report": report.model_dump(mode="json") if report else None,
        "penalty_total": report.penalty_total if report else None,
        "effective": effective_view(effective),
        "solver": {"status": result.solver.status, "seconds": round(result.solver.wall_time_s, 1)} if result.solver else None,
        "repair": {"steps": result.repair.steps, "penalty_before": result.repair.penalty_before,
                   "penalty_after": result.repair.penalty_after} if result.repair else None,
    }


def menu_view(menu: MenuVersion, cat: Catalogue, versions: list[int]) -> dict:
    """A stored menu version; calories come from the report saved with it."""
    dishes = {d.dish_id: d for d in cat.dishes.dishes}
    kcal = {c["date"]: c for c in (menu.validation_report or {}).get("calories", [])}
    view = menu.model_dump(mode="json")
    view["dinners"] = [
        d | {"known_kcal": kcal.get(d["date"], {}).get("known_kcal"), "kcal_complete": kcal.get(d["date"], {}).get("complete")}
        for d in dinners_view(menu.dinners, dishes)
    ]
    view["versions"] = versions
    return view


def dinners_from_input(raw: list[dict]) -> list[Dinner]:
    return [Dinner.model_validate(d) for d in raw]


SCOPE_ORDER = ("dish", "dinner", "week", "menu")


def changes_view(changes, dishes: dict) -> list[dict]:
    return [
        {"date": c.date.isoformat(), "removed": [_dish_ref(i, dishes) for i in c.removed], "added": [_dish_ref(i, dishes) for i in c.added]}
        for c in changes
    ]


def proposal_view(proposal, dishes: dict, effective: EffectiveConstraintSet) -> dict:
    report = proposal.report
    return {
        "status": proposal.status.value,
        "scope": proposal.scope,
        "attempts": [{"scope": a.scope, "status": a.status.value, "message": a.message} for a in proposal.attempts],
        "dinners": dinners_view(proposal.dinners or (), dishes, report.calories if report else None),
        "changes": changes_view(proposal.changes, dishes),
        "report": report.model_dump(mode="json") if report else None,
        "penalty_total": report.penalty_total if report else None,
        "effective": effective_view(effective),
    }

"""Planner benchmark on synthetic catalogues (Phase 4).

Usage: python benchmarks/bench_planner.py [--threshold T] [num_dishes ...]
Reports solve time, plan status, penalties before/after repair, repeatability
and the dish-similarity distribution of the synthetic catalogue.
"""

import statistics
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from synthetic import synthetic_catalogue  # noqa: E402

from meal_planner.constraints import build_effective_set  # noqa: E402
from meal_planner.models import Constraint  # noqa: E402
from meal_planner.plan_context import make_context  # noqa: E402
from meal_planner.planner import plan_menu  # noqa: E402
from meal_planner.settings import Settings  # noqa: E402
from meal_planner.vocab import TaskScope  # noqa: E402

START = date(2026, 10, 19)


def typical_constraints() -> list[Constraint]:
    rules = [
        ("每顿4个菜（含汤）", "hard", {"type": "dish_count", "min": 4, "max": 4}),
        ("每顿一个汤", "hard", {"type": "dish_type_count", "dish_type": "soup", "min": 1, "max": 1}),
        ("每顿至少一个大荤", "hard", {"type": "dish_type_count", "dish_type": "meat", "min": 1}),
        ("每顿至少一个素菜", "hard", {"type": "dish_type_count", "dish_type": "vegetarian", "min": 1}),
        ("两周内不重复", "hard", {"type": "exact_repeat_window", "weeks": 2}),
        ("一周内菜别太像", "soft", {"type": "dish_similarity", "window_weeks": 1}),
        ("一周内整餐别太像", "soft", {"type": "meal_similarity", "window_weeks": 1}),
    ]
    return [
        Constraint(constraint_id=f"C{n:03d}", description=d, scope=["menu_generation"], strictness=s,
                   source="persistent", execution=e, parse_status="executable")
        for n, (d, s, e) in enumerate(rules, start=1)
    ]


def similarity_distribution(ctx) -> str:
    ids = sorted(ctx.dishes)
    scores = sorted(s for n, a in enumerate(ids) for b in ids[n + 1:] if (s := ctx.similarity(a, b)) is not None)
    q = statistics.quantiles(scores, n=100)
    above = sum(s > 0.5 for s in scores) / len(scores)
    return f"pairs={len(scores)} p50={q[49]:.2f} p90={q[89]:.2f} p99={q[98]:.2f} share>0.5={above:.1%}"


def run(num_dishes: int, settings: Settings) -> None:
    catalogue = synthetic_catalogue(num_dishes)
    effective = build_effective_set(typical_constraints(), [], TaskScope.MENU_GENERATION)
    ctx = make_context(catalogue, settings, START)
    t = time.monotonic()
    print(f"\n== {num_dishes} dishes ==  similarity: {similarity_distribution(ctx)} ({time.monotonic() - t:.1f}s)")

    first = None
    for attempt in (1, 2):
        ctx = make_context(catalogue, settings, START)
        t = time.monotonic()
        result = plan_menu(ctx, effective)
        total = time.monotonic() - t
        s, r = result.solver, result.repair
        repair = f"repair: steps={r.steps} penalty {r.penalty_before}->{r.penalty_after} ({r.seconds:.1f}s)" if r else "no repair"
        print(f"run {attempt}: status={result.status} solver={s.status} vars={s.num_variables} "
              f"solve={s.wall_time_s:.1f}s objective={s.objective} {repair} total={total:.1f}s")
        if result.report:
            print("   " + "; ".join(f"{x.constraint_id}={x.status}" + (f"({x.penalty})" if x.penalty else "") for x in result.report.results))
        if first is None:
            first = result.dinners
        else:
            print(f"   repeatable: {first == result.dinners}")


if __name__ == "__main__":
    args = sys.argv[1:]
    planner = {}
    if args[:1] == ["--threshold"]:
        t = float(args[1])
        planner = {"default_dish_similarity_threshold": t, "default_meal_similarity_threshold": t}
        args = args[2:]
    settings = Settings(planner=Settings().planner.model_copy(update=planner))
    print(f"thresholds: dish={settings.planner.default_dish_similarity_threshold} meal={settings.planner.default_meal_similarity_threshold}")
    for n in [int(a) for a in args] or [100, 200, 300]:
        run(n, settings)

import json
import re
from datetime import date, datetime

import pytest

from fakes import FakeLLM
from meal_planner.demo import synthetic_catalogue
from meal_planner.models import Diner, Dinner, MenuVersion, plan_dates
from meal_planner.pdf_export import ExportError, build_menu_pdf, dishes_in_order
from meal_planner.translation import BATCH_SIZE, TranslationOutput, load_translations, save_translations, translate_dishes

START = date(2026, 10, 19)


def fake_translator(prompt: str) -> dict:
    """Translates by structure: keeps line/step counts and every number of each step."""
    recipes = json.loads(prompt.split("\n", 1)[1])
    return {"dishes": [
        {
            "dish_id": r["dish_id"],
            "name_en": f"Dish {r['dish_id']}",
            "ingredients": [{"name": l["english_name"] or "item", "unit": "g" if l["unit"] else None, "note": "to taste" if l["note"] else None}
                            for l in r["ingredients"]],
            "steps": [f"Step {' '.join(re.findall(r'[0-9]+', s))}".strip() for s in r["steps"]],
            "uncertainty_notes": "Check salt." if r["uncertainty_notes"] else None,
        }
        for r in recipes
    ]}


@pytest.fixture(scope="module")
def cat():
    return synthetic_catalogue(100)


@pytest.fixture
def dishes(cat):
    return {d.dish_id: d for d in cat.dishes.dishes}


@pytest.fixture
def ingredients(cat):
    return {i.ingredient_id: i for i in cat.ingredients.ingredients}


def _dish(dishes, dish_id, **changes):
    return dishes[dish_id].model_copy(update=changes)


def test_translations_are_cached_and_redone_only_when_the_recipe_changes(tmp_path, dishes, ingredients):
    batch = [_dish(dishes, f"dish_{n:04d}", steps=("炒 2 分钟", "出锅")) for n in range(1, 21)]
    llm = FakeLLM(fake_translator)

    cache, failed = translate_dishes(llm, batch, ingredients, {})
    assert failed == {} and len(cache) == 20
    assert len(llm.calls) == -(-20 // BATCH_SIZE)
    save_translations(tmp_path, cache)

    llm.calls.clear()
    cache = load_translations(tmp_path)
    cache, _ = translate_dishes(llm, batch, ingredients, cache)
    assert llm.calls == []  # nothing changed

    edited = [batch[0].model_copy(update={"steps": ("炒 3 分钟",)})] + batch[1:]
    cache, _ = translate_dishes(llm, edited, ingredients, cache)
    assert len(llm.calls) == 1 and '"dish_0001"' in llm.calls[0]["prompt"] and '"dish_0002"' not in llm.calls[0]["prompt"]
    assert cache["dish_0001"].steps == ("Step 3",)


def test_model_output_has_no_quantities():
    # Quantities are rendered from recipe data; the model is never asked for them.
    assert "quantity" not in json.dumps(TranslationOutput.model_json_schema())


def _broken(change):
    def respond(prompt):
        out = fake_translator(prompt)
        change(out["dishes"][0])
        return out
    return respond


@pytest.mark.parametrize(
    "change, error",
    [
        (lambda d: d["steps"].pop(), "steps"),
        (lambda d: d["ingredients"].append({"name": "extra"}), "ingredient lines"),
        (lambda d: d.update(name_en="番茄 Tomato"), "Chinese characters"),
        (lambda d: d.update(name_en=" "), "empty names"),
        (lambda d: d.update(price=3), "invalid translation"),
    ],
)
def test_invalid_translations_are_refused(dishes, ingredients, change, error):
    dish = _dish(dishes, "dish_0001", steps=("炒 2 分钟", "出锅"))
    cache, failed = translate_dishes(FakeLLM(_broken(change)), [dish], ingredients, {})
    assert "dish_0001" not in cache and error in failed["dish_0001"]


def test_missing_numbers_produce_a_warning(dishes, ingredients):
    dish = _dish(dishes, "dish_0001", steps=("小火炖 40 分钟，180 度",))
    cache, failed = translate_dishes(FakeLLM(_broken(lambda d: d.update(steps=["Simmer for 40 minutes."]))), [dish], ingredients, {})
    assert failed == {}
    assert cache["dish_0001"].warnings == ("step 1: number(s) 180 not found in the translation",)


def test_dish_without_reply_fails_alone(dishes, ingredients):
    batch = [dishes["dish_0001"], dishes["dish_0002"]]
    cache, failed = translate_dishes(FakeLLM(lambda p: {"dishes": fake_translator(p)["dishes"][:1]}), batch, ingredients, {})
    assert set(cache) == {"dish_0001"} and failed == {"dish_0002": "no translation returned"}


# --- PDF -------------------------------------------------------------------------------------


def _menu(dishes):
    ids = sorted(dishes)
    return MenuVersion(menu_id="M001", version=2, start_date=START, diners=[Diner(description="x", count=1)],
                       dinners=[Dinner(date=d, dish_ids=tuple(ids[i * 4:i * 4 + 4])) for i, d in enumerate(plan_dates(START))],
                       created_at=datetime(2026, 10, 12))


def test_pdf_contains_every_recipe_with_data_quantities(dishes, ingredients):
    menu = _menu(dishes)
    order = dishes_in_order(menu)
    translations, _ = translate_dishes(FakeLLM(fake_translator), [dishes[k] for k in order], ingredients, {})

    pdf = build_menu_pdf(menu, dishes, translations, compress=False)

    assert pdf.startswith(b"%PDF")
    for dish_id in order:
        assert f"Dish {dish_id}".encode() in pdf
    first_line = dishes[order[0]].ingredients[0]
    assert f"{int(first_line.quantity)} g".encode() in pdf
    assert b"menu M001, version 2" in pdf


def test_long_steps_wrap_across_pages(dishes, ingredients):
    menu = _menu(dishes)
    order = dishes_in_order(menu)
    long_dishes = {k: d.model_copy(update={"steps": ("把食材洗净切好，" * 200,)}) if k in order else d for k, d in dishes.items()}
    translations, _ = translate_dishes(FakeLLM(_broken(lambda d: None)), [long_dishes[k] for k in order], ingredients, {})
    translations = {k: t.model_copy(update={"steps": ("Wash and cut the ingredients. " * 200,)}) for k, t in translations.items()}

    pdf = build_menu_pdf(menu, long_dishes, translations, compress=False)

    assert len(re.findall(rb"/Type /Page[^s]", pdf)) > len(order)


def test_pdf_requires_every_translation(dishes):
    with pytest.raises(ExportError, match="missing translations"):
        build_menu_pdf(_menu(dishes), dishes, {})

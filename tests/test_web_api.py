"""JSON API tests (Flask test client, fake LLM, synthetic data in a temporary directory)."""

import pytest

from fakes import FakeLLM, result
from meal_planner.demo import synthetic_catalogue, write_catalogue
from meal_planner.llm import LLMError
from meal_planner.models import Constraint, ConstraintsFile, Feedback, PreferencesFile
from meal_planner.settings import Settings, save_settings
from meal_planner.web import create_app
from meal_planner.yaml_io import write_yaml_atomic

START = "2026-10-19"
RULES = [
    ("每顿4个菜", {"type": "dish_count", "min": 4, "max": 4}),
    ("每顿一个汤", {"type": "dish_type_count", "dish_type": "soup", "min": 1, "max": 1}),
    ("两周内不重复", {"type": "exact_repeat_window", "weeks": 2}),
]


@pytest.fixture
def data_dir(tmp_path):
    data = tmp_path / "data"
    write_catalogue(synthetic_catalogue(100), data)
    constraints = [
        Constraint(constraint_id=f"C{n:03d}", description=d, scope=["menu_generation", "menu_adjustment"],
                   strictness="hard", source="persistent", execution=e, parse_status="executable")
        for n, (d, e) in enumerate(RULES, start=1)
    ]
    write_yaml_atomic(data / "constraints.yaml", ConstraintsFile(constraints=constraints).model_dump(mode="json"))
    save_settings(data, Settings(planner=Settings().planner.model_copy(update={"time_limit_s": 10})))
    return data


@pytest.fixture
def llm():
    return FakeLLM()


@pytest.fixture
def client(data_dir, llm):
    return create_app(data_dir, llm_factory=lambda settings, task: llm).test_client()


def ok(response, status=200):
    assert response.status_code == status, response.get_json()
    return response.get_json()


def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200 and "<html" in response.get_data(as_text=True)


def test_writes_require_json(client, data_dir):
    before = (data_dir / "constraints.yaml").read_bytes()
    response = client.post("/api/constraints", data={"description": "x"})
    assert response.status_code == 415
    assert (data_dir / "constraints.yaml").read_bytes() == before


# --- Ingredients ---------------------------------------------------------------


def test_ingredient_crud(client):
    new = {"ingredient_id": "ing_okra", "name_zh": "秋葵", "category": "vegetable", "kcal_per_100g": 33}
    ok(client.post("/api/ingredients", json=new), 201)
    duplicate = client.post("/api/ingredients", json=new)
    assert duplicate.status_code == 400 and "duplicate ingredient_id 'ing_okra'" in duplicate.get_json()["issues"][0]

    edited = ok(client.put("/api/ingredients/ing_okra", json=new | {"notes": "嫩的好吃", "ingredient_id": "ing_x"}))
    assert edited["ingredient_id"] == "ing_okra" and edited["notes"] == "嫩的好吃"
    ok(client.delete("/api/ingredients/ing_okra"))
    assert client.delete("/api/ingredients/ing_okra").status_code == 404


def test_ingredient_suggestion_writes_nothing(client, llm, data_dir):
    before = (data_dir / "ingredients.yaml").read_bytes()
    llm.response = {"name_en": "okra", "aliases": ["羊角豆"], "category": "vegetable", "kcal_per_100g": 33,
                    "grams_per_unit": [{"unit": "根", "grams": 12}], "notes": None}

    suggested = ok(client.post("/api/ingredients/suggest", json={"name_zh": "秋葵"}))

    assert suggested["ingredient"]["ingredient_id"] == "ing_okra" and suggested["warnings"] == []
    assert (data_dir / "ingredients.yaml").read_bytes() == before
    ok(client.post("/api/ingredients", json=suggested["ingredient"]), 201)


def test_dish_suggestion_writes_nothing(client, llm, data_dir):
    files = ["dishes.yaml", "pending_dishes.yaml", "ingredients.yaml"]
    before = [(data_dir / f).read_bytes() for f in files]
    llm.response = {
        "name_en": "Tomato and egg", "dish_type": "vegetarian", "servings": 3,
        "ingredients": [{"name": "番茄", "quantity": 300, "unit": "g", "main": True},
                        {"name": "鸡蛋", "ingredient_id": "ing_egg", "quantity": 3, "unit": "个"}],
        "steps": ["鸡蛋打散", "番茄切块后与鸡蛋同炒"], "cooking_method": "stir_fry", "flavours": ["sweet_sour"],
    }

    suggested = ok(client.post("/api/dishes/suggest", json={"name_zh": "番茄炒蛋", "steps_text": "炒番茄和鸡蛋"}))

    assert suggested["steps_source"] == "parsed" and suggested["sources"] == [] and suggested["warnings"] == []
    assert [(data_dir / f).read_bytes() for f in files] == before
    created = ok(client.post("/api/dishes", json=suggested["dish"]), 201)
    assert created["source"] == "manual" and created["style"]["main_ingredients"] == ["ing_tomato"]


def test_dish_suggestion_with_web_search_keeps_reference_link(client, llm):
    llm.response = {
        "dish_type": "vegetarian", "ingredients": [{"name": "番茄", "quantity": 300, "unit": "g"}],
        "steps": ["番茄切块", "炒软"], "sources": ["https://recipes.example/1"],
    }
    suggested = ok(client.post("/api/dishes/suggest", json={"name_zh": "炒番茄", "web_search": True}))

    assert llm.calls[-1]["web_search"] is True and suggested["steps_source"] == "searched"
    assert suggested["sources"] == ["https://recipes.example/1"]
    created = ok(client.post("/api/dishes", json=suggested["dish"]), 201)
    assert created["source_url"] == "https://recipes.example/1"
    bad = suggested["dish"] | {"name_zh": "炒番茄2", "source_url": "javascript:alert(1)"}
    assert client.post("/api/dishes", json=bad).status_code == 400


def test_dish_suggestion_errors(client, llm):
    assert client.post("/api/dishes/suggest", json={"name_zh": " "}).status_code == 400
    llm.response = {"dish_type": "vegetarian"}
    assert client.post("/api/dishes/suggest", json={"name_zh": "番茄炒蛋"}).status_code == 502


def test_ingredient_suggestion_errors(client, llm):
    assert client.post("/api/ingredients/suggest", json={"name_zh": " "}).status_code == 400
    assert client.post("/api/ingredients/suggest", json={"name_zh": "秋葵", "ingredient_id": "ing_x"}).status_code == 404
    llm.response = {"name_en": "okra"}
    assert client.post("/api/ingredients/suggest", json={"name_zh": "秋葵"}).status_code == 502


def test_ingredient_in_use_cannot_be_deleted(client):
    response = client.delete("/api/ingredients/ing_tofu")
    assert response.status_code == 400 and any("ing_tofu" in i for i in response.get_json()["issues"])


# --- Dishes, candidates and review ------------------------------------------------


DISH = {
    "name_zh": "清炒秋葵", "dish_type": "vegetarian", "servings": 2,
    "ingredients": [{"ingredient_id": "ing_cabbage", "quantity": 300, "unit": "g"}],
    "steps": ["洗净", "清炒"], "style": {"main_ingredients": ["ing_cabbage"], "cooking_method": "stir_fry"},
}


def test_manual_dish_is_approved_and_server_sets_provenance(client):
    created = ok(client.post("/api/dishes", json=DISH | {"source": "ai_generated", "review_status": "pending"}), 201)
    assert (created["dish_id"], created["source"], created["review_status"]) == ("dish_0101", "manual", "approved")
    assert created["calories"]["known_kcal"] > 0

    edited = ok(client.put("/api/dishes/dish_0101", json=DISH | {"name_zh": "清炒包菜"}))
    assert edited["name_zh"] == "清炒包菜" and edited["source"] == "manual" and edited["updated_at"]


def test_dish_with_unknown_ingredient_is_refused(client):
    bad = DISH | {"ingredients": [{"ingredient_id": "ing_durian", "quantity": 1, "unit": "g"}]}
    response = client.post("/api/dishes", json=bad)
    assert response.status_code == 400 and "ing_durian" in response.get_json()["issues"][0]


def test_generate_then_review_candidates(client, llm):
    draft = DISH | {"name_zh": "白菜豆腐汤", "dish_type": "soup", "style": {"main_ingredients": ["ing_cabbage"], "cooking_method": "boil", "flavours": ["light"]}}
    llm.response = {"dishes": [draft, draft | {"name_zh": "怪汤", "dish_type": "meat"}]}

    generated = ok(client.post("/api/candidates/generate", json={"requests": [{"dish_type": "soup", "count": 2, "reason": "缺汤"}]}))
    assert [d["name_zh"] for d in generated["added"]] == ["白菜豆腐汤"]
    assert generated["rejected"][0][0] == "怪汤"

    pending = ok(client.get("/api/pending"))["pending"]
    ok(client.post("/api/review", json={"decisions": [{"dish_id": pending[0]["dish_id"], "action": "approve"}]}))
    assert pending[0]["dish_id"] in {d["dish_id"] for d in ok(client.get("/api/dishes"))}


def test_candidate_count_is_limited(client):
    response = client.post("/api/candidates/generate", json={"requests": [{"dish_type": "soup", "count": 500}]})
    assert response.status_code == 400


def test_llm_failure_is_reported(client, llm):
    llm.error = LLMError("Claude Code CLI not found")
    response = client.post("/api/candidates/generate", json={"requests": [{"dish_type": "soup", "count": 2}]})
    assert response.status_code == 502 and "not found" in response.get_json()["issues"][0]


# --- Constraints ---------------------------------------------------------------------


def test_persistent_constraint_lifecycle(client, llm):
    added = ok(client.post("/api/constraints", json={"description": "每顿至少一个素菜"}), 201)
    assert (added["constraint_id"], added["parse_status"]) == ("C004", "unparsed")

    llm.response = {"results": [result("C004", execution={"type": "dish_type_count", "dish_type": "vegetarian", "min": 1})]}
    parsed = ok(client.post("/api/constraints/parse"))
    assert parsed[-1]["parse_status"] == "executable"

    edited = ok(client.put("/api/constraints/C004", json={"strictness": "soft", "active": False}))
    assert (edited["strictness"], edited["active"]) == ("soft", False)
    ok(client.delete("/api/constraints/C004"))
    assert client.put("/api/constraints/C004", json={"active": True}).status_code == 404


def test_selected_constraints_can_be_parsed_again(client, llm):
    before = {c["constraint_id"]: c for c in ok(client.get("/api/constraints"))}
    weekday_soup = {"type": "dish_type_count", "dish_type": "soup", "min": 1, "max": 1, "weekdays": [1, 3, 5]}
    llm.response = {"results": [result("C002", execution=weekday_soup)]}

    parsed = {c["constraint_id"]: c for c in ok(client.post("/api/constraints/parse", json={"constraint_ids": ["C002"]}))}

    assert "C002" in llm.calls[-1]["prompt"] and "C001" not in llm.calls[-1]["prompt"]
    assert parsed["C002"]["execution"]["weekdays"] == [1, 3, 5]
    assert parsed["C001"] == before["C001"]
    assert client.post("/api/constraints/parse", json={"constraint_ids": ["C999"]}).status_code == 404
    assert client.post("/api/constraints/parse", json={"constraint_ids": "C002"}).status_code == 400


def test_task_constraints_are_parsed_but_not_saved(client, llm, data_dir):
    before = (data_dir / "constraints.yaml").read_bytes()
    llm.response = {"results": [result("T001", execution={"type": "dish_type_count", "dish_type": "soup", "min": 2, "max": 2})]}

    parsed = ok(client.post("/api/task-constraints/parse", json={"task": "menu_generation", "items": [{"description": "这次两个汤"}]}))

    assert parsed[0]["constraint_id"] == "T001" and parsed[0]["scope"] == ["menu_generation"]
    assert (data_dir / "constraints.yaml").read_bytes() == before
    effective = ok(client.post("/api/constraints/effective", json={"task": "menu_generation", "task_constraints": parsed}))
    assert not effective["ready"] and effective["issues"][0]["kind"] == "conflict"

    with_override = parsed[0] | {"overrides": ["C002"]}
    effective = ok(client.post("/api/constraints/effective", json={"task": "menu_generation", "task_constraints": [with_override]}))
    assert effective["ready"]
    assert {c["constraint_id"]: c["status"] for c in effective["constraints"]}["C002"] == "overridden"


def test_task_constraint_for_the_wrong_task_is_refused(client):
    adjustment_only = Constraint(constraint_id="T001", description="x", scope=["menu_adjustment"], strictness="hard",
                                 source="task").model_dump(mode="json")
    response = client.post("/api/constraints/effective", json={"task": "menu_generation", "task_constraints": [adjustment_only]})
    assert response.status_code == 400


# --- Menus ---------------------------------------------------------------------------


DINERS = [{"description": "成年女性", "count": 3}, {"description": "6岁儿童", "count": 1}]


def test_plan_save_and_reload_menu(client):
    planned = ok(client.post("/api/menus/plan", json={"start_date": START}))
    assert planned["status"] == "feasible" and len(planned["dinners"]) == 20
    assert all(r["status"] == "passed" for r in planned["report"]["results"])

    dinners = [{"date": d["date"], "dish_ids": [x["dish_id"] for x in d["dishes"]]} for d in planned["dinners"]]
    saved = ok(client.post("/api/menus", json={"start_date": START, "diners": DINERS, "dinners": dinners, "change_note": "第一版"}), 201)
    assert saved == {"menu_id": "M001", "version": 1, "status": "feasible"}

    [row] = ok(client.get("/api/menus"))
    assert row["menu_id"] == "M001" and row["status"] == "feasible"
    menu = ok(client.get("/api/menus/M001?version=1"))
    assert menu["dinners"][0]["dishes"][0]["name_zh"] and menu["dinners"][0]["known_kcal"] is not None
    assert client.get("/api/menus/M001?version=9").status_code == 404


def test_saved_menu_is_revalidated_by_the_server(client):
    planned = ok(client.post("/api/menus/plan", json={"start_date": START}))
    first = planned["dinners"][0]["dishes"][0]["dish_id"]
    tampered = [{"date": d["date"], "dish_ids": [first]} for d in planned["dinners"]]  # 1 dish per dinner, repeated

    saved = ok(client.post("/api/menus", json={"start_date": START, "diners": DINERS, "dinners": tampered}), 201)

    assert saved["status"] == "best_effort"
    menu = ok(client.get(f"/api/menus/{saved['menu_id']}"))
    assert menu["validation_report"]["status"] == "best_effort"


def test_unknown_dish_cannot_be_saved(client):
    planned = ok(client.post("/api/menus/plan", json={"start_date": START}))
    dinners = [{"date": d["date"], "dish_ids": ["dish_9999"]} for d in planned["dinners"]]
    response = client.post("/api/menus", json={"start_date": START, "diners": DINERS, "dinners": dinners})
    assert response.status_code == 400


@pytest.mark.parametrize("start", ["2026-10-20", "next monday"])
def test_start_date_must_be_a_monday(client, start):
    response = client.post("/api/menus/plan", json={"start_date": start})
    assert response.status_code == 400


def test_blocked_plan_explains_why(client):
    unparsed = Constraint(constraint_id="T001", description="少点油", scope=["menu_generation"], strictness="hard", source="task")
    planned = ok(client.post("/api/menus/plan", json={"start_date": START, "task_constraints": [unparsed.model_dump(mode="json")]}))
    assert planned["status"] == "blocked" and "not parsed" in planned["messages"][0]


def test_default_diners(client):
    ok(client.put("/api/preferences/diners", json={"diners": DINERS}))
    assert ok(client.get("/api/preferences"))["default_diners"] == DINERS
    assert client.put("/api/preferences/diners", json={"diners": [{"description": "x", "count": 0}]}).status_code == 400


# --- Settings ------------------------------------------------------------------------


def test_settings_round_trip_and_validation(client):
    current = ok(client.get("/api/settings"))
    current["models"]["constraint_parsing"] = "opus"
    assert ok(client.put("/api/settings", json=current))["models"]["constraint_parsing"] == "opus"
    current["similarity_weights"]["cuisine"] = -1
    assert client.put("/api/settings", json=current).status_code == 400


def test_vocab(client):
    vocab = ok(client.get("/api/vocab"))
    assert vocab["dish_types"] == ["vegetarian", "mixed", "meat", "soup"]


# --- Menu adjustment -------------------------------------------------------------------


def _saved_menu(client):
    planned = ok(client.post("/api/menus/plan", json={"start_date": START}))
    dinners = [{"date": d["date"], "dish_ids": [x["dish_id"] for x in d["dishes"]]} for d in planned["dinners"]]
    ok(client.post("/api/menus", json={"start_date": START, "diners": DINERS, "dinners": dinners}), 201)
    return dinners


def test_propose_and_save_adjustment(client):
    dinners = _saved_menu(client)
    target = {"date": dinners[3]["date"], "dish_id": dinners[3]["dish_ids"][1]}

    proposal = ok(client.post("/api/menus/M001/adjust/propose", json={"version": 1, **target}))
    assert proposal["status"] == "feasible" and proposal["scope"] == "dish"
    [change] = proposal["changes"]
    assert change["date"] == target["date"] and [d["dish_id"] for d in change["removed"]] == [target["dish_id"]]

    new_dinners = [{"date": d["date"], "dish_ids": [x["dish_id"] for x in d["dishes"]]} for d in proposal["dinners"]]
    saved = ok(client.post("/api/menus/M001/adjust/save", json={
        "version": 1, "dinners": new_dinners, "change_note": "换掉不喜欢的菜",
        "feedback": {"dish_id": target["dish_id"], "scope": "future_menus", "note": "太油"},
    }), 201)
    assert saved == {"menu_id": "M001", "version": 2, "status": "feasible"}

    v2 = ok(client.get("/api/menus/M001"))
    assert v2["based_on_version"] == 1 and v2["changes"][0]["date"] == target["date"]
    assert ok(client.get("/api/menus/M001?version=1"))["dinners"][3]["dishes"][1]["dish_id"] == target["dish_id"]
    feedback = ok(client.get("/api/preferences"))["feedback"]
    assert [(f["dish_id"], f["scope"], f["note"]) for f in feedback] == [(target["dish_id"], "future_menus", "太油")]


def test_adjustment_requires_a_reason_and_a_real_target(client):
    dinners = _saved_menu(client)
    assert client.post("/api/menus/M001/adjust/propose", json={"date": dinners[0]["date"], "dish_id": "dish_9999"}).status_code == 400
    response = client.post("/api/menus/M001/adjust/save", json={"version": 1, "dinners": dinners, "change_note": " "})
    assert response.status_code == 400 and "原因" in response.get_json()["issues"][0]
    assert client.post("/api/menus/M404/adjust/propose", json={"date": START, "dish_id": "dish_0001"}).status_code == 404


# --- Video import ----------------------------------------------------------------------


def test_video_import_endpoint(data_dir, llm):
    from meal_planner.video_import import VideoText

    class Source:
        def fetch(self, ref):
            return VideoText("白菜豆腐汤", "", "白菜切段，豆腐切块，加水煮开……", "subtitles", "zh")

    client = create_app(data_dir, llm_factory=lambda s, task: llm, video_source=Source()).test_client()
    llm.response = {"found_recipe": True, "reason": "", "recipe": {
        "name_zh": "白菜豆腐汤", "dish_type": "soup", "ingredients": [{"name": "包菜", "quantity": 200, "unit": "g"}, {"name": "虾皮"}],
        "steps": ["煮开"], "uncertainty_notes": "没有说明时间"}}

    result = ok(client.post("/api/videos/import", json={"url": "https://youtu.be/dQw4w9WgXcQ"}), 201)

    assert result["text_source"] == "subtitles" and result["dish"]["review_status"] == "pending"
    assert [l["unmatched_name"] for l in result["dish"]["ingredients"]] == [None, "虾皮"]
    bad = client.post("/api/videos/import", json={"url": "https://vimeo.com/1"})
    assert bad.status_code == 422 and "只支持" in bad.get_json()["issues"][0]


# --- English PDF export ------------------------------------------------------------------


def test_translate_then_download_pdf(client, llm):
    from test_translation_pdf import fake_translator

    _saved_menu(client)
    assert client.get("/api/menus/M001/export.pdf").status_code == 400  # not translated yet

    llm.response = fake_translator
    result = ok(client.post("/api/menus/M001/export/translate", json={"version": 1}))
    assert result["failed"] == [] and result["translated_now"] == result["dishes"] > 0

    again = ok(client.post("/api/menus/M001/export/translate", json={"version": 1}))
    assert again["translated_now"] == 0

    pdf = client.get("/api/menus/M001/export.pdf?version=1")
    assert pdf.status_code == 200 and pdf.mimetype == "application/pdf" and pdf.data.startswith(b"%PDF")
    assert "M001_v1_recipes_en.pdf" in pdf.headers["Content-Disposition"]


# --- Dish deletion ---------------------------------------------------------------------


def test_delete_unused_dish(client, data_dir):
    dish_id = ok(client.get("/api/dishes"))[0]["dish_id"]
    assert ok(client.delete(f"/api/dishes/{dish_id}")) == {"deleted": dish_id}
    assert dish_id not in {d["dish_id"] for d in ok(client.get("/api/dishes"))}
    assert client.delete(f"/api/dishes/{dish_id}").status_code == 404


def test_dish_used_by_a_saved_menu_cannot_be_deleted(client):
    dinners = _saved_menu(client)
    used = dinners[0]["dish_ids"][0]
    response = client.delete(f"/api/dishes/{used}")
    assert response.status_code == 409 and "菜单 M001 第 1 版" in response.get_json()["issues"][0]
    assert used in {d["dish_id"] for d in ok(client.get("/api/dishes"))}
    ok(client.get("/api/menus/M001"))  # the menu still loads

    in_menu = {i for d in dinners for i in d["dish_ids"]}
    unused = next(d["dish_id"] for d in ok(client.get("/api/dishes")) if d["dish_id"] not in in_menu)
    ok(client.delete(f"/api/dishes/{unused}"))
    ok(client.get("/api/menus/M001"))


def test_dish_with_feedback_cannot_be_deleted(client, data_dir):
    dish_id = ok(client.get("/api/dishes"))[0]["dish_id"]
    feedback = Feedback(feedback_id="F001", dish_id=dish_id, kind="dislike", scope="future_menus")
    write_yaml_atomic(data_dir / "preferences.yaml", PreferencesFile(feedback=(feedback,)).model_dump(mode="json"))
    response = client.delete(f"/api/dishes/{dish_id}")
    assert response.status_code == 409 and "反馈 F001" in response.get_json()["issues"][0]

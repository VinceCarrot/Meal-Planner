"""The whole workflow through the HTTP API on the demo catalogue, with fake Claude backends per task.

Shortage -> candidate generation -> review -> plan -> save -> local adjustment with
feedback -> new version -> video import -> English PDF. The ingredient file must be
byte-for-byte unchanged at the end: no AI path may write it.
"""

import pytest

from fakes import FakeLLM, result
from test_translation_pdf import fake_translator
from meal_planner.demo import create_demo_data
from meal_planner.settings import LLMTask, Settings, save_settings
from meal_planner.video_import import VideoText
from meal_planner.web import create_app

START = "2026-10-19"
SOUP_TWICE = {"type": "dish_type_count", "dish_type": "soup", "min": 2, "max": 2}


def soup_drafts(prompt):
    count = int(prompt.split("Create ")[1].split(" ")[0])
    lines = [{"ingredient_id": "ing_cabbage", "quantity": 200, "unit": "g"}, {"ingredient_id": "ing_tofu", "quantity": 150, "unit": "g"}]
    return {"dishes": [
        {"name_zh": f"白菜豆腐汤{n}", "dish_type": "soup", "servings": 4, "ingredients": lines, "steps": ["煮 10 分钟"],
         "style": {"main_ingredients": ["ing_cabbage"], "cooking_method": "boil", "flavours": ["light"]}}
        for n in range(count)
    ]}


class VideoSource:
    def fetch(self, ref):
        return VideoText("清炒包菜", "", "包菜切丝，大火炒两分钟，加盐。", "subtitles", "zh")


@pytest.fixture
def client(tmp_path):
    data = tmp_path / "demo_data"
    create_demo_data(data)
    save_settings(data, Settings(planner=Settings().planner.model_copy(update={"time_limit_s": 10})))
    fakes = {
        LLMTask.CONSTRAINT_PARSING: FakeLLM({"results": [result("T001", execution=SOUP_TWICE)]}),
        LLMTask.DISH_GENERATION: FakeLLM(soup_drafts),
        LLMTask.TRANSLATION: FakeLLM(fake_translator),
        LLMTask.VIDEO_EXTRACTION: FakeLLM({"found_recipe": True, "reason": "", "recipe": {
            "name_zh": "清炒包菜", "dish_type": "vegetarian", "ingredients": [{"name": "包菜", "quantity": 300, "unit": "g", "main": True}],
            "steps": ["切丝", "大火炒两分钟"], "cooking_method": "stir_fry", "uncertainty_notes": "盐的用量未说明"}}),
    }
    app = create_app(data, llm_factory=lambda settings, task: fakes[task], video_source=VideoSource())
    return app.test_client(), data


def ok(response, status=200):
    assert response.status_code == status, response.get_json()
    return response.get_json()


def test_complete_workflow(client):
    client, data = client
    ingredients_before = (data / "ingredients.yaml").read_bytes()

    # Task constraint "two soups this time", explicitly replacing the persistent "one soup" rule.
    [task] = ok(client.post("/api/task-constraints/parse", json={"task": "menu_generation", "items": [{"description": "这次每顿两个汤"}]}))
    task["overrides"] = ["C002"]
    first = ok(client.post("/api/menus/plan", json={"start_date": START, "task_constraints": [task]}))
    assert first["status"] == "infeasible"
    [gap] = first["gaps"]
    assert gap["dish_type"] == "soup" and gap["additional_dishes_needed"] == 5

    generated = ok(client.post("/api/candidates/generate", json={
        "requests": [{"dish_type": "soup", "count": gap["suggested_count"], "reason": gap["description"]}], "task_constraints": [task]}))
    assert len(generated["added"]) == gap["suggested_count"] == 8
    decisions = [{"dish_id": d["dish_id"], "action": "approve"} for d in generated["added"]]
    ok(client.post("/api/review", json={"decisions": decisions}))

    planned = ok(client.post("/api/menus/plan", json={"start_date": START, "task_constraints": [task]}))
    assert planned["status"] == "feasible"
    assert all(sum(d["dish_type"] == "soup" for d in dinner["dishes"]) == 2 for dinner in planned["dinners"])

    dinners = [{"date": d["date"], "dish_ids": [x["dish_id"] for x in d["dishes"]]} for d in planned["dinners"]]
    saved = ok(client.post("/api/menus", json={"start_date": START, "diners": [{"description": "成年女性", "count": 3}],
                                               "dinners": dinners, "task_constraints": [task]}), 201)
    assert saved["status"] == "feasible"

    # Replace one dish. The generation-only rule does not carry over to the adjustment task:
    # without it the persistent "one soup" rule applies again and only a whole-menu change fits.
    target = {"date": dinners[5]["date"], "dish_id": dinners[5]["dish_ids"][0]}
    without = ok(client.post("/api/menus/M001/adjust/propose", json={"version": 1, **target}))
    assert without["scope"] == "menu" and [a["scope"] for a in without["attempts"]] == ["dish", "dinner", "week", "menu"]

    # Reusing the rule explicitly for this adjustment keeps the change local.
    reused = task | {"scope": ["menu_adjustment"]}
    proposal = ok(client.post("/api/menus/M001/adjust/propose", json={"version": 1, **target, "task_constraints": [reused]}))
    assert proposal["status"] == "feasible" and proposal["scope"] == "dish" and len(proposal["changes"]) == 1
    new_dinners = [{"date": d["date"], "dish_ids": [x["dish_id"] for x in d["dishes"]]} for d in proposal["dinners"]]
    v2 = ok(client.post("/api/menus/M001/adjust/save", json={
        "version": 1, "dinners": new_dinners, "change_note": "不喜欢", "task_constraints": [reused],
        "feedback": {"dish_id": target["dish_id"], "scope": "future_menus", "note": None}}), 201)
    assert v2["version"] == 2
    assert [d["dish_id"] for d in ok(client.get("/api/menus/M001?version=1"))["dinners"][5]["dishes"]][0] == target["dish_id"]

    # Import a recipe from a video into review.
    imported = ok(client.post("/api/videos/import", json={"url": "https://www.bilibili.com/video/BV1xx411c7mD"}), 201)
    assert imported["dish"]["ingredients"][0]["ingredient_id"] == "ing_cabbage"
    assert imported["dish"]["dish_id"] in {d["dish_id"] for d in ok(client.get("/api/pending"))["pending"]}

    # English recipe book for version 2.
    translated = ok(client.post("/api/menus/M001/export/translate", json={"version": 2}))
    assert translated["failed"] == []
    pdf = client.get("/api/menus/M001/export.pdf?version=2")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")

    assert (data / "ingredients.yaml").read_bytes() == ingredients_before


def test_corrupt_data_file_is_reported_with_its_backup(client):
    client, data = client
    ok(client.put("/api/preferences/diners", json={"diners": [{"description": "成人", "count": 2}]}))  # creates a .bak
    (data / "preferences.yaml").write_text("default_diners: [broken\n", encoding="utf-8")

    response = client.get("/api/dishes")

    assert response.status_code == 400
    issue = response.get_json()["issues"][0]
    assert "preferences.yaml" in issue and "backup exists: preferences.yaml.bak" in issue


def test_requests_for_other_host_names_are_refused(client):
    client, _ = client
    assert client.get("/api/dishes", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/dishes", headers={"Host": "127.0.0.1:5000"}).status_code == 200

import pytest

from meal_planner.catalogue import DataError
from meal_planner.llm.claude_cli import ClaudeCliBackend
from meal_planner.settings import LLMTask, Settings, load_settings, save_settings


def test_missing_file_gives_defaults(tmp_path):
    settings = load_settings(tmp_path)
    assert settings.model_for(LLMTask.CONSTRAINT_PARSING) == "sonnet"
    assert settings.model_for(LLMTask.DISH_GENERATION) is None


def test_model_choice_round_trips_and_selects_backend_model(tmp_path):
    models = {**Settings().models, LLMTask.CONSTRAINT_PARSING: "opus"}
    save_settings(tmp_path, Settings(models=models))

    backend = load_settings(tmp_path).backend_for(LLMTask.CONSTRAINT_PARSING)

    assert isinstance(backend, ClaudeCliBackend) and backend.model == "opus"


def test_partial_file_falls_back_to_default_per_task(tmp_path):
    (tmp_path / "settings.yaml").write_text("schema_version: 1\nmodels:\n  dish_generation: sonnet\n", encoding="utf-8")
    settings = load_settings(tmp_path)
    assert settings.model_for(LLMTask.DISH_GENERATION) == "sonnet"
    assert settings.model_for(LLMTask.TRANSLATION) == "sonnet"
    assert settings.models[LLMTask.INGREDIENT_ANALYSIS] == "sonnet"  # listed for the settings page


@pytest.mark.parametrize("text", ["llm_backend: local\n", "models:\n  cooking: opus\n"])
def test_invalid_settings_are_rejected(tmp_path, text):
    (tmp_path / "settings.yaml").write_text("schema_version: 1\n" + text, encoding="utf-8")
    with pytest.raises(DataError):
        load_settings(tmp_path)

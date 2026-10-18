"""Application settings stored in data/settings.yaml (edited from the Web UI in Phase 6).

Model names are passed to the selected backend unchanged; for the `claude_cli`
backend they are Claude Code `--model` values such as "sonnet" or "opus".
`None` means the backend's default model.
"""

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from .catalogue import DataError, DataIssue, parse_model
from .llm import LLMBackend, create_backend
from .models import Record
from .similarity import SimilarityWeights
from .yaml_io import YamlReadError, read_yaml, write_yaml_atomic

SETTINGS_FILE = "settings.yaml"


class LLMTask(StrEnum):
    CONSTRAINT_PARSING = "constraint_parsing"
    DISH_GENERATION = "dish_generation"
    VIDEO_EXTRACTION = "video_extraction"
    TRANSLATION = "translation"
    INGREDIENT_ANALYSIS = "ingredient_analysis"
    DISH_ANALYSIS = "dish_analysis"


DEFAULT_MODELS = {
    LLMTask.CONSTRAINT_PARSING: "sonnet",  # short structured task: faster, uses less quota
    LLMTask.DISH_GENERATION: None,  # account default (Opus)
    LLMTask.VIDEO_EXTRACTION: None,
    LLMTask.TRANSLATION: "sonnet",
    LLMTask.INGREDIENT_ANALYSIS: "sonnet",
    LLMTask.DISH_ANALYSIS: "sonnet",
}


class PlannerSettings(Record):
    """Optimizer configuration (ADR-017). Penalties are points in one weighted objective."""

    time_limit_s: float = Field(30, gt=0)
    workers: int = Field(8, ge=1)
    # Used when a similarity constraint gives no max_similarity. Provisional (ADR-017):
    # to be calibrated on the real catalogue.
    default_dish_similarity_threshold: float = Field(0.5, gt=0, le=1)
    default_meal_similarity_threshold: float = Field(0.5, gt=0, le=1)
    penalty_soft_count: int = Field(100, ge=0)  # per dish outside a soft count range, per dinner
    penalty_soft_exclusion: int = Field(100, ge=0)  # per serving of a soft-excluded dish
    penalty_soft_repeat: int = Field(50, ge=0)  # per pair of servings inside a soft repeat window
    penalty_shared_ingredient: int = Field(100, ge=0)  # per dish pair sharing an ingredient in one dinner (soft)
    penalty_dish_similarity: int = Field(100, ge=0)  # x similarity, per similar dish pair in the window
    penalty_meal_similarity: int = Field(100, ge=0)  # x normalized score, per similar dinner pair
    penalty_disliked: int = Field(200, ge=0)  # per serving of a dish with dislike feedback
    repair_max_steps: int = Field(50, ge=0)
    # Menu adjustment: cost of replacing a dish of the existing menu inside a wider adjustment scope.
    penalty_change: int = Field(300, ge=0)


class CandidateSettings(Record):
    """How many candidate dishes to request for a catalogue gap: max(minimum, ceil(factor x gap))."""

    factor: float = Field(1.5, ge=1)
    minimum: int = Field(5, ge=1)


class Settings(Record):
    schema_version: Literal[1] = 1
    llm_backend: Literal["claude_cli"] = "claude_cli"
    models: dict[LLMTask, str | None] = Field(default_factory=lambda: dict(DEFAULT_MODELS))
    similarity_weights: SimilarityWeights = SimilarityWeights()
    planner: PlannerSettings = PlannerSettings()
    candidates: CandidateSettings = CandidateSettings()

    @field_validator("models", mode="after")
    @classmethod
    def _all_tasks(cls, models: dict) -> dict:
        """Tasks missing from an older settings file get their default, so the UI lists every task."""
        return {**DEFAULT_MODELS, **models}

    def model_for(self, task: LLMTask) -> str | None:
        return self.models.get(task, DEFAULT_MODELS[task])

    def backend_for(self, task: LLMTask) -> LLMBackend:
        return create_backend(self.llm_backend, model=self.model_for(task))


def load_settings(data_dir: Path) -> Settings:
    """Read settings; a missing file means all defaults."""
    path = Path(data_dir) / SETTINGS_FILE
    if not path.exists():
        return Settings()
    try:
        raw = read_yaml(path)
    except YamlReadError as e:
        raise DataError([DataIssue(SETTINGS_FILE, "", str(e))]) from None
    return parse_model(Settings, raw, SETTINGS_FILE)


def save_settings(data_dir: Path, settings: Settings) -> None:
    write_yaml_atomic(Path(data_dir) / SETTINGS_FILE, settings.model_dump(mode="json"))

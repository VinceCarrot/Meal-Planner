"""Application settings stored in data/settings.yaml (edited from the Web UI in Phase 6).

Model names are passed to the selected backend unchanged; for the `claude_cli`
backend they are Claude Code `--model` values such as "sonnet" or "opus".
`None` means the backend's default model.
"""

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field

from .catalogue import DataError, DataIssue, parse_model
from .llm import LLMBackend, create_backend
from .models import Record
from .yaml_io import YamlReadError, read_yaml, write_yaml_atomic

SETTINGS_FILE = "settings.yaml"


class LLMTask(StrEnum):
    CONSTRAINT_PARSING = "constraint_parsing"
    DISH_GENERATION = "dish_generation"
    VIDEO_EXTRACTION = "video_extraction"
    TRANSLATION = "translation"


DEFAULT_MODELS = {
    LLMTask.CONSTRAINT_PARSING: "sonnet",  # short structured task: faster, uses less quota
    LLMTask.DISH_GENERATION: None,  # account default (Opus)
    LLMTask.VIDEO_EXTRACTION: None,
    LLMTask.TRANSLATION: "sonnet",
}


class Settings(Record):
    schema_version: Literal[1] = 1
    llm_backend: Literal["claude_cli"] = "claude_cli"
    models: dict[LLMTask, str | None] = Field(default_factory=lambda: dict(DEFAULT_MODELS))

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

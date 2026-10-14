"""Request helpers shared by the API modules."""

from typing import Any

from flask import current_app, request

from ..catalogue import Catalogue
from ..llm import LLMBackend
from ..settings import LLMTask, Settings, load_settings
from ..store import DataStore


class NotFound(Exception):
    pass


class Conflict(Exception):
    """The request is valid but other data still depends on the record."""

    def __init__(self, message: str, issues: list[str]):
        super().__init__(message)
        self.issues = issues


def store() -> DataStore:
    return DataStore(current_app.config["DATA_DIR"])


def load() -> tuple[DataStore, Catalogue]:
    s = store()
    return s, s.load()


def settings() -> Settings:
    return load_settings(current_app.config["DATA_DIR"])


def llm(task: LLMTask) -> LLMBackend:
    return current_app.config["LLM_FACTORY"](settings(), task)


def body() -> Any:
    """The JSON request body. Non-JSON requests are refused with 415."""
    return request.get_json()


def dump(model) -> Any:
    return model.model_dump(mode="json")

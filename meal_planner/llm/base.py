from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


class LLMError(Exception):
    """The model could not be called or did not return a usable result."""


@dataclass(frozen=True)
class Tool:
    """An application tool offered to an agent call.

    `fn` is an ordinary type-annotated Python function; each backend derives the
    tool's input schema from its signature. Tools must only read data: build them
    from `ReadOnlyCatalogue`, never from `DataStore` (ADR-012).
    """

    name: str
    description: str
    fn: Callable[..., Any]


class LLMBackend(Protocol):
    def structured(self, system: str, prompt: str, output_schema: dict, web_search: bool = False) -> dict:
        """One call without application tools; returns an object matching `output_schema`.

        `web_search=True` lets the model search the web during this call (and nothing else).
        """
        ...

    def agent(self, system: str, prompt: str, tools: Sequence[Tool], output_schema: dict) -> dict:
        """A tool-using loop over `tools`; returns an object matching `output_schema`."""
        ...

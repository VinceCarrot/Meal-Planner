class FakeLLM:
    """Test double for LLMBackend: returns a canned response and records calls."""

    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls = []

    def structured(self, system, prompt, output_schema):
        self.calls.append({"system": system, "prompt": prompt, "schema": output_schema})
        if self.error:
            raise self.error
        return self.response(prompt) if callable(self.response) else self.response

    def agent(self, system, prompt, tools, output_schema):
        raise AssertionError("agent calls are not expected here")


def result(constraint_id, status="executable", strictness="hard", execution=None, notes=""):
    return {"constraint_id": constraint_id, "parse_status": status, "strictness": strictness, "execution": execution, "notes": notes}

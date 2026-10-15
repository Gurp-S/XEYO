"""Typed provider output-limit fact, compatible with the protocol boundary."""
from engine.model_events import ModelProtocolError


class OutputLimitError(ModelProtocolError):
    def __init__(self, finish_reason):
        if finish_reason not in {"length", "max_tokens"}:
            raise ValueError("invalid_output_limit_reason")
        self.finish_reason = finish_reason
        super().__init__(f"model stream ended with finish_reason={finish_reason}")

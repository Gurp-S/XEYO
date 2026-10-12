"""Request-local prediction cache; a different input cannot reuse its count."""
import hashlib
import json


class CountedInput:
    def __init__(self, model, abort):
        self.model, self.abort = model, abort
        self.counts = {}

    def __getattr__(self, name):
        return getattr(self.model, name)

    @staticmethod
    def identity(source):
        return hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode("utf-8")).hexdigest()

    def context_token_measure(self, source):
        key = self.identity(source)
        if key in self.counts:
            return self.counts[key]
        measure = getattr(self.model, "context_token_measure", None)
        return measure(source) if callable(measure) else None

    async def prime(self, messages, tools):
        predict = getattr(self.model, "predict_context_tokens", None)
        measure = getattr(self.model, "context_token_measure", None)
        if not callable(predict) and not callable(measure):
            return
        self.abort.raise_if_aborted()
        source = self.model.context_input(messages, tools)
        key = self.identity(source)
        if key not in self.counts:
            if callable(predict):
                count = await predict(messages, tools, self.abort)
                value = (count, "anthropic_count_tokens_prediction") if count is not None else None
            else:
                value = measure(source)
            self.abort.raise_if_aborted()
            self.counts[key] = value

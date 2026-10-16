"""Generation refusals that preserve source; never absorb commit/storage errors."""


class GenerationUnavailable(Exception):
    """Transient model failure, marked only inside the generation boundary."""


def mark_generation_failure(exc):
    from common.errors import classify_llm_failure
    if isinstance(exc, OSError) and not isinstance(exc, (TimeoutError, ConnectionError)):
        return  # Storage/permission errors never become transport by wording.
    failure = classify_llm_failure(exc)
    if failure.retryable:
        raise GenerationUnavailable('handoff_generation_' + failure.code) from exc


def recoverable(exc):
    from model.output_exhaustion import OutputLimitError
    return isinstance(exc, (GenerationUnavailable, OutputLimitError)) or (isinstance(exc, ValueError) and str(exc) in {
        'semantic_generation_empty', 'semantic_generation_unexpected_tool',
        'semantic_generation_output_limit', 'semantic_generation_capacity_exceeded',
        'semantic_generation_recall_limit', 'semantic_generation_call_identity_conflict',
        'handoff_declaration_missing', 'handoff_response_limit', 'handoff_request_exceeds_capacity',
    })

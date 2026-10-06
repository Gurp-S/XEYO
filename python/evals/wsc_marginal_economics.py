"""Shadow fold economics: charge only miss added by the fold.

Both candidates see the same new input and the same preceding request/response
prefixes. The more expensive transition across the two structural scenarios
is used; this is not evidence of provider cache persistence or future reuse.
"""
from dataclasses import dataclass

from evals.wsc_prefix_accounting import estimate, shared_tokens

BASIS = 'wsc_marginal_openai_json_utf8_quarters'


@dataclass(frozen=True)
class MarginalEconomics:
    keep_tokens: int
    fold_tokens: int
    shared_tokens: int
    input_extra_miss: int
    response_extra_miss: int

    @property
    def saved_tokens(self):
        return self.keep_tokens - self.fold_tokens

    @property
    def transition_tokens(self):
        return max(0, self.input_extra_miss, self.response_extra_miss)

    def account(self):
        return dict(economics_basis=BASIS, projection_keep_tokens=self.keep_tokens,
                    projection_fold_tokens=self.fold_tokens, projection_shared_tokens=self.shared_tokens,
                    projection_saved_tokens=self.saved_tokens, projection_transition_tokens=self.transition_tokens,
                    incremental_miss_input=self.input_extra_miss, incremental_miss_response=self.response_extra_miss)


def compare(keep: str, fold: str, *, previous: str, response_prefix: str | None):
    retained = estimate(keep, previous=previous, response_prefix=response_prefix)
    compressed = estimate(fold, previous=previous, response_prefix=response_prefix)
    return MarginalEconomics(retained.tokens, compressed.tokens, shared_tokens(keep, fold),
                             compressed.input_miss - retained.input_miss,
                             compressed.response_miss - retained.response_miss)

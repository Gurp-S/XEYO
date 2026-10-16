"""Eval-only byte-exact publishing; task and physical-scope checks unchanged."""
from evals.wsc_task_acceptance_protocol import ArtifactSink


class ExactArtifactSink(ArtifactSink):
    @staticmethod
    def _publish(path, content):
        from rewind.service import _write_atomic
        _write_atomic(path, content.encode('utf-8'))

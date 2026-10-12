"""Isolated generation coverage with a model-independent validation contract."""
from dataclasses import dataclass, field
from msgtypes.message import ToolUse
from synaptic.source_presentation import Coverage, digest, merge, validated


@dataclass
class PresentedHandoff(ToolUse):
    presentation: dict = field(default_factory=dict)

"""Observed empty TODO state, distinct from an absent or unobserved state."""
from synaptic.types import Pin


def empty_state_pin(seeds):
    if (seeds.todo_source >= 0 and seeds.todo_observed
            and seeds.todo_active_count == 0 and not seeds.todos):
        return (Pin("todo:0", "TODO", "observed active=0"),)
    return ()

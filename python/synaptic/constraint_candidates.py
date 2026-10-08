"""Historical keyword matches are candidates, never constraint authority."""
from synaptic.types import Pin


def pin(seeds, graph, region_end):
    from synaptic.task_checkpoint import enabled
    from synaptic.seeds import extract_constraints
    if not enabled():
        return None
    sources = tuple(i for i in seeds.user_nodes if i < region_end
                    and extract_constraints(graph.node(i).text))
    if not sources:
        return None
    return Pin("constraint_candidates", "历史约束候选来源",
               f"sources={len(sources)} validity=unobserved", nodes=sources)

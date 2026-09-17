import sys, tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
from synaptic.project import default_params, project
from wsc._fixtures import synth_session

msgs = synth_session(turns=24, user_every=1)
for level in ("Medium+", "Hard", "Ultra"):
    for style in ("expand", "read"):
        p = replace(default_params(level=level), handle_style=style)
        tmp = Path(tempfile.mkdtemp()) / ".xeyo_offload" / "cold.txt"
        proj = project(msgs, region_end=len(msgs), params=p, view_path=tmp)
        print(
            f"{level:8s} {style:6s} pruned={len(proj.result.hot.pruned_nodes):4d} "
            f"kept={len(proj.result.hot.kept_nodes):4d} cards={len(proj.result.hot.cards):3d} "
            f"req={proj.result.user_requests_rendered}/{proj.result.user_requests_total} "
            f"tokens={proj.tokens} expand={proj.text.count('expand(')} read={proj.text.count('Read(file_path=')}"
        )

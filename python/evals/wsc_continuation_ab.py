"""Retired literal-history experiment; saved batch-22 reports stay unchanged.

Use wsc_task_continuity_ab.py for state, provenance and emission regressions.
The previous experiment measured word retention, not long-task behavior.
"""
import argparse
import sys


def evaluate(folder, live_source):
    raise RuntimeError(
        "retired_requirement_floor_evaluation: use evals/wsc_task_continuity_ab.py; "
        "prior reports remain historical artifacts"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder")
    parser.add_argument("live_source")
    options = parser.parse_args()
    try:
        evaluate(options.folder, options.live_source)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)

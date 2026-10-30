"""Acquisition permission cannot accidentally run an unqualified comparison."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
from native_c_qualification import require_qualification


class NativeAcquisitionTests(unittest.TestCase):
    def test_only_one_native_compaction_is_admitted_in_owned_study(self):
        reg = {"purpose": "carrier_acquisition", "order": ["compaction"],
               "caps": {"native_compaction_calls": 1, "pairs": 0}, "study_workspace": {"bound": True}}
        require_qualification(reg)
        for patch in ({"order": ["B", "C"]}, {"caps": {"native_compaction_calls": 2, "pairs": 0}},
                      {"caps": {"native_compaction_calls": 1, "pairs": 1}}, {"study_workspace": None}):
            with self.subTest(patch=patch), self.assertRaisesRegex(ValueError, "acquisition_must_only"):
                require_qualification({**reg, **patch})

    def test_comparison_still_requires_C_qualification(self):
        with self.assertRaisesRegex(ValueError, "C_qualification_required"):
            require_qualification({"purpose": "comparison", "study_workspace": {"bound": True}})


if __name__ == "__main__":
    unittest.main()

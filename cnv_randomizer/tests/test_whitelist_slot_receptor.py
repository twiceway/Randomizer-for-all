"""T-081 — whitelist slot receptor bucket + export consistency."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from donor_msb_compat import (  # noqa: E402
    donor_allowed_for_slot,
    donor_slot_compat_reject_reason,
)
from whitelist_slot_receptor import (  # noqa: E402
    BUCKET_IDS,
    ScannedSlot,
    SlotScanResult,
    aggregate_donor_receptor,
    classify_receptor_bucket,
    donor_allowed_matches_export,
)

GIANT_CROW = "m60_51_53_00:c4560_9002"
GROUND_TRASH = "m10_00_00_00:c0000_9000"


def _slot(**kwargs) -> dict:
    base = {
        "map_id": "m60_37_45_00",
        "name": "c3471_9000",
        "model": "c3471",
        "walk_route": "",
        "backup_anim": -1,
        "chr_activate": 0,
        "collision_part": "",
    }
    base.update(kwargs)
    return base


def _compat_crow() -> dict:
    return {
        GIANT_CROW: {
            "force_donor_msb": True,
            "compat_patrol_keep": False,
            "compat_standing_keep": False,
            "donor_pose_label": "aerial_model",
            "donor_walk_route": "",
            "vanilla_scan_model": "c4560",
            "vanilla_supported_buckets": ["aerial_slot"],
        },
        GROUND_TRASH: {
            "force_donor_msb": False,
            "compat_patrol_keep": True,
            "compat_standing_keep": True,
            "donor_pose_label": "ground_stand",
            "donor_walk_route": "",
            "vanilla_scan_model": "c0000",
            "vanilla_supported_buckets": [
                "collision_perch",
                "patrol",
                "sit_squat",
                "ground_stand",
            ],
        },
    }


def _scan_from_slots(slots: list[dict]) -> SlotScanResult:
    result = SlotScanResult()
    for slot in slots:
        bid = classify_receptor_bucket(slot)
        result.slots.append(
            ScannedSlot(
                bucket_id=bid,
                pick_eligible=True,
                apply_class="standing_keep_initial",
                slot=slot,
            )
        )
        result.bucket_totals_all_msb[bid] = result.bucket_totals_all_msb.get(bid, 0) + 1
        result.bucket_totals_pick_eligible[bid] = (
            result.bucket_totals_pick_eligible.get(bid, 0) + 1
        )
    return result


class TestClassifyReceptorBucket(unittest.TestCase):
    def test_patrol_before_backup(self) -> None:
        self.assertEqual(
            classify_receptor_bucket(_slot(walk_route="route_a", backup_anim=700)),
            "patrol",
        )

    def test_ground_stand_default(self) -> None:
        self.assertEqual(classify_receptor_bucket(_slot()), "ground_stand")

    def test_sit_squat(self) -> None:
        self.assertEqual(
            classify_receptor_bucket(_slot(backup_anim=702)),
            "sit_squat",
        )

    def test_aerial_slot_model(self) -> None:
        self.assertEqual(
            classify_receptor_bucket(_slot(model="c4560_9000")),
            "aerial_slot",
        )


class TestAggregateDonorReceptor(unittest.TestCase):
    def test_crow_patrol_and_ground_blocked_aerial_only(self) -> None:
        scanned = _scan_from_slots(
            [
                _slot(walk_route="patrol_1"),
                _slot(name="stand_1"),
                _slot(model="c4560"),
            ]
        )
        compat = _compat_crow()
        agg = aggregate_donor_receptor(scanned, GIANT_CROW, compat)
        patrol = agg["receptor_all_msb"]["patrol"]
        ground = agg["receptor_all_msb"]["ground_stand"]
        aerial = agg["receptor_all_msb"]["aerial_slot"]
        self.assertEqual(patrol["total"], 1)
        self.assertEqual(patrol["allowed"], 0)
        self.assertEqual(patrol["blocked"], 1)
        self.assertEqual(ground["allowed"], 0)
        self.assertEqual(aerial["allowed"], 1)
        self.assertEqual(agg["historical_states"], ["aerial_slot"])
        self.assertIn("historical_state_counts", agg)

    def test_receptor_fast_reject_matches_full_check(self) -> None:
        compat = _compat_crow()
        receptor_index = {
            GIANT_CROW: aggregate_donor_receptor(
                _scan_from_slots(
                    [_slot(walk_route="p"), _slot(), _slot(model="c4560")]
                ),
                GIANT_CROW,
                compat,
            )
        }
        patrol_slot = _slot(walk_route="patrol_1")
        self.assertFalse(
            donor_allowed_for_slot(
                patrol_slot, GIANT_CROW, compat, receptor_index
            )
        )
        stand_slot = _slot()
        self.assertFalse(
            donor_allowed_for_slot(
                stand_slot, GIANT_CROW, compat, receptor_index
            )
        )
        aerial_slot = _slot(model="c4560")
        self.assertTrue(
            donor_allowed_for_slot(
                aerial_slot, GIANT_CROW, compat, receptor_index
            )
        )

    def test_ground_trash_patrol_allowed(self) -> None:
        scanned = _scan_from_slots([_slot(walk_route="patrol_1")])
        compat = _compat_crow()
        agg = aggregate_donor_receptor(scanned, GROUND_TRASH, compat)
        patrol = agg["receptor_all_msb"]["patrol"]
        self.assertEqual(patrol["allowed"], 1)
        self.assertIn("patrol", agg["historical_states"])
        self.assertIn("ground_stand", agg["historical_states"])

    def test_reject_matches_donor_allowed(self) -> None:
        compat = _compat_crow()
        slots = [
            _slot(walk_route="p"),
            _slot(),
            _slot(backup_anim=700),
        ]
        for slot in slots:
            self.assertEqual(
                donor_allowed_matches_export(slot, GIANT_CROW, compat),
                donor_allowed_for_slot(slot, GIANT_CROW, compat),
            )
            self.assertEqual(
                donor_allowed_matches_export(slot, GIANT_CROW, compat),
                donor_slot_compat_reject_reason(slot, GIANT_CROW, compat) is None,
            )


class TestSkipScriptActivatePairing(unittest.TestCase):
    def test_script_activate_with_collision_is_collision_perch(self) -> None:
        """T-089 global: chr_activate no longer a pairing bucket."""
        for name in ("c4200_9000", "c4311_9000"):
            slot = _slot(
                map_id="m60_42_37_00",
                name=name,
                model="c4200" if name.startswith("c4200") else "c4311",
                chr_activate=1000000003,
                collision_part="h423700",
            )
            self.assertEqual(classify_receptor_bucket(slot), "collision_perch")

    def test_script_activate_plain_is_ground_stand(self) -> None:
        slot = _slot(
            map_id="m10_00_00_00",
            name="c3000_9000",
            model="c3000",
            chr_activate=1000000003,
            collision_part="",
        )
        self.assertEqual(classify_receptor_bucket(slot), "ground_stand")


class TestExportRowCount(unittest.TestCase):
    def test_build_donor_base_matches_contract(self) -> None:
        from export_whitelist_donor_slot_receptor import _build_donor_base_rows
        from gatefront_quad_catalog import iter_contract_whitelist_rows

        if not (SCRIPT_DIR / "cache" / "enemy_index.json").is_file():
            self.skipTest("enemy_index missing")
        wl_len = len(iter_contract_whitelist_rows())
        base = _build_donor_base_rows()
        self.assertEqual(len(base), wl_len)
        self.assertGreater(wl_len, 300)


if __name__ == "__main__":
    unittest.main()

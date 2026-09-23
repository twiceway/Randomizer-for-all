"""门前 14 槽链路：飞巡蝙蝠 / 蹲坐拒大狗 / 唤声船原位不捐。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from donor_msb_compat import donor_slot_compat_reject_reason, filter_prep_donor_indices_for_msb_compat
from enemy_randomizer_core import (
    is_keep_original_slot_model,
    is_never_donor_model,
    is_never_donor_npc_id,
    is_unsafe_donor_template,
    slot_physique_bucket,
)

_ROOT = Path(__file__).resolve().parents[1]
_CATEGORIES = json.loads((_ROOT / "enemy_categories.json").read_text(encoding="utf-8-sig"))
_ALLOWLIST = json.loads(
    (_ROOT / "donor_pool_review_allowlist.json").read_text(encoding="utf-8-sig")
)


class Gatefront14SlotPipelineTests(unittest.TestCase):
    def test_c4200_slot_is_flying_physique(self) -> None:
        slot = {
            "model": "c4200",
            "chr_activate": 1000000003,
            "collision_part": "h423700",
            "walk_route": "",
            "backup_anim": -1,
        }
        self.assertEqual(slot_physique_bucket(slot, _CATEGORIES), "flying")

    def test_c4200_script_slot_allows_humanoid_without_force(self) -> None:
        """T-089: gatefront bats pair as collision_perch; historical match enough."""
        slot = {
            "map_id": "m60_42_37_00",
            "name": "c4200_9000",
            "model": "c4200",
            "chr_activate": 1000000003,
            "collision_part": "h423700",
            "walk_route": "",
            "backup_anim": -1,
        }
        compat = {
            "m60_47_51_00:c4321_9000": {
                "vanilla_scan_model": "c4321",
                "vanilla_supported_buckets": [
                    "collision_perch",
                    "script_chr_activate",
                    "ground_stand",
                    "patrol",
                ],
                "force_donor_msb": False,
            }
        }
        self.assertIsNone(
            donor_slot_compat_reject_reason(
                slot,
                "m60_47_51_00:c4321_9000",
                compat,
                categories_cfg=_CATEGORIES,
            )
        )

    def test_c4200_allows_humanoid_when_historical_and_force(self) -> None:
        slot = {
            "map_id": "m60_42_37_00",
            "name": "c4200_9000",
            "model": "c4200",
            "chr_activate": 1000000003,
            "collision_part": "h423700",
            "walk_route": "",
            "backup_anim": -1,
        }
        compat = {
            "m60_47_51_00:c4321_9000": {
                "vanilla_scan_model": "c4321",
                "vanilla_supported_buckets": [
                    "collision_perch",
                    "script_chr_activate",
                    "ground_stand",
                    "patrol",
                ],
                "force_donor_msb": True,
            }
        }
        self.assertIsNone(
            donor_slot_compat_reject_reason(
                slot,
                "m60_47_51_00:c4321_9000",
                compat,
                categories_cfg=_CATEGORIES,
            )
        )

    def test_sit_slot_rejects_gowry_giant_dog(self) -> None:
        slot = {
            "map_id": "m60_42_37_00",
            "name": "c4311_9000",
            "model": "c4311",
            "backup_anim": 704,
            "chr_activate": 0,
            "walk_route": "",
            "collision_part": "",
        }
        compat = {
            "m60_50_38_00:c4550_9000": {
                "vanilla_scan_model": "c4550",
                "donor_pose_label": "sit_squat_backup_709",
                "vanilla_supported_buckets": ["sit_squat", "ground_stand"],
                "force_donor_msb": True,
            }
        }
        self.assertEqual(
            donor_slot_compat_reject_reason(
                slot,
                "m60_50_38_00:c4550_9000",
                compat,
                categories_cfg=_CATEGORIES,
            ),
            "sit_slot_oversized_donor",
        )

    def test_tibia_mariner_keep_original_and_never_donor(self) -> None:
        self.assertTrue(is_keep_original_slot_model("c4950", _CATEGORIES))
        self.assertTrue(is_keep_original_slot_model("c5620", _CATEGORIES))
        self.assertTrue(is_never_donor_model("c4950", _CATEGORIES))
        self.assertTrue(is_never_donor_model("c5620", _CATEGORIES))
        self.assertTrue(
            is_never_donor_npc_id({"npc": 56200084}, _CATEGORIES)
        )
        self.assertTrue(
            is_unsafe_donor_template(
                {"npc": 56200084, "model": "c5620", "template_id": "m61_48_38_00:c5620_9000"},
                _CATEGORIES,
            )
        )
        npc_ids = {
            int(n)
            for ids in (_ALLOWLIST.get("npc_ids_by_category") or {}).values()
            for n in ids
        }
        if not npc_ids:
            for v in _ALLOWLIST.values():
                if isinstance(v, list) and v and isinstance(v[0], int):
                    npc_ids.update(int(x) for x in v)
                elif isinstance(v, dict):
                    for inner in v.values():
                        if isinstance(inner, list) and inner and isinstance(inner[0], int):
                            npc_ids.update(int(x) for x in inner)
        self.assertNotIn(56200084, npc_ids)

    def test_crystal_crab_hard_never_donor_and_not_allowlisted(self) -> None:
        from enemy_category_rules import is_never_donor_hard_block_model

        self.assertTrue(is_never_donor_hard_block_model("c2275", _CATEGORIES))
        self.assertTrue(is_keep_original_slot_model("c2275", _CATEGORIES))
        self.assertTrue(
            is_unsafe_donor_template(
                {
                    "npc": 22751024,
                    "model": "c2275",
                    "template_id": "m14_00_00_00:c2275_9026",
                },
                _CATEGORIES,
            )
        )
        npc_ids = {
            int(n)
            for ids in (_ALLOWLIST.get("npc_ids_by_category") or {}).values()
            for n in ids
        }
        self.assertNotIn(22751024, npc_ids)
        self.assertNotIn(22740052, npc_ids)

    def test_pick_filter_drops_tibia_even_if_prep_stale(self) -> None:
        prep = {
            "donors": [
                {
                    "template_id": "m61_48_38_00:c5620_9000",
                    "model": "c5620",
                    "npc": 56200084,
                }
            ]
        }
        slot = {
            "map_id": "m60_42_37_00",
            "name": "c4311_9011",
            "model": "c4311",
            "walk_route": "route",
        }
        self.assertEqual(
            filter_prep_donor_indices_for_msb_compat(
                prep, [0], slot, compat_by_tid={}, categories_cfg=_CATEGORIES
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()

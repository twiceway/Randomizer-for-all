"""T-085 / T-080 — historical-state pairing reject (+ size / force_donor)."""

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

FORCE_BIRD = "m60_49_52_00:c4980_9000"
GIANT_CROW = "m60_51_53_00:c4560_9002"
NORMAL_TRASH = "m10_00_00_00:c0000_9000"
PATROL_ONLY = "m60_47_39_00:c4560_9000"


def _slot(
    *,
    walk_route: str = "",
    name: str = "c3471_9000",
    backup_anim: int = -1,
    chr_activate: int = 0,
    model: str = "c3471",
    collision_part: str = "",
) -> dict:
    return {
        "map_id": "m60_37_45_00",
        "name": name,
        "model": model,
        "walk_route": walk_route,
        "backup_anim": backup_anim,
        "chr_activate": chr_activate,
        "collision_part": collision_part,
    }


WOLF_BOSS_STAND = "m60_49_57_00:c3180_9000"
WOLF_PATROL = "m60_35_50_00:c3180_9002"
C4315_STAND = "m60_47_57_00:c4315_9000"
C5590_STAND = "m61_47_35_00:c5590_9000"
C5525_STAND = "m61_47_47_00:c5525_9000"
C6233_PAGE = "m61_47_44_00:c6233_9000"
C5250_PATROL = "m20_01_00_00:c5250_9005"
C3470_COLLISION = "m11_10_00_00:c3470_9027"

_QUADRUPED_CFG = {"quadruped_slot_model_prefixes": ["c3180", "c5525"]}


def _compat_v2() -> dict:
    """Vanilla bucket sets from enemy_index scan (model → buckets)."""
    return {
        FORCE_BIRD: {
            "vanilla_scan_model": "c4980",
            "vanilla_supported_buckets": [
                "script_chr_activate",
                "patrol",
                "aerial_slot",
            ],
            "force_donor_msb": True,
            "compat_patrol_keep": False,
            "compat_standing_keep": False,
            "donor_pose_label": "scripted_flyer",
            "donor_walk_route": "",
        },
        GIANT_CROW: {
            "vanilla_scan_model": "c4560",
            "vanilla_supported_buckets": ["aerial_slot"],
            "force_donor_msb": True,
            "compat_patrol_keep": False,
            "compat_standing_keep": False,
            "donor_pose_label": "aerial_model",
            "donor_walk_route": "",
        },
        NORMAL_TRASH: {
            "vanilla_scan_model": "c0000",
            "vanilla_supported_buckets": [
                "collision_perch",
                "patrol",
                "sit_squat",
                "ground_stand",
            ],
        },
        PATROL_ONLY: {
            "vanilla_scan_model": "c4560",
            "vanilla_supported_buckets": ["patrol"],
        },
        WOLF_BOSS_STAND: {
            "vanilla_scan_model": "c3180",
            "vanilla_supported_buckets": ["patrol", "ground_stand"],
            "vanilla_patrol_profiles": [{"npc": 31800025, "think": 31800020}],
            "donor_npc": 31800100,
            "donor_think": 31800050,
            "donor_walk_route": "",
        },
        WOLF_PATROL: {
            "vanilla_scan_model": "c3180",
            "vanilla_supported_buckets": ["patrol", "ground_stand"],
            "vanilla_patrol_profiles": [{"npc": 31800025, "think": 31800020}],
            "donor_npc": 31800025,
            "donor_think": 31800020,
            "donor_walk_route": "walk_route_c3180_9002_6",
        },
        C4315_STAND: {
            "vanilla_scan_model": "c4315",
            "vanilla_supported_buckets": ["patrol", "ground_stand"],
            "vanilla_patrol_profiles": [
                {"npc": 43150052, "think": 43150000},
                {"npc": 43151050, "think": 43151001},
            ],
            "donor_npc": 43150052,
            "donor_think": 43150000,
            "donor_walk_route": "",
        },
        C5590_STAND: {
            "vanilla_scan_model": "c5590",
            "vanilla_supported_buckets": ["patrol", "ground_stand"],
            "vanilla_patrol_profiles": [{"npc": 55900091, "think": 55900000}],
            "donor_npc": 55900483,
            "donor_think": 55900000,
            "donor_walk_route": "",
        },
        C5525_STAND: {
            "vanilla_scan_model": "c5525",
            "vanilla_supported_buckets": ["patrol", "ground_stand"],
            "vanilla_patrol_profiles": [{"npc": 55250095, "think": 55250000}],
            "donor_npc": 55250095,
            "donor_think": 55250000,
            "donor_walk_route": "",
        },
        C6233_PAGE: {
            "vanilla_scan_model": "c6233",
            "vanilla_supported_buckets": ["ground_stand"],
            "vanilla_patrol_profiles": [],
            "donor_npc": 62330082,
            "donor_think": 37030000,
            "donor_walk_route": "",
        },
        C5250_PATROL: {
            "vanilla_scan_model": "c5250",
            "vanilla_supported_buckets": ["patrol", "ground_stand"],
            "vanilla_patrol_profiles": [{"npc": 52501489, "think": 52501050}],
            "donor_npc": 52501489,
            "donor_think": 52501050,
            "donor_walk_route": "walk_route_c5250_9005_83",
            "donor_pose_label": "patrol",
            "compat_patrol_keep": True,
        },
        C3470_COLLISION: {
            "vanilla_scan_model": "c3470",
            "vanilla_supported_buckets": [
                "sit_squat",
                "ground_stand",
                "collision_perch",
            ],
            "donor_npc": 34700200,
            "donor_think": 34700500,
            "donor_walk_route": "",
            "donor_pose_label": "collision_anchor_no_backup",
        },
    }


class DonorVanillaStateRejectTests(unittest.TestCase):
    def test_standing_force_bird_blocked(self) -> None:
        self.assertEqual(
            donor_slot_compat_reject_reason(
                _slot(),
                FORCE_BIRD,
                _compat_v2(),
            ),
            "vanilla_state_unsupported",
        )

    def test_patrol_force_bird_allowed_by_historical(self) -> None:
        """T-085: patrol ∈ historical → allow (no patrol_keep stack)."""
        self.assertIsNone(
            donor_slot_compat_reject_reason(
                _slot(walk_route="Route_A", name="c4050_9000"),
                FORCE_BIRD,
                _compat_v2(),
            )
        )

    def test_patrol_giant_crow_blocked(self) -> None:
        self.assertEqual(
            donor_slot_compat_reject_reason(
                _slot(walk_route="Route_A", name="c4311_9005"),
                GIANT_CROW,
                _compat_v2(),
            ),
            "vanilla_state_unsupported",
        )

    def test_aerial_giant_crow_allowed(self) -> None:
        self.assertIsNone(
            donor_slot_compat_reject_reason(
                _slot(model="c4560", name="c4560_9002"),
                GIANT_CROW,
                _compat_v2(),
            )
        )

    def test_standing_giant_crow_blocked(self) -> None:
        self.assertEqual(
            donor_slot_compat_reject_reason(
                _slot(name="c4311_9008"),
                GIANT_CROW,
                _compat_v2(),
            ),
            "vanilla_state_unsupported",
        )

    def test_patrol_normal_trash_allowed(self) -> None:
        self.assertTrue(
            donor_allowed_for_slot(
                _slot(walk_route="Route_A", name="c4050_9000"),
                NORMAL_TRASH,
                _compat_v2(),
            )
        )

    def test_standing_patrol_only_model_blocked(self) -> None:
        self.assertEqual(
            donor_slot_compat_reject_reason(
                _slot(name="c4311_9008"),
                PATROL_ONLY,
                _compat_v2(),
            ),
            "vanilla_state_unsupported",
        )

    def test_patrol_patrol_only_model_allowed(self) -> None:
        self.assertIsNone(
            donor_slot_compat_reject_reason(
                _slot(walk_route="Route_A", name="c4050_9000"),
                PATROL_ONLY,
                _compat_v2(),
            )
        )

    def test_script_slot_force_bird_allowed(self) -> None:
        self.assertIsNone(
            donor_slot_compat_reject_reason(
                _slot(name="c4980_9001", chr_activate=1, model="c4980"),
                FORCE_BIRD,
                _compat_v2(),
            )
        )

    def test_aerial_slot_normal_trash_blocked(self) -> None:
        self.assertEqual(
            donor_slot_compat_reject_reason(
                _slot(name="c4560_9000", model="c4560"),
                NORMAL_TRASH,
                _compat_v2(),
            ),
            "vanilla_state_unsupported",
        )

    def test_vanilla_no_occurrence(self) -> None:
        compat = {
            "m10_00_00_00:c9999_9000": {
                "vanilla_scan_model": "c9999",
                "vanilla_supported_buckets": [],
            }
        }
        self.assertEqual(
            donor_slot_compat_reject_reason(_slot(), "m10_00_00_00:c9999_9000", compat),
            "vanilla_no_occurrence",
        )

    def test_patrol_wolf_boss_standing_allowed_by_historical(self) -> None:
        """T-085: patrol ∈ historical → allow (no lineage stack)."""
        self.assertIsNone(
            donor_slot_compat_reject_reason(
                _slot(walk_route="walk_route_c4310_9007_20", name="c4311_9005"),
                WOLF_BOSS_STAND,
                _compat_v2(),
                categories_cfg=_QUADRUPED_CFG,
            )
        )

    def test_patrol_wolf_patrol_lineage_allowed(self) -> None:
        self.assertIsNone(
            donor_slot_compat_reject_reason(
                _slot(walk_route="walk_route_c4310_9007_20", name="c4311_9005"),
                WOLF_PATROL,
                _compat_v2(),
            )
        )

    def test_standing_wolf_boss_allowed(self) -> None:
        self.assertIsNone(
            donor_slot_compat_reject_reason(
                _slot(name="c4311_9008"),
                WOLF_BOSS_STAND,
                _compat_v2(),
            )
        )

    def test_v2_bucket_pass_allows_script_slot_without_force(self) -> None:
        """T-086: historical match is enough at pick; force is apply-side auto."""
        compat = {
            NORMAL_TRASH: {
                **(_compat_v2()[NORMAL_TRASH]),
                "force_donor_msb": False,
            }
        }
        self.assertIsNone(
            donor_slot_compat_reject_reason(
                _slot(collision_part="h000800", name="c4351_9000"),
                NORMAL_TRASH,
                compat,
            )
        )

    def test_script_chr_collision_allows_standing_swap_same_model(self) -> None:
        compat = {
            NORMAL_TRASH: {
                **(_compat_v2()[NORMAL_TRASH]),
                "vanilla_scan_model": "c4200",
                "donor_pose_label": "collision_anchor_no_backup",
                "vanilla_supported_buckets": [
                    "script_chr_activate",
                    "collision_perch",
                    "ground_stand",
                    "patrol",
                    "sit_squat",
                ],
                "force_donor_msb": True,
            }
        }
        self.assertIsNone(
            donor_slot_compat_reject_reason(
                _slot(
                    collision_part="h423700",
                    chr_activate=1000000003,
                    name="c4200_9000",
                    model="c4200",
                ),
                NORMAL_TRASH,
                compat,
            )
        )

    def test_script_patrol_flyer_allows_humanoid_when_historical(self) -> None:
        """T-089: flyer slot pairs as collision_perch; historical match allows."""
        compat = {
            NORMAL_TRASH: {
                **(_compat_v2()[NORMAL_TRASH]),
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
                _slot(
                    collision_part="h423700",
                    chr_activate=1000000003,
                    name="c4200_9000",
                    model="c4200",
                ),
                NORMAL_TRASH,
                compat,
                categories_cfg=_QUADRUPED_CFG,
            )
        )

    def test_script_patrol_flyer_allows_same_model_ground_stand_when_historical(
        self,
    ) -> None:
        compat = {
            "m60_43_52_00:c4200_9000": {
                "vanilla_scan_model": "c4200",
                "vanilla_supported_buckets": [
                    "collision_perch",
                    "script_chr_activate",
                    "ground_stand",
                    "patrol",
                ],
                "donor_pose_label": "ground_stand",
                "force_donor_msb": True,
            }
        }
        self.assertIsNone(
            donor_slot_compat_reject_reason(
                _slot(
                    collision_part="h423700",
                    chr_activate=1000000003,
                    name="c4200_9000",
                    model="c4200",
                ),
                "m60_43_52_00:c4200_9000",
                compat,
                categories_cfg=_QUADRUPED_CFG,
            )
        )

    def test_shade_boss_line_allowed_on_ground_stand_when_historical(self) -> None:
        """T-085: ground_stand ∈ historical → allow (no shade route stack)."""
        compat = {
            NORMAL_TRASH: {
                **(_compat_v2()[NORMAL_TRASH]),
                "vanilla_scan_model": "c5513",
                "donor_npc": 55130083,
                "donor_think": 55130900,
                "vanilla_supported_buckets": ["ground_stand", "patrol"],
                "force_donor_msb": False,
            }
        }
        self.assertIsNone(
            donor_slot_compat_reject_reason(
                _slot(name="c4311_9001", model="c4311"),
                NORMAL_TRASH,
                compat,
                categories_cfg=_QUADRUPED_CFG,
            )
        )

    def test_script_patrol_flyer_allows_flying_donor(self) -> None:
        compat = {
            NORMAL_TRASH: {
                **(_compat_v2()[NORMAL_TRASH]),
                "vanilla_scan_model": "c4560",
                "vanilla_supported_buckets": [
                    "collision_perch",
                    "script_chr_activate",
                    "aerial_slot",
                ],
                "force_donor_msb": True,
            }
        }
        cfg = dict(_QUADRUPED_CFG)
        cfg["flying_slot_model_prefixes"] = list(
            cfg.get("flying_slot_model_prefixes") or []
        ) + ["c4560"]
        self.assertIsNone(
            donor_slot_compat_reject_reason(
                _slot(
                    collision_part="h423700",
                    chr_activate=1000000003,
                    name="c4200_9000",
                    model="c4200",
                ),
                NORMAL_TRASH,
                compat,
                categories_cfg=cfg,
            )
        )

    def test_script_patrol_flyer_none_categories_does_not_crash(self) -> None:
        compat = {
            NORMAL_TRASH: {
                **(_compat_v2()[NORMAL_TRASH]),
                "vanilla_scan_model": "c4560",
                "vanilla_supported_buckets": [
                    "script_chr_activate",
                    "aerial_slot",
                ],
                "force_donor_msb": True,
            }
        }
        reason = donor_slot_compat_reject_reason(
            _slot(
                collision_part="h423700",
                chr_activate=1000000003,
                name="c4200_9000",
                model="c4200",
            ),
            NORMAL_TRASH,
            compat,
            categories_cfg=None,
        )
        self.assertTrue(reason is None or isinstance(reason, str))

    def test_sit_slot_rejects_oversized_c4550(self) -> None:
        compat = {
            NORMAL_TRASH: {
                **(_compat_v2()[NORMAL_TRASH]),
                "vanilla_scan_model": "c4550",
                "donor_pose_label": "sit_squat_backup_709",
                "vanilla_supported_buckets": ["sit_squat", "ground_stand"],
                "force_donor_msb": True,
            }
        }
        cfg = dict(_QUADRUPED_CFG)
        cfg["sit_slot_oversized_donor_model_prefixes"] = ["c4550"]
        self.assertEqual(
            donor_slot_compat_reject_reason(
                _slot(name="c4311_9000", backup_anim=704, model="c4311"),
                NORMAL_TRASH,
                compat,
                categories_cfg=cfg,
            ),
            "sit_slot_oversized_donor",
        )

    def test_standing_c4315_allowed_on_patrol_slot(self) -> None:
        self.assertIsNone(
            donor_slot_compat_reject_reason(
                _slot(walk_route="walk_route_c4310_9007_20", name="c4311_9010"),
                C4315_STAND,
                _compat_v2(),
                categories_cfg=_QUADRUPED_CFG,
            )
        )

    def test_standing_c5590_allowed_on_patrol_slot(self) -> None:
        self.assertIsNone(
            donor_slot_compat_reject_reason(
                _slot(walk_route="walk_route_c4310_9007_20", name="c4311_9005"),
                C5590_STAND,
                _compat_v2(),
                categories_cfg=_QUADRUPED_CFG,
            )
        )

    def test_standing_c5525_allowed_on_patrol_slot(self) -> None:
        self.assertIsNone(
            donor_slot_compat_reject_reason(
                _slot(walk_route="walk_route_c4310_9007_20", name="c4311_9005"),
                C5525_STAND,
                _compat_v2(),
                categories_cfg=_QUADRUPED_CFG,
            )
        )

    def test_standing_c6233_allowed_on_patrol_slot_no_profiles(self) -> None:
        self.assertIsNone(
            donor_slot_compat_reject_reason(
                _slot(walk_route="walk_route_c4310_9007_20", name="c4311_9005"),
                C6233_PAGE,
                _compat_v2(),
                categories_cfg=_QUADRUPED_CFG,
            )
        )

    def test_patrol_c5250_allowed_on_ground_stand_slot(self) -> None:
        self.assertIsNone(
            donor_slot_compat_reject_reason(
                _slot(name="c4200_9002"),
                C5250_PATROL,
                _compat_v2(),
                categories_cfg=_QUADRUPED_CFG,
            )
        )

    def test_collision_c3470_sit_allows_without_force(self) -> None:
        """T-086: sit + historical match no longer blocked by force at pick."""
        self.assertIsNone(
            donor_slot_compat_reject_reason(
                _slot(name="c4300_9003", backup_anim=700),
                C3470_COLLISION,
                _compat_v2(),
            )
        )

    def test_collision_c3470_allowed_on_sit_when_force(self) -> None:
        compat = {
            C3470_COLLISION: {
                **(_compat_v2()[C3470_COLLISION]),
                "force_donor_msb": True,
            }
        }
        self.assertIsNone(
            donor_slot_compat_reject_reason(
                _slot(name="c4300_9003", backup_anim=700),
                C3470_COLLISION,
                compat,
            )
        )


if __name__ == "__main__":
    unittest.main()

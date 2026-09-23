"""resolve_runtime_think — patrol slots use donor think; walk route is apply-time only."""

from __future__ import annotations

import unittest

from donor_vanilla_states import apply_patrol_runtime_alignment, build_model_vanilla_state_index
from enemy_randomizer_core import resolve_runtime_think

_QUADRUPED_CFG = {"quadruped_slot_model_prefixes": ["c3180", "c5525"]}


class ResolveRuntimeThinkTests(unittest.TestCase):
    def test_patrol_slot_uses_donor_think_not_slot_think(self) -> None:
        slot = {
            "walk_route": "walk_route_c4310_9007_20",
            "think": 43111200,
            "npc": 43111210,
        }
        template = {
            "think": 37030000,
            "npc": 62330082,
        }
        self.assertEqual(
            resolve_runtime_think(slot, template),
            62330000,
        )
        self.assertNotEqual(
            resolve_runtime_think(slot, template),
            43111200,
        )

    def test_patrol_slot_preserves_patrol_donor_think(self) -> None:
        slot = {
            "walk_route": "walk_route_c4310_9007_20",
            "think": 43111200,
            "npc": 43111210,
        }
        template = {
            "think": 31800020,
            "npc": 31800025,
            "walk_route": "walk_route_c3180_9002_6",
        }
        self.assertEqual(resolve_runtime_think(slot, template), 31800020)

    def test_standing_wolf_donor_aligns_to_vanilla_patrol_on_human_route(self) -> None:
        vanilla_slots = [
            {
                "model": "c3180",
                "walk_route": "walk_route_c3180_9002_6",
                "npc": 31800025,
                "think": 31800020,
            },
            {
                "model": "c3180",
                "walk_route": "walk_route_c3180_9003_6",
                "npc": 31800025,
                "think": 31800020,
            },
        ]
        model_index = build_model_vanilla_state_index(vanilla_slots)
        slot = {
            "walk_route": "walk_route_c4310_9007_20",
            "think": 43111200,
            "npc": 43111210,
        }
        template = {
            "model": "c3180",
            "think": 31800100,
            "npc": 31800100,
            "walk_route": "",
        }
        think = resolve_runtime_think(slot, template)
        npc, think = apply_patrol_runtime_alignment(
            slot,
            template,
            31800100,
            think,
            model_index,
            _QUADRUPED_CFG,
        )
        self.assertEqual(npc, 31800025)
        self.assertEqual(think, 31800020)

    def test_standing_wolf_boss_aligns_on_ground_stand_slot(self) -> None:
        vanilla_slots = [
            {
                "model": "c3180",
                "walk_route": "walk_route_c3180_9002_6",
                "npc": 31800025,
                "think": 31800020,
            },
        ]
        model_index = build_model_vanilla_state_index(vanilla_slots)
        slot = {"walk_route": "", "think": 43111100, "npc": 43111110}
        template = {
            "model": "c3180",
            "think": 31800100,
            "npc": 31800100,
            "walk_route": "",
        }
        think = resolve_runtime_think(slot, template)
        npc, think = apply_patrol_runtime_alignment(
            slot,
            template,
            31800100,
            think,
            model_index,
            _QUADRUPED_CFG,
        )
        self.assertEqual(npc, 31800025)
        self.assertEqual(think, 31800020)

    def test_boss_wolf_aligns_on_ground_even_when_donor_has_walk_route(self) -> None:
        vanilla_slots = [
            {
                "model": "c3180",
                "walk_route": "walk_route_c3180_9002_6",
                "npc": 31800025,
                "think": 31800020,
            },
        ]
        model_index = build_model_vanilla_state_index(vanilla_slots)
        slot = {"walk_route": "", "think": 43111100, "npc": 43111110}
        template = {
            "model": "c3180",
            "think": 31800100,
            "npc": 31800100,
            "walk_route": "walk_route_c3180_9002_6",
        }
        think = resolve_runtime_think(slot, template)
        npc, think = apply_patrol_runtime_alignment(
            slot,
            template,
            31800100,
            think,
            model_index,
            _QUADRUPED_CFG,
        )
        self.assertEqual(npc, 31800025)
        self.assertEqual(think, 31800020)

    def test_chariot_boss_line_aligns_on_ground_stand(self) -> None:
        vanilla_slots = [
            {
                "model": "c4460",
                "walk_route": "flame tank route A",
                "npc": 44607120,
                "think": 44600000,
            },
        ]
        model_index = build_model_vanilla_state_index(vanilla_slots)
        from donor_vanilla_states import apply_chariot_runtime_alignment

        slot = {"walk_route": "", "think": 43112100, "npc": 43112110}
        template = {
            "model": "c4460",
            "think": 44607800,
            "npc": 44607840,
            "walk_route": "",
        }
        think = resolve_runtime_think(slot, template)
        npc, think = apply_chariot_runtime_alignment(
            slot, template, 44607840, think, model_index
        )
        self.assertEqual(npc, 44607120)
        self.assertEqual(think, 44600000)

    def test_static_dog_boss_line_aligns_on_ground_stand(self) -> None:
        vanilla_slots = [
            {
                "model": "c4170",
                "walk_route": "",
                "npc": 41700000,
                "think": 41700000,
            },
            {
                "model": "c4170",
                "walk_route": "",
                "npc": 41700000,
                "think": 41700001,
            },
        ]
        model_index = build_model_vanilla_state_index(vanilla_slots)
        from donor_vanilla_states import apply_static_runtime_alignment

        slot = {"walk_route": "", "think": 43112100, "npc": 43112110}
        template = {
            "model": "c4170",
            "think": 41700100,
            "npc": 41700100,
            "walk_route": "",
        }
        think = resolve_runtime_think(slot, template)
        npc, think = apply_static_runtime_alignment(
            slot, template, 41700100, think, model_index
        )
        self.assertEqual(npc, 41700000)
        self.assertEqual(think, 41700000)

    def test_sanitize_inferred_static_think_aligns_on_ground_stand(self) -> None:
        vanilla_slots = [
            {
                "model": "c3000",
                "walk_route": "",
                "npc": 30000014,
                "think": 30000000,
            },
            {
                "model": "c3000",
                "walk_route": "",
                "npc": 30005051,
                "think": 30001000,
            },
        ]
        model_index = build_model_vanilla_state_index(vanilla_slots)
        from donor_vanilla_states import apply_static_runtime_alignment

        slot = {"walk_route": "", "think": 43112100, "npc": 43112110}
        template = {
            "model": "c3000",
            "think": 30001000,
            "npc": 30005051,
            "walk_route": "",
        }
        npc, think = apply_static_runtime_alignment(
            slot, template, 30005051, 30005000, model_index
        )
        self.assertEqual(npc, 30000014)
        self.assertEqual(think, 30000000)

    def test_vanilla_static_09xx_not_realigned(self) -> None:
        vanilla_slots = [
            {
                "model": "c3050",
                "walk_route": "",
                "npc": 30500140,
                "think": 30500940,
            },
        ]
        model_index = build_model_vanilla_state_index(vanilla_slots)
        from donor_vanilla_states import apply_static_runtime_alignment

        slot = {"walk_route": "", "think": 43112100, "npc": 43112110}
        template = {
            "model": "c3050",
            "think": 30500940,
            "npc": 30500140,
            "walk_route": "",
        }
        npc, think = apply_static_runtime_alignment(
            slot, template, 30500140, 30500940, model_index
        )
        self.assertEqual(npc, 30500140)
        self.assertEqual(think, 30500940)

    def test_script_patrol_flyer_preserves_flying_think(self) -> None:
        import json
        from pathlib import Path

        categories = json.loads(
            (Path(__file__).resolve().parents[1] / "enemy_categories.json").read_text(
                encoding="utf-8-sig"
            )
        )
        slot = {
            "model": "c4200",
            "chr_activate": 1000000003,
            "collision_part": "h423700",
            "walk_route": "",
            "backup_anim": -1,
        }
        template = {
            "model": "c4200",
            "think": 42000000,
            "npc": 42000083,
            "walk_route": "",
        }
        self.assertEqual(
            resolve_runtime_think(slot, template, categories_cfg=categories),
            42000000,
        )

    def test_patrol_npc_think_thousands_aligns_to_inferred(self) -> None:
        from donor_vanilla_states import resolve_slot_runtime_npc_and_think

        slot = {
            "walk_route": "walk_route_c3020_9005_51",
            "think": 30200000,
            "npc": 30200010,
        }
        template = {
            "model": "c5701",
            "think": 57001000,
            "npc": 57010083,
            "walk_route": "donor patrol",
        }
        _, think = resolve_slot_runtime_npc_and_think(
            slot, template, 57010083, None, {}
        )
        self.assertEqual(think, 57010000)

    def test_patrol_npc_think_thousands_prefers_matching_patrol_ref(self) -> None:
        from donor_vanilla_states import resolve_slot_runtime_npc_and_think

        vanilla_slots = [
            {
                "model": "c4470",
                "walk_route": "c4470 patrol",
                "npc": 44702000,
                "think": 44702000,
            },
        ]
        model_index = build_model_vanilla_state_index(vanilla_slots)
        slot = {
            "walk_route": "slot patrol",
            "think": 43111200,
            "npc": 43111210,
        }
        template = {
            "model": "c4470",
            "think": 44700000,
            "npc": 44702000,
            "walk_route": "donor patrol",
        }
        _, think = resolve_slot_runtime_npc_and_think(
            slot, template, 44702000, None, model_index
        )
        self.assertEqual(think, 44702000)

    def test_flyer_slot_skips_thousands_alignment(self) -> None:
        import json
        from pathlib import Path

        from donor_vanilla_states import resolve_slot_runtime_npc_and_think

        categories = json.loads(
            (Path(__file__).resolve().parents[1] / "enemy_categories.json").read_text(
                encoding="utf-8-sig"
            )
        )
        slot = {
            "model": "c4200",
            "chr_activate": 1000000003,
            "collision_part": "h423700",
            "walk_route": "",
            "backup_anim": -1,
        }
        template = {
            "model": "c4200",
            "think": 42000000,
            "npc": 42001150,
            "walk_route": "",
        }
        _, think = resolve_slot_runtime_npc_and_think(
            slot, template, 42001150, categories, {}
        )
        self.assertEqual(think, 42000000)

    def test_thousands_skips_inferred_think_missing_from_param(self) -> None:
        from donor_vanilla_states import resolve_slot_runtime_npc_and_think

        slot = {
            "walk_route": "",
            "think": 43110000,
            "npc": 43110010,
            "backup_anim": 704,
        }
        template = {
            "model": "c3703",
            "think": 37030000,
            "npc": 37031035,
            "walk_route": "",
        }
        _, think = resolve_slot_runtime_npc_and_think(
            slot, template, 37031035, None, {}
        )
        self.assertEqual(think, 37030000)

    def test_clamp_replaces_missing_inferred_think_with_donor(self) -> None:
        from donor_vanilla_states import clamp_runtime_think_to_param

        slot = {"walk_route": "", "backup_anim": 704}
        template = {
            "model": "c3703",
            "think": 37030000,
            "npc": 37031035,
        }
        _, think = clamp_runtime_think_to_param(
            slot, template, 37031035, 37031000, {}
        )
        self.assertEqual(think, 37030000)

    def test_clamp_synthetic_missing_think_falls_back_to_family_row(self) -> None:
        from donor_vanilla_states import clamp_runtime_think_to_param

        slot = {"walk_route": ""}
        template = {
            "model": "c6260",
            "think": 62601000,
            "npc": 62601000,
        }
        _, think = clamp_runtime_think_to_param(
            slot, template, 62601000, 62601000, {}
        )
        self.assertEqual(think, 62600000)


if __name__ == "__main__":
    unittest.main()

"""Boss-slot HP floor — re-exports from enemy_difficulty (T-053)."""

from enemy_difficulty import (
    BOSS_SLOT_SRC_CATEGORIES,
    REGION_HP_MULT,
    assignment_hp_override,
    boss_slot_hp_floor,
    effective_npc_hp,
    floor_base_hp_for_donor,
    npc_base_hp,
    region_hp_multiplier,
    sp_effect_ids,
)

__all__ = [
    "BOSS_SLOT_SRC_CATEGORIES",
    "REGION_HP_MULT",
    "assignment_hp_override",
    "boss_slot_hp_floor",
    "effective_npc_hp",
    "floor_base_hp_for_donor",
    "npc_base_hp",
    "region_hp_multiplier",
    "sp_effect_ids",
]

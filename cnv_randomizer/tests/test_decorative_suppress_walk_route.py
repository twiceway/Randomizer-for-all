"""T-082：有 walk_route 的假人不沉底；无路假人仍沉；马车事件图领队假人不沉。"""

from __future__ import annotations

from enemy_category_rules import is_caravan_event_slot
from enemy_randomizer_core import (
    build_decorative_suppress_assignments,
    is_decorative_suppress_slot,
    load_enemy_index,
    slot_has_walk_route,
)
from enemy_randomizer_core import _load_json, DEFAULT_CATEGORIES_PATH


def test_walk_route_dummy_not_suppressed():
    cfg = _load_json(DEFAULT_CATEGORIES_PATH)
    leader = {
        "map_id": "m60_42_37_00",
        "name": "c0100_9001",
        "model": "c0100",
        "npc": 1000000,
        "think": 1000000,
        "walk_route": "巡回ルート コウモリ大群",
    }
    assert slot_has_walk_route(leader)
    assert is_decorative_suppress_slot(leader, cfg) is False


def test_no_walk_dummy_still_suppressed():
    cfg = _load_json(DEFAULT_CATEGORIES_PATH)
    shell = {
        "map_id": "m60_42_37_00",
        "name": "c0100_9000",
        "model": "c0100",
        "npc": 10003000,
        "think": 1,
        "walk_route": "",
    }
    assert slot_has_walk_route(shell) is False
    assert is_decorative_suppress_slot(shell, cfg) is True


def test_gatefront_suppress_skips_bat_leader():
    cfg = _load_json(DEFAULT_CATEGORIES_PATH)
    index = load_enemy_index()
    rows = build_decorative_suppress_assignments(
        index, cfg, map_filter="m60_42_37_00"
    )
    names = {str(r["entity_name"]) for r in rows}
    assert "c0100_9001" not in names  # bat swarm leader
    assert "c0100_9002" not in names  # has walk
    assert "c0100_9003" not in names  # has walk
    assert "c0100_9000" in names  # no walk — still sink


def test_caravan_event_c0110_not_suppressed():
    cfg = _load_json(DEFAULT_CATEGORIES_PATH)
    hitch = {
        "map_id": "m60_11_09_02",
        "name": "m60_44_36_00-c0110_9000",
        "model": "c0110",
        "npc": 1100000,
        "think": 44000000,
        "walk_route": "",
    }
    assert slot_has_walk_route(hitch) is False
    assert is_decorative_suppress_slot(hitch, cfg) is False
    assert is_caravan_event_slot(hitch, cfg) is True


def test_caravan_event_c4600_kept_c4300_not_caravan_slot():
    cfg = _load_json(DEFAULT_CATEGORIES_PATH)
    giant = {
        "map_id": "m60_11_09_02",
        "name": "m60_44_36_00-c4600_9000",
        "model": "c4600",
        "npc": 46001010,
        "think": 46001000,
    }
    noble = {
        "map_id": "m60_11_09_02",
        "name": "m60_44_36_00-c4300_9011",
        "model": "c4300",
        "npc": 43001010,
        "think": 43001500,
    }
    soldier = {
        "map_id": "m60_11_09_02",
        "name": "m60_44_36_00-c4311_9001",
        "model": "c4311",
        "npc": 43110010,
        "think": 43110010,
    }
    assert is_caravan_event_slot(giant, cfg) is True
    assert is_caravan_event_slot(noble, cfg) is False
    assert is_caravan_event_slot(soldier, cfg) is False


def test_patrol_align_does_not_remap_to_cart_troll():
    """c4600 巡逻对齐共识常是拉车山妖；不得把可捐皮改成 never_donor 行。"""
    from donor_vanilla_states import (
        build_model_vanilla_state_index,
        resolve_slot_runtime_npc_and_think,
    )

    cfg = _load_json(DEFAULT_CATEGORIES_PATH)
    vanilla_slots = [
        {
            "model": "c4600",
            "walk_route": "cart patrol",
            "npc": 46001010,
            "think": 46001000,
        },
        {
            "model": "c4600",
            "walk_route": "cart patrol 2",
            "npc": 46001010,
            "think": 46001000,
        },
        {
            "model": "c4600",
            "walk_route": "other patrol",
            "npc": 46004200,
            "think": 46004000,
        },
    ]
    model_index = build_model_vanilla_state_index(vanilla_slots)
    slot = {"walk_route": "slot", "model": "c4340", "npc": 43400000, "think": 43400000}
    template = {
        "model": "c4600",
        "npc": 46004200,
        "think": 46004000,
        "walk_route": "donor patrol",
    }
    npc, think = resolve_slot_runtime_npc_and_think(
        slot, template, 46004200, cfg, model_index
    )
    assert npc == 46004200
    assert npc not in {46001010, 46001020, 46001030}

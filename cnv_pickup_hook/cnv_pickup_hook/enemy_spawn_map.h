#pragma once

#include <cstdint>
#include <cstddef>

namespace EnemySpawnMap {

struct DebugRow {
    char map_id[32];
    char entity_name[64];
    char template_id[128];
    char model[16];
    char placement[24];
    char walk_route[96];
    int npc = 0;
    int npc_donor = 0;
    int backup_anim = -1;
    float pos_x = 0.0f;
    float pos_y = 0.0f;
    float pos_z = 0.0f;
    bool has_pos = false;
};

struct SlotPosRow {
    char map_id[32];
    char entity_name[64];
    char model[16];
    float pos_x = 0.0f;
    float pos_y = 0.0f;
    float pos_z = 0.0f;
    int npc = 0;
};

bool Load(const char* path);
bool IsLoaded();
uint32_t Seed();
size_t EntryCount();
size_t DebugRowCount();

// Returns baked rune_delta (amount to ADD) for (map_id, entity_name); -1 if none.
int LookupRuneAmount(const char* map_id, const char* entity_name);

// Fallback when ChrIns modules are already cleared at EnemyIns dtor.
// Returns baked rune_delta for npc param id; -1 if unknown.
int LookupRuneAmountByNpc(int npc_param_id);

// True if spawn map tagged this runtime npc as Starscourge Radahn skin (c4730).
bool IsRadahnNpc(int npc_param_id);

// Debug HUD: all spawn rows matching runtime npc id (may be >1 if ambiguous).
size_t LookupDebugByNpc(int npc_param_id, DebugRow* out, size_t out_cap);

// Prefer single row when map_id is known.
bool LookupDebugByMapNpc(const char* map_id, int npc_param_id, DebugRow* out);

// map + runtime npc matches row.npc_donor (vanilla npc on ChrIns).
bool LookupDebugByMapDonorNpc(const char* map_id, int npc_param_id, DebugRow* out);

// Resolve spawn row by map + runtime npc (copy id, donor, or copy manifest).
bool LookupDebugResolved(const char* map_id, int npc_param_id, DebugRow* out);

// Nearest MSB slot on map (world pos ~= player chunk + target local).
bool LookupDebugNearestPos(
    const char* map_id,
    float world_x,
    float world_y,
    float world_z,
    float max_dist_m,
    DebugRow* out,
    float* out_dist_m = nullptr);

// Vanilla MSB slot positions (from cnv_enemy_debug_slots.txt).
bool LoadSlotIndex(const char* path);

// Spawn-map row for a known map + MSB slot name (model/skin/donor).
bool LookupDebugByMapSlot(const char* map_id, const char* entity_name, DebugRow* out);

// Copy manifest: copy npc id -> vanilla base npc id; 0 if unknown.
int LookupCopyBaseNpc(int copy_npc_id);

}  // namespace EnemySpawnMap

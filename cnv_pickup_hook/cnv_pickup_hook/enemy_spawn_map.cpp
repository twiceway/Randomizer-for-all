#include "enemy_spawn_map.h"

#include "globals.h"
#include "log.h"

#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <unordered_map>
#include <vector>

namespace EnemySpawnMap {

namespace {

// Values are rune_delta (amount to ADD on death), not absolute rune_amount.
std::unordered_map<std::string, int> g_entries;
std::unordered_map<int, int> g_by_npc;
std::unordered_map<int, bool> g_radahn_npcs;
std::vector<DebugRow> g_debug_rows;
std::vector<SlotPosRow> g_slot_pos_rows;
std::unordered_map<int, int> g_copy_to_base;
std::unordered_map<int, std::vector<int>> g_base_to_copies;
uint32_t g_seed = 0;
bool g_loaded = false;

std::string MakeKey(const char* map_id, const char* entity_name) {
    std::string key;
    if (map_id) {
        key.append(map_id);
    }
    key.push_back('\t');
    if (entity_name) {
        key.append(entity_name);
    }
    return key;
}

bool ParseUint(const char* text, uint32_t& out) {
    if (!text || !*text) {
        return false;
    }
    char* end = nullptr;
    const unsigned long long value = strtoull(text, &end, 10);
    if (end == text) {
        return false;
    }
    out = static_cast<uint32_t>(value);
    return true;
}

bool ParseInt(const char* text, int& out) {
    if (!text || !*text) {
        return false;
    }
    char* end = nullptr;
    const long value = strtol(text, &end, 10);
    if (end == text) {
        return false;
    }
    out = static_cast<int>(value);
    return true;
}

void RememberDelta(int npc_param_id, int delta, int& conflicts) {
    if (delta <= 0) {
        return;
    }
    if (npc_param_id <= 0) {
        return;
    }
    const auto it = g_by_npc.find(npc_param_id);
    if (it == g_by_npc.end()) {
        g_by_npc[npc_param_id] = delta;
    } else if (it->second != delta) {
        if (delta > it->second) {
            it->second = delta;
        }
        ++conflicts;
    }
}

void CopyField(char* dst, size_t dst_len, const char* src) {
    if (!dst || dst_len == 0) {
        return;
    }
    if (!src) {
        dst[0] = '\0';
        return;
    }
    strncpy_s(dst, dst_len, src, _TRUNCATE);
}

void RememberDebugRow(const char* map_id,
                      const char* entity_name,
                      const char* template_id,
                      const char* model,
                      int npc_param_id,
                      int npc_donor,
                      const char* placement,
                      const char* walk_route,
                      int backup_anim,
                      float pos_x,
                      float pos_y,
                      float pos_z,
                      bool has_pos) {
    if (npc_param_id <= 0) {
        return;
    }
    DebugRow row{};
    CopyField(row.map_id, sizeof(row.map_id), map_id);
    CopyField(row.entity_name, sizeof(row.entity_name), entity_name);
    CopyField(row.template_id, sizeof(row.template_id), template_id);
    CopyField(row.model, sizeof(row.model), model);
    CopyField(row.placement, sizeof(row.placement), placement);
    CopyField(row.walk_route, sizeof(row.walk_route), walk_route);
    row.npc = npc_param_id;
    row.npc_donor = npc_donor > 0 ? npc_donor : npc_param_id;
    row.backup_anim = backup_anim;
    row.pos_x = pos_x;
    row.pos_y = pos_y;
    row.pos_z = pos_z;
    row.has_pos = has_pos;
    g_debug_rows.push_back(row);
}

bool ParseFloat(const char* text, float& out) {
    if (!text || !*text) {
        return false;
    }
    char* end = nullptr;
    const float value = strtof(text, &end);
    if (end == text) {
        return false;
    }
    out = value;
    return true;
}

void UpsertDebugRowPosition(const char* map_id,
                              const char* entity_name,
                              float pos_x,
                              float pos_y,
                              float pos_z) {
    if (!map_id || !entity_name || !entity_name[0]) {
        return;
    }
    for (DebugRow& row : g_debug_rows) {
        if (_stricmp(row.map_id, map_id) == 0 && _stricmp(row.entity_name, entity_name) == 0) {
            row.pos_x = pos_x;
            row.pos_y = pos_y;
            row.pos_z = pos_z;
            row.has_pos = true;
            return;
        }
    }
}

const DebugRow* FindDebugRow(const char* map_id, const char* entity_name) {
    if (!map_id || !entity_name) {
        return nullptr;
    }
    for (const DebugRow& row : g_debug_rows) {
        if (_stricmp(row.map_id, map_id) == 0 && _stricmp(row.entity_name, entity_name) == 0) {
            return &row;
        }
    }
    return nullptr;
}

void RememberCopyPair(int copy_id, int base_npc) {
    if (copy_id <= 0 || base_npc <= 0) {
        return;
    }
    g_copy_to_base[copy_id] = base_npc;
    auto& copies = g_base_to_copies[base_npc];
    for (int existing : copies) {
        if (existing == copy_id) {
            return;
        }
    }
    copies.push_back(copy_id);
}

bool LoadNpcCopyManifest(const char* path) {
    if (!path || !path[0]) {
        return false;
    }
    FILE* file = nullptr;
    if (fopen_s(&file, path, "r") != 0 || !file) {
        return false;
    }
    int loaded = 0;
    int pending_copy = 0;
    char line[512];
    while (fgets(line, sizeof(line), file)) {
        char* copy_key = strstr(line, "\"copy_id\"");
        char* base_key = strstr(line, "\"base_npc\"");
        if (copy_key) {
            char* colon = strchr(copy_key, ':');
            if (colon) {
                ParseInt(colon + 1, pending_copy);
            }
            continue;
        }
        if (base_key && pending_copy > 0) {
            char* colon = strchr(base_key, ':');
            int base_npc = 0;
            if (colon && ParseInt(colon + 1, base_npc)) {
                RememberCopyPair(pending_copy, base_npc);
                ++loaded;
            }
            pending_copy = 0;
        }
    }
    fclose(file);
    LogLine("enemy spawn map: copy manifest %s pairs=%d", path, loaded);
    return loaded > 0;
}

void TryLoadSidecars(const char* spawn_map_path) {
    if (!spawn_map_path || !spawn_map_path[0]) {
        return;
    }
    std::string dir(spawn_map_path);
    const size_t slash = dir.find_last_of("\\/");
    if (slash == std::string::npos) {
        return;
    }
    dir.resize(slash + 1);

    const std::string slot_index = dir + "cnv_enemy_debug_slots.txt";
    LoadSlotIndex(slot_index.c_str());

    char manifest_name[128]{};
    FILE* spawn = nullptr;
    if (fopen_s(&spawn, spawn_map_path, "r") != 0 || !spawn) {
        return;
    }
    char line[768];
    while (fgets(line, sizeof(line), spawn)) {
        if (strncmp(line, "npc_soul_copies_manifest=", 25) == 0) {
            const char* value = line + 25;
            strncpy_s(manifest_name, sizeof(manifest_name), value, _TRUNCATE);
            char* nl = strchr(manifest_name, '\r');
            if (nl) {
                *nl = '\0';
            }
            nl = strchr(manifest_name, '\n');
            if (nl) {
                *nl = '\0';
            }
            break;
        }
    }
    fclose(spawn);
    if (!manifest_name[0]) {
        char seeded[128]{};
        snprintf(seeded, sizeof(seeded), "cnv_npc_soul_copies_%u.json", g_seed);
        LoadNpcCopyManifest((dir + seeded).c_str());
        return;
    }
    LoadNpcCopyManifest((dir + manifest_name).c_str());
}

}  // namespace

bool Load(const char* path) {
    g_entries.clear();
    g_by_npc.clear();
    g_radahn_npcs.clear();
    g_debug_rows.clear();
    g_slot_pos_rows.clear();
    g_copy_to_base.clear();
    g_base_to_copies.clear();
    g_seed = 0;
    g_loaded = false;

    FILE* file = nullptr;
    if (fopen_s(&file, path, "r") != 0 || !file) {
        LogLine("enemy spawn map: not found (%s)", path ? path : "(null)");
        return false;
    }

    int npc_conflicts = 0;
    int with_delta = 0;
    char line[768];
    while (fgets(line, sizeof(line), file)) {
        if (line[0] == '#' || line[0] == '\n' || line[0] == '\r') {
            continue;
        }

        char* eq = strchr(line, '=');
        if (eq) {
            *eq = '\0';
            const char* key = line;
            char* value = eq + 1;
            while (*value == ' ' || *value == '\t') {
                ++value;
            }
            char* nl = strchr(value, '\r');
            if (nl) {
                *nl = '\0';
            }
            nl = strchr(value, '\n');
            if (nl) {
                *nl = '\0';
            }
            if (strcmp(key, "seed") == 0) {
                ParseUint(value, g_seed);
            }
            continue;
        }

        char* nl = strchr(line, '\r');
        if (nl) {
            *nl = '\0';
        }
        nl = strchr(line, '\n');
        if (nl) {
            *nl = '\0';
        }
        if (!line[0]) {
            continue;
        }

        // map \t entity \t src \t tgt \t template \t model \t npc \t think \t chara \t rune
        // [\t engine_soul \t rune_delta \t npc_donor [\t placement \t walk_route \t backup_anim]]
        char* fields[16] = {};
        int nfields = 0;
        char* cursor = line;
        while (nfields < 16) {
            fields[nfields++] = cursor;
            char* tab = strchr(cursor, '\t');
            if (!tab) {
                break;
            }
            *tab = '\0';
            cursor = tab + 1;
        }
        if (nfields < 10) {
            continue;
        }

        const char* map_id = fields[0];
        const char* entity_name = fields[1];
        const char* template_id = fields[4];
        int npc_param_id = 0;
        int rune_amount = 0;
        if (!ParseInt(fields[6], npc_param_id) || !ParseInt(fields[9], rune_amount)) {
            continue;
        }

        int npc_donor = npc_param_id;
        if (nfields >= 13) {
            ParseInt(fields[12], npc_donor);
        }
        const char* placement = (nfields >= 14) ? fields[13] : "";
        const char* walk_route = (nfields >= 15) ? fields[14] : "";
        int backup_anim = -1;
        if (nfields >= 16) {
            ParseInt(fields[15], backup_anim);
        }
        float pos_x = 0.0f;
        float pos_y = 0.0f;
        float pos_z = 0.0f;
        bool has_pos = false;
        if (nfields >= 19) {
            has_pos = ParseFloat(fields[16], pos_x) && ParseFloat(fields[17], pos_y)
                      && ParseFloat(fields[18], pos_z);
        }
        RememberDebugRow(map_id,
                         entity_name,
                         template_id,
                         fields[5],
                         npc_param_id,
                         npc_donor,
                         placement,
                         walk_route,
                         backup_anim,
                         pos_x,
                         pos_y,
                         pos_z,
                         has_pos);

        // Tag Radahn skins for meteor hook (even when rune_delta==0).
        const char* model = fields[5];
        if (model && (_strnicmp(model, "c4730", 5) == 0) && npc_param_id > 0) {
            g_radahn_npcs[npc_param_id] = true;
        }
        if (nfields >= 13) {
            int npc_donor = 0;
            if (ParseInt(fields[12], npc_donor)
                && (npc_donor == 47300040 || npc_donor == 47300041)
                && npc_param_id > 0) {
                g_radahn_npcs[npc_param_id] = true;
            }
        }

        int rune_delta = 0;
        if (nfields >= 12) {
            if (!ParseInt(fields[11], rune_delta)) {
                rune_delta = 0;
            }
        } else if (nfields >= 11) {
            int engine_soul = 0;
            if (ParseInt(fields[10], engine_soul)) {
                if (engine_soul < 0) {
                    engine_soul = 0;
                }
                rune_delta = rune_amount - engine_soul;
            }
        } else {
            // Legacy rows: treat full rune_amount as delta (Boss getSoul=0 cases).
            // Trash with getSoul>0 may double-award until map is re-augmented.
            rune_delta = rune_amount;
        }
        if (rune_delta < 0) {
            rune_delta = 0;
        }
        if (rune_delta <= 0) {
            continue;
        }

        g_entries[MakeKey(map_id, entity_name)] = rune_delta;
        RememberDelta(npc_param_id, rune_delta, npc_conflicts);
        ++with_delta;
    }

    fclose(file);
    TryLoadSidecars(path);
    for (const SlotPosRow& slot : g_slot_pos_rows) {
        UpsertDebugRowPosition(slot.map_id, slot.entity_name, slot.pos_x, slot.pos_y, slot.pos_z);
    }
    g_loaded = !g_entries.empty() || !g_radahn_npcs.empty() || !g_debug_rows.empty()
               || !g_slot_pos_rows.empty();
    LogLine("enemy spawn map: %s entries=%zu delta_rows=%d npc_index=%zu debug_rows=%zu radahn_npcs=%zu conflicts=%d seed=%u",
            g_loaded ? "loaded" : "empty",
            g_entries.size(),
            with_delta,
            g_by_npc.size(),
            g_debug_rows.size(),
            g_radahn_npcs.size(),
            npc_conflicts,
            g_seed);
    return g_loaded;
}

bool IsLoaded() {
    return g_loaded;
}

uint32_t Seed() {
    return g_seed;
}

size_t EntryCount() {
    return g_entries.size();
}

size_t DebugRowCount() {
    return g_debug_rows.size();
}

int LookupRuneAmount(const char* map_id, const char* entity_name) {
    if (!map_id || !entity_name) {
        return -1;
    }
    const auto it = g_entries.find(MakeKey(map_id, entity_name));
    if (it == g_entries.end()) {
        return -1;
    }
    return it->second;
}

int LookupRuneAmountByNpc(int npc_param_id) {
    if (npc_param_id <= 0) {
        return -1;
    }
    const auto it = g_by_npc.find(npc_param_id);
    if (it == g_by_npc.end()) {
        return -1;
    }
    return it->second;
}

bool IsRadahnNpc(int npc_param_id) {
    if (npc_param_id <= 0) {
        return false;
    }
    if (npc_param_id == 47300040 || npc_param_id == 47300041) {
        return true;
    }
    return g_radahn_npcs.find(npc_param_id) != g_radahn_npcs.end();
}

size_t LookupDebugByNpc(int npc_param_id, DebugRow* out, size_t out_cap) {
    if (npc_param_id <= 0 || !out || out_cap == 0) {
        return 0;
    }
    size_t n = 0;
    for (const DebugRow& row : g_debug_rows) {
        if (row.npc != npc_param_id) {
            continue;
        }
        out[n++] = row;
        if (n >= out_cap) {
            break;
        }
    }
    return n;
}

bool LookupDebugByMapNpc(const char* map_id, int npc_param_id, DebugRow* out) {
    if (!map_id || !out || npc_param_id <= 0) {
        return false;
    }
    for (const DebugRow& row : g_debug_rows) {
        if (row.npc != npc_param_id) {
            continue;
        }
        if (_stricmp(row.map_id, map_id) != 0) {
            continue;
        }
        *out = row;
        return true;
    }
    return false;
}

bool LookupDebugByMapDonorNpc(const char* map_id, int npc_param_id, DebugRow* out) {
    if (!map_id || !out || npc_param_id <= 0) {
        return false;
    }
    for (const DebugRow& row : g_debug_rows) {
        if (row.npc_donor != npc_param_id) {
            continue;
        }
        if (_stricmp(row.map_id, map_id) != 0) {
            continue;
        }
        *out = row;
        return true;
    }
    return false;
}

bool LookupDebugResolved(const char* map_id, int npc_param_id, DebugRow* out) {
    if (!map_id || !out || npc_param_id <= 0) {
        return false;
    }
    if (LookupDebugByMapNpc(map_id, npc_param_id, out)) {
        return true;
    }
    if (LookupDebugByMapDonorNpc(map_id, npc_param_id, out)) {
        return true;
    }
    const auto copy_it = g_copy_to_base.find(npc_param_id);
    if (copy_it != g_copy_to_base.end()) {
        if (LookupDebugByMapDonorNpc(map_id, copy_it->second, out)) {
            return true;
        }
    }
    const auto base_it = g_base_to_copies.find(npc_param_id);
    if (base_it != g_base_to_copies.end()) {
        for (int copy_id : base_it->second) {
            if (LookupDebugByMapNpc(map_id, copy_id, out)) {
                return true;
            }
        }
    }
    DebugRow matches[16];
    const size_t n = LookupDebugByNpc(npc_param_id, matches, 16);
    if (n == 1) {
        *out = matches[0];
        return true;
    }
    if (n > 1) {
        for (size_t i = 0; i < n; ++i) {
            if (_stricmp(matches[i].map_id, map_id) == 0) {
                *out = matches[i];
                return true;
            }
        }
    }
    return false;
}

bool LookupDebugNearestPos(
    const char* map_id,
    float world_x,
    float world_y,
    float world_z,
    float max_dist_m,
    DebugRow* out,
    float* out_dist_m) {
    if (!map_id || !out || max_dist_m <= 0.0f) {
        return false;
    }
    const float max_dist_sq = max_dist_m * max_dist_m;
    const SlotPosRow* best_slot = nullptr;
    float best_dist_sq = max_dist_sq;
    for (const SlotPosRow& slot : g_slot_pos_rows) {
        if (_stricmp(slot.map_id, map_id) != 0) {
            continue;
        }
        const float dx = slot.pos_x - world_x;
        const float dy = slot.pos_y - world_y;
        const float dz = slot.pos_z - world_z;
        const float dist_sq = dx * dx + dy * dy + dz * dz;
        if (dist_sq > best_dist_sq) {
            continue;
        }
        best_dist_sq = dist_sq;
        best_slot = &slot;
    }
    if (!best_slot) {
        for (const DebugRow& row : g_debug_rows) {
            if (!row.has_pos || _stricmp(row.map_id, map_id) != 0) {
                continue;
            }
            const float dx = row.pos_x - world_x;
            const float dy = row.pos_y - world_y;
            const float dz = row.pos_z - world_z;
            const float dist_sq = dx * dx + dy * dy + dz * dz;
            if (dist_sq > best_dist_sq) {
                continue;
            }
            best_dist_sq = dist_sq;
            *out = row;
            if (out_dist_m) {
                *out_dist_m = sqrtf(best_dist_sq);
            }
            return true;
        }
        return false;
    }

    if (const DebugRow* row = FindDebugRow(map_id, best_slot->entity_name)) {
        *out = *row;
        if (!out->has_pos) {
            out->pos_x = best_slot->pos_x;
            out->pos_y = best_slot->pos_y;
            out->pos_z = best_slot->pos_z;
            out->has_pos = true;
        }
    } else {
        DebugRow built{};
        CopyField(built.map_id, sizeof(built.map_id), best_slot->map_id);
        CopyField(built.entity_name, sizeof(built.entity_name), best_slot->entity_name);
        CopyField(built.model, sizeof(built.model), best_slot->model);
        built.npc = best_slot->npc;
        built.npc_donor = best_slot->npc;
        built.pos_x = best_slot->pos_x;
        built.pos_y = best_slot->pos_y;
        built.pos_z = best_slot->pos_z;
        built.has_pos = true;
        *out = built;
    }
    if (out_dist_m) {
        *out_dist_m = sqrtf(best_dist_sq);
    }
    return true;
}

bool LookupDebugByMapSlot(const char* map_id, const char* entity_name, DebugRow* out) {
    const DebugRow* row = FindDebugRow(map_id, entity_name);
    if (!row || !out) {
        return false;
    }
    *out = *row;
    return true;
}

int LookupCopyBaseNpc(int copy_npc_id) {
    if (copy_npc_id <= 0) {
        return 0;
    }
    const auto it = g_copy_to_base.find(copy_npc_id);
    return it != g_copy_to_base.end() ? it->second : 0;
}

bool LoadSlotIndex(const char* path) {
    if (!path || !path[0]) {
        return false;
    }
    FILE* file = nullptr;
    if (fopen_s(&file, path, "r") != 0 || !file) {
        LogLine("enemy spawn map: slot index not found (%s)", path);
        return false;
    }
  g_slot_pos_rows.clear();
    int loaded = 0;
    char line[512];
    while (fgets(line, sizeof(line), file)) {
        if (line[0] == '#' || line[0] == '\n' || line[0] == '\r') {
            continue;
        }
        char* nl = strchr(line, '\r');
        if (nl) {
            *nl = '\0';
        }
        nl = strchr(line, '\n');
        if (nl) {
            *nl = '\0';
        }
        char* fields[8] = {};
        int nfields = 0;
        char* cursor = line;
        while (nfields < 8) {
            fields[nfields++] = cursor;
            char* tab = strchr(cursor, '\t');
            if (!tab) {
                break;
            }
            *tab = '\0';
            cursor = tab + 1;
        }
        if (nfields < 5) {
            continue;
        }
        float pos_x = 0.0f;
        float pos_y = 0.0f;
        float pos_z = 0.0f;
        if (!ParseFloat(fields[2], pos_x) || !ParseFloat(fields[3], pos_y)
            || !ParseFloat(fields[4], pos_z)) {
            continue;
        }
        SlotPosRow row{};
        CopyField(row.map_id, sizeof(row.map_id), fields[0]);
        CopyField(row.entity_name, sizeof(row.entity_name), fields[1]);
        row.pos_x = pos_x;
        row.pos_y = pos_y;
        row.pos_z = pos_z;
        if (nfields >= 6) {
            CopyField(row.model, sizeof(row.model), fields[5]);
        }
        if (nfields >= 7) {
            ParseInt(fields[6], row.npc);
        }
        g_slot_pos_rows.push_back(row);
        ++loaded;
    }
    fclose(file);
    LogLine("enemy spawn map: slot index loaded=%d path=%s", loaded, path);
    return loaded > 0;
}

}  // namespace EnemySpawnMap

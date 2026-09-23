#include "enemy_debug_shared.h"

#include "enemy_spawn_map.h"
#include "log.h"
#include "sigscan.h"

#include <cmath>
#include <cstdio>
#include <cstring>
#include <chrono>
#include <thread>

namespace enemy_debug_internal {
std::string GetDllDirectory() {
    char dll_path[MAX_PATH]{};
    HMODULE self = nullptr;
    if (!GetModuleHandleExA(
            GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            reinterpret_cast<LPCSTR>(&GetDllDirectory),
            &self)
        || !self
        || GetModuleFileNameA(self, dll_path, MAX_PATH) == 0) {
        return {};
    }
    char* slash = strrchr(dll_path, '\\');
    if (slash) {
        *slash = '\0';
    }
    return std::string(dll_path) + "\\";
}

void TrimAscii(char* text) {
    if (!text) {
        return;
    }
    size_t len = strlen(text);
    while (len > 0 && (text[len - 1] == '\r' || text[len - 1] == '\n' || text[len - 1] == ' ')) {
        text[--len] = '\0';
    }
    char* start = text;
    while (*start == ' ' || *start == '\t') {
        ++start;
    }
    if (start != text) {
        memmove(text, start, strlen(start) + 1);
    }
}

void RememberNpcEnglishName(int npc_id, const char* name, bool overwrite = false) {
    if (npc_id <= 0 || !name || !name[0]) {
        return;
    }
  const auto found = g_npc_en_names.find(npc_id);
    if (found != g_npc_en_names.end() && !overwrite) {
        return;
    }
    g_npc_en_names[npc_id] = name;
}

bool LoadNpcNamesCsv(const char* path) {
    if (!path || !path[0]) {
        return false;
    }
    FILE* file = nullptr;
    if (fopen_s(&file, path, "r") != 0 || !file) {
        return false;
    }
    char line[512];
    int loaded = 0;
    while (fgets(line, sizeof(line), file)) {
        TrimAscii(line);
        if (!line[0] || line[0] == '#') {
            continue;
        }
        char* comma = strchr(line, ',');
        if (!comma) {
            continue;
        }
        *comma = '\0';
        int npc_id = atoi(line);
        if (npc_id <= 0) {
            continue;
        }
        char* name = comma + 1;
        char* next = strchr(name, ',');
        if (next) {
            *next = '\0';
        }
        TrimAscii(name);
        if (!name[0]) {
            continue;
        }
        RememberNpcEnglishName(npc_id, name, true);
        ++loaded;
    }
    fclose(file);
    LogLine("enemy_debug: npc names csv %s rows=%d", path, loaded);
    return loaded > 0;
}

bool LoadNpcNamesParamdex(const char* path) {
    if (!path || !path[0]) {
        return false;
    }
    FILE* file = nullptr;
    if (fopen_s(&file, path, "r") != 0 || !file) {
        return false;
    }
    char line[512];
    int loaded = 0;
    while (fgets(line, sizeof(line), file)) {
        TrimAscii(line);
        if (!line[0] || line[0] == '#') {
            continue;
        }
        char* cursor = line;
        while (*cursor == ' ' || *cursor == '\t') {
            ++cursor;
        }
        int npc_id = 0;
        if (sscanf_s(cursor, "%d", &npc_id) != 1 || npc_id <= 0) {
            continue;
        }
        while (*cursor && *cursor != ' ' && *cursor != '\t') {
            ++cursor;
        }
        while (*cursor == ' ' || *cursor == '\t') {
            ++cursor;
        }
        if (!*cursor) {
            continue;
        }
        RememberNpcEnglishName(npc_id, cursor, false);
        ++loaded;
    }
    fclose(file);
    LogLine("enemy_debug: npc names paramdex %s rows=%d", path, loaded);
    return loaded > 0;
}

void LoadNpcEnglishNames() {
    if (g_npc_names_loaded) {
        return;
    }
    g_npc_names_loaded = true;
    const std::string dll_dir = GetDllDirectory();
    if (!dll_dir.empty()) {
        LoadNpcNamesCsv((dll_dir + "NpcParam.csv").c_str());
        const char* paramdex_paths[] = {
            "..\\..\\tools\\DSMSPortable\\Assets\\Paramdex\\ER\\Names\\NpcParam.txt",
            "..\\..\\tools\\DSMSPortable\\app\\Assets\\Paramdex\\ER\\Names\\NpcParam.txt",
        };
        for (const char* rel : paramdex_paths) {
            LoadNpcNamesParamdex((dll_dir + rel).c_str());
        }
    }
    LogLine("enemy_debug: npc english names total=%zu", g_npc_en_names.size());
}

const char* LookupNpcEnglishName(int npc_id) {
    if (npc_id <= 0) {
        return "";
    }
    const auto found = g_npc_en_names.find(npc_id);
    if (found != g_npc_en_names.end()) {
        return found->second.c_str();
    }
    const int base_npc = EnemySpawnMap::LookupCopyBaseNpc(npc_id);
    if (base_npc > 0) {
        const auto base_found = g_npc_en_names.find(base_npc);
        if (base_found != g_npc_en_names.end()) {
            return base_found->second.c_str();
        }
    }
    return "";
}

void FillNpcEnglishNames(MarkSnapshot& snap) {
    const char* runtime_name = LookupNpcEnglishName(snap.npc);
    if (runtime_name[0]) {
        snprintf(snap.npc_name_en, sizeof(snap.npc_name_en), "%s", runtime_name);
    }
    const char* donor_name = LookupNpcEnglishName(snap.donor_npc);
    if (donor_name[0]) {
        snprintf(snap.donor_name_en, sizeof(snap.donor_name_en), "%s", donor_name);
    }
}

void DumpPlayerProbe(void* player_ins) {
    FILE* file = nullptr;
    if (fopen_s(&file, "mod\\dll\\cnv_enemy_debug_probe.txt", "w") != 0 || !file) {
        g_last_probe_status = "probe: WRITE FAILED (check mod/dll)";
        LogLine("enemy_debug probe: fopen failed");
        return;
    }

    ++g_probe_dump_seq;
    int row_count = 0;
    int changed_count = 0;
    fprintf(file, "CNV enemy debug probe dump #%u\n", g_probe_dump_seq);
    fprintf(file, "hook_hits=%u patches=%u last_raw=%p last_npc=%d\n",
            g_capture_hits.load(std::memory_order_relaxed),
            g_lock_patch_count.load(std::memory_order_relaxed),
            g_last_raw_capture,
            g_last_raw_npc);

    if (!player_ins) {
        fprintf(file, "player: (null)\n");
        fclose(file);
        g_last_probe_status = "probe: dumped (no player yet)";
        LogLine("enemy_debug probe: wrote (no player)");
        return;
    }

    const uint64_t base = reinterpret_cast<uint64_t>(player_ins);
    fprintf(file, "player=%p\n", player_ins);

    auto write_chr_row = [&](uint32_t off, uint64_t raw, const char* tag) {
        if (!IsSanePtr(raw)) {
            return;
        }
        void* candidate = reinterpret_cast<void*>(raw);
        const int npc = ReadNpcParamId(candidate);
        if (!IsPlausibleNpcId(npc)) {
            return;
        }
        float x = 0.0f, y = 0.0f, z = 0.0f;
        const bool has_pos = ReadPos(candidate, x, y, z);
        fprintf(file,
                "%soff=0x%03X ptr=%p npc=%d enemy=%d pos=%s %.1f,%.1f,%.1f\n",
                tag,
                off,
                candidate,
                npc,
                IsEnemyChrIns(player_ins, candidate) ? 1 : 0,
                has_pos ? "ok" : "no",
                x,
                y,
                z);
        ++row_count;
    };

    if (g_probe_snapshot_valid) {
        fprintf(file, "=== CHANGED since previous F8 (want dog npc 55xxxxxx) ===\n");
        for (uint32_t off = kProbeScanStart; off <= kProbeScanEnd; off += 8) {
            const uint64_t raw = ReadU64(base + off);
            const size_t idx = (off - kProbeScanStart) / 8;
            const uint64_t prev = g_probe_snapshot[idx];
            if (raw == prev) {
                continue;
            }
            ++changed_count;
            fprintf(file, "CHANGED off=0x%03X was=%p now=%p\n",
                    off,
                    reinterpret_cast<void*>(prev),
                    reinterpret_cast<void*>(raw));
            write_chr_row(off, raw, "  ");
        }
        if (changed_count == 0) {
            fprintf(file, "(no pointer changes in 0x500-0x900)\n");
        }
    } else {
        fprintf(file, "=== BASELINE (step 1: do NOT lock) ===\n");
    }

    fprintf(file, "=== ALL enemy-like pointers ===\n");
    for (uint32_t off = kProbeScanStart; off <= kProbeScanEnd; off += 8) {
        write_chr_row(off, ReadU64(base + off), "");
    }

    for (uint32_t off = kProbeScanStart; off <= kProbeScanEnd; off += 8) {
        const size_t idx = (off - kProbeScanStart) / 8;
        g_probe_snapshot[idx] = ReadU64(base + off);
    }
    g_probe_snapshot_valid = true;

    fclose(file);
    char status[160];
    if (g_probe_dump_seq == 1) {
        snprintf(status,
                 sizeof(status),
                 "probe step1 OK (%d rows) - LOCK dog, press F8 again",
                 row_count);
    } else if (changed_count > 0) {
        snprintf(status,
                 sizeof(status),
                 "probe step2: %d offsets changed (see txt)",
                 changed_count);
    } else {
        snprintf(status,
                 sizeof(status),
                 "probe: no changes (%d rows) - lock dog first?",
                 row_count);
    }
    g_last_probe_status = status;
    LogLine("enemy_debug probe: dump#%u rows=%d changed=%d",
            g_probe_dump_seq,
            row_count,
            changed_count);
}

bool RegisterProbeHotkeys() {
    static bool registered = false;
    if (registered) {
        return true;
    }
    const BOOL f6_ok = RegisterHotKey(nullptr, kHotkeyMarkId, 0, kMarkVk);
    const BOOL f8_ok = RegisterHotKey(nullptr, kHotkeyProbeId, 0, kProbeVk);
    const BOOL f9_ok = RegisterHotKey(nullptr, kHotkeyProbeAltId, 0, kProbeVkAlt);
    LogLine("enemy_debug: RegisterHotKey F6=%d F8=%d F9=%d err=%lu",
            f6_ok ? 1 : 0,
            f8_ok ? 1 : 0,
            f9_ok ? 1 : 0,
            GetLastError());
    registered = f6_ok || f8_ok || f9_ok;
    return registered;
}

void InferModelFromSlotName(const char* entity_name, char* out, size_t out_len) {
    if (!entity_name || !entity_name[0] || !out || out_len == 0) {
        return;
    }
    const char* underscore = strchr(entity_name, '_');
    if (!underscore || underscore == entity_name) {
        snprintf(out, out_len, "%s", entity_name);
        return;
    }
    size_t prefix_len = static_cast<size_t>(underscore - entity_name);
    if (prefix_len >= out_len) {
        prefix_len = out_len - 1;
    }
    memcpy(out, entity_name, prefix_len);
    out[prefix_len] = '\0';
}

void MergeDebugRowIntoSnapshot(MarkSnapshot& snap, const EnemySpawnMap::DebugRow& row) {
    if (!snap.entity_name[0] && row.entity_name[0]) {
        snprintf(snap.entity_name, sizeof(snap.entity_name), "%s", row.entity_name);
    }
    if (!snap.model[0] && row.model[0]) {
        snprintf(snap.model, sizeof(snap.model), "%s", row.model);
    }
    if (!snap.template_id[0] && row.template_id[0]) {
        snprintf(snap.template_id, sizeof(snap.template_id), "%s", row.template_id);
    }
    if (snap.donor_npc <= 0 && row.npc_donor > 0) {
        snap.donor_npc = row.npc_donor;
    }
    if ((!snap.placement[0] || snap.placement[0] == '-') && row.placement[0]) {
        snprintf(snap.placement, sizeof(snap.placement), "%s", PlacementLabel(row));
    }
    if (!snap.walk_route[0] && row.walk_route[0]) {
        snprintf(snap.walk_route, sizeof(snap.walk_route), "%s", row.walk_route);
    }
    if (snap.backup_anim < 0 && row.backup_anim >= 0) {
        snap.backup_anim = row.backup_anim;
    }
}

void CopyDebugRowToSnapshot(MarkSnapshot& snap, const EnemySpawnMap::DebugRow& row) {
    snprintf(snap.entity_name, sizeof(snap.entity_name), "%s", row.entity_name);
    snprintf(snap.model, sizeof(snap.model), "%s", row.model);
    snprintf(snap.template_id, sizeof(snap.template_id), "%s", row.template_id);
    snap.donor_npc = row.npc_donor;
    snprintf(snap.placement, sizeof(snap.placement), "%s", PlacementLabel(row));
    snprintf(snap.walk_route, sizeof(snap.walk_route), "%s", row.walk_route);
    snap.backup_anim = row.backup_anim;
}

void EnrichMarkSnapshot(MarkSnapshot& snap, bool for_mark) {
    EnemySpawnMap::DebugRow full{};
    if (snap.map_name[0] && snap.entity_name[0]
        && EnemySpawnMap::LookupDebugByMapSlot(snap.map_name, snap.entity_name, &full)) {
        MergeDebugRowIntoSnapshot(snap, full);
    }
    if (snap.donor_npc <= 0) {
        const int copy_base = EnemySpawnMap::LookupCopyBaseNpc(snap.npc);
        if (copy_base > 0) {
            snap.donor_npc = copy_base;
        }
    }
    if (!for_mark && !snap.model[0] && snap.entity_name[0]) {
        InferModelFromSlotName(snap.entity_name, snap.model, sizeof(snap.model));
    }
}

static void SetMarkTrust(MarkSnapshot& snap, const char* resolve_label) {
    if (!resolve_label || !resolve_label[0]) {
        snprintf(snap.mark_trust, sizeof(snap.mark_trust), "unresolved");
        return;
    }
    if (_stricmp(resolve_label, "spawn_map") == 0 || _stricmp(resolve_label, "npc_map") == 0
        || _stricmp(resolve_label, "npc_only") == 0) {
        snprintf(snap.mark_trust, sizeof(snap.mark_trust), "ok");
        return;
    }
    if (_stricmp(resolve_label, "nearest") == 0 || _stricmp(resolve_label, "nearest_alt") == 0) {
        snprintf(snap.mark_trust, sizeof(snap.mark_trust), "weak_pos");
        return;
    }
    snprintf(snap.mark_trust, sizeof(snap.mark_trust), "weak");
}

void MergeResolvedSpawnRow(const char* map_name, EnemySpawnMap::DebugRow& map_row) {
    if (!map_name || !map_name[0] || !map_row.entity_name[0]) {
        return;
    }
    EnemySpawnMap::DebugRow full{};
    if (!EnemySpawnMap::LookupDebugByMapSlot(map_name, map_row.entity_name, &full)) {
        return;
    }
    if (!map_row.model[0] && full.model[0]) {
        snprintf(map_row.model, sizeof(map_row.model), "%s", full.model);
    }
    if (!map_row.template_id[0] && full.template_id[0]) {
        snprintf(map_row.template_id, sizeof(map_row.template_id), "%s", full.template_id);
    }
    if (map_row.npc_donor <= 0 && full.npc_donor > 0) {
        map_row.npc_donor = full.npc_donor;
    }
    if (!map_row.placement[0] && full.placement[0]) {
        snprintf(map_row.placement, sizeof(map_row.placement), "%s", full.placement);
    }
    if (!map_row.walk_route[0] && full.walk_route[0]) {
        snprintf(map_row.walk_route, sizeof(map_row.walk_route), "%s", full.walk_route);
    }
    if (map_row.backup_anim < 0 && full.backup_anim >= 0) {
        map_row.backup_anim = full.backup_anim;
    }
    if (map_row.npc <= 0 && full.npc > 0) {
        map_row.npc = full.npc;
    }
}

MarkSnapshot BuildMarkSnapshotFromLockOn(
    void* player_ins,
    void* target_chr,
    SlotResolvePolicy policy,
    const char* mark_source) {
    MarkSnapshot snap{};
    if (!player_ins || !target_chr) {
        return snap;
    }
    snap.valid = true;
    snap.npc = ReadNpcParamId(target_chr);
    if (!ReadPos(target_chr, snap.target_x, snap.target_y, snap.target_z)) {
        if (void* pos_chr = FindChrWithPosForNpc(player_ins, target_chr, snap.npc)) {
            ReadPos(pos_chr, snap.target_x, snap.target_y, snap.target_z);
        }
    }
    ReadPos(player_ins, snap.player_lx, snap.player_ly, snap.player_lz);

    const uint64_t pbase = reinterpret_cast<uint64_t>(player_ins);
    const uint32_t map_raw = ReadU32(pbase + g_map_id_off);
    FormatMapId(map_raw, snap.map_name, sizeof(snap.map_name));
    snap.chunk_x = ReadF32(pbase + g_map_id_off - 16);
    snap.chunk_y = ReadF32(pbase + g_map_id_off - 12);
    snap.chunk_z = ReadF32(pbase + g_map_id_off - 8);

    EnemySpawnMap::DebugRow map_row{};
    const bool resolved = ResolveLockOnDebugRow(
        player_ins,
        target_chr,
        &map_row,
        &snap.slot_dist_m,
        snap.slot_resolve,
        sizeof(snap.slot_resolve),
        policy);
    if (resolved) {
        MergeResolvedSpawnRow(snap.map_name, map_row);
        CopyDebugRowToSnapshot(snap, map_row);
        snap.spawn_npc = map_row.npc;
        if (snap.spawn_npc > 0) {
            snap.npc = snap.spawn_npc;
        }
    }
    SetMarkTrust(snap, snap.slot_resolve);
    if (mark_source && mark_source[0]) {
        snprintf(snap.mark_source, sizeof(snap.mark_source), "%s", mark_source);
    }
    EnrichMarkSnapshot(snap, false);
    if (snap.donor_npc <= 0) {
        const int copy_base = EnemySpawnMap::LookupCopyBaseNpc(snap.npc);
        if (copy_base > 0) {
            snap.donor_npc = copy_base;
        }
    }
    if (!EstimateEnemyWorldPos(player_ins, target_chr, snap.world_x, snap.world_y, snap.world_z)) {
        if (void* pos_chr = FindChrWithPosForNpc(player_ins, target_chr, snap.npc)) {
            EstimateEnemyWorldPos(player_ins, pos_chr, snap.world_x, snap.world_y, snap.world_z);
        }
    }
    if (snap.spawn_npc > 0) {
        snap.npc = snap.spawn_npc;
    }
    FillNpcEnglishNames(snap);
    return snap;
}

int AuthoritativeMarkNpc(const MarkSnapshot& snap) {
    return snap.spawn_npc > 0 ? snap.spawn_npc : snap.npc;
}

void RefreshHudLockCache(void* player_ins, void* target_chr) {
    if (!player_ins || !target_chr) {
        g_hud_lock_cache.valid = false;
        return;
    }
    g_hud_lock_cache.snap =
        BuildMarkSnapshotFromLockOn(player_ins, target_chr, SlotResolvePolicy::Hud, "f7_hud");
    g_hud_lock_cache.valid =
        g_hud_lock_cache.snap.valid && AuthoritativeMarkNpc(g_hud_lock_cache.snap) > 0;
    g_hud_lock_cache.npc = AuthoritativeMarkNpc(g_hud_lock_cache.snap);
    g_hud_lock_cache.tick_ms = GetTickCount64();
}

void AppendUtf8Line(std::string& out, const char* line) {
    if (!line) {
        return;
    }
    if (!out.empty()) {
        out.push_back('\n');
    }
    out.append(line);
}

std::string BuildDebugText(void* player_ins, void* target_chr) {
    std::string text;
    AppendUtf8Line(text, g_hud_enabled.load() ? "[CNV enemy debug  F7=ON]" : "[CNV enemy debug  F7=off]");
    AppendUtf8Line(text, g_last_probe_status.c_str());
    AppendUtf8Line(text, "keys: F7=HUD | F6=mark+log | F8=probe");

    char line[512];
    if (!player_ins) {
        AppendUtf8Line(text, "player: (not in world yet)");
    } else {
        const uint64_t pbase = reinterpret_cast<uint64_t>(player_ins);
        const uint32_t map_raw = ReadU32(pbase + g_map_id_off);
        char map_name[32];
        FormatMapId(map_raw, map_name, sizeof(map_name));

        const float cx = ReadF32(pbase + g_map_id_off - 16);
        const float cy = ReadF32(pbase + g_map_id_off - 12);
        const float cz = ReadF32(pbase + g_map_id_off - 8);

        float lx = 0.0f, ly = 0.0f, lz = 0.0f;
        const bool has_local = ReadPos(player_ins, lx, ly, lz);

        snprintf(line,
                 sizeof(line),
                 "map: %s  (raw=0x%08X)",
                 map_name,
                 map_raw);
        AppendUtf8Line(text, line);

        if (has_local) {
            snprintf(line, sizeof(line), "pos local: %.1f, %.1f, %.1f", lx, ly, lz);
        } else {
            snprintf(line, sizeof(line), "pos local: (read failed)");
        }
        AppendUtf8Line(text, line);

        snprintf(line, sizeof(line), "chunk: %.1f, %.1f, %.1f", cx, cy, cz);
        AppendUtf8Line(text, line);

        snprintf(line,
                 sizeof(line),
                 "lock hook: %s  patches=%u off=0x%X",
                 kEnableLockCapturePatch
                     ? (g_lock_capture_installed ? "capture rax" : "MISS")
                     : "OFF safe",
                 g_lock_patch_count.load(std::memory_order_relaxed),
                 g_lock_target_off);
        AppendUtf8Line(text, line);

        snprintf(line,
                 sizeof(line),
                 "game lock: %s  (LockTgtMan)",
                 IsGameLockOnFlagSet() ? "ON" : "OFF");
        AppendUtf8Line(text, line);

        snprintf(line,
                 sizeof(line),
                 "probe: hook_hits=%u  last_raw=%p npc=%d",
                 g_capture_hits.load(std::memory_order_relaxed),
                 g_last_raw_capture,
                 g_last_raw_npc);
        AppendUtf8Line(text, line);

        int poll_npc = 0;
        void* poll_ptr = PollLockAtOffset(player_ins, g_lock_target_off, &poll_npc);
        snprintf(line,
                 sizeof(line),
                 "probe: poll@0x%X=%p npc=%d",
                 g_lock_target_off,
                 poll_ptr,
                 poll_npc);
        AppendUtf8Line(text, line);
    }

    if (!target_chr) {
        AppendUtf8Line(text, "lock-on: (none) - lock enemy to see slot/skin");
        return text;
    }

    const int npc = ReadNpcParamId(target_chr);
    float tx = 0.0f, ty = 0.0f, tz = 0.0f;
    const bool has_target_pos = ReadPos(target_chr, tx, ty, tz);
    const char* npc_en = LookupNpcEnglishName(npc);
    snprintf(line,
             sizeof(line),
             "lock-on npc=%d (%s)  chr=%p",
             npc,
             npc_en[0] ? npc_en : "-",
             target_chr);
    AppendUtf8Line(text, line);
    if (has_target_pos) {
        snprintf(line, sizeof(line), "target pos: %.1f, %.1f, %.1f", tx, ty, tz);
        AppendUtf8Line(text, line);
    }

    EnemySpawnMap::DebugRow map_row{};
    char map_name[32] = {};
    float slot_dist_m = -1.0f;
    char slot_resolve[24] = {};
    if (player_ins) {
        const uint32_t map_raw = ReadU32(reinterpret_cast<uint64_t>(player_ins) + g_map_id_off);
        FormatMapId(map_raw, map_name, sizeof(map_name));
    }
    if (ResolveLockOnDebugRow(
            player_ins, target_chr, &map_row, &slot_dist_m, slot_resolve, sizeof(slot_resolve))) {
        MergeResolvedSpawnRow(map_name, map_row);
        snprintf(line, sizeof(line), "slot: %s", map_row.entity_name);
        AppendUtf8Line(text, line);
        if (slot_resolve[0]) {
            snprintf(line,
                     sizeof(line),
                     "slot_resolve: %s  dist=%.1fm",
                     slot_resolve,
                     slot_dist_m >= 0.0f ? slot_dist_m : 0.0f);
            AppendUtf8Line(text, line);
        }
        snprintf(line,
                 sizeof(line),
                 "model=%s  donor_npc=%d (%s)",
                 map_row.model,
                 map_row.npc_donor,
                 LookupNpcEnglishName(map_row.npc_donor)[0] ? LookupNpcEnglishName(map_row.npc_donor) : "-");
        AppendUtf8Line(text, line);
        if (map_row.npc > 0 && map_row.npc != npc) {
            snprintf(line,
                     sizeof(line),
                     "spawn_npc=%d (%s)",
                     map_row.npc,
                     LookupNpcEnglishName(map_row.npc)[0] ? LookupNpcEnglishName(map_row.npc) : "-");
            AppendUtf8Line(text, line);
        }
        snprintf(line, sizeof(line), "skin: %s", map_row.template_id);
        AppendUtf8Line(text, line);
        snprintf(line,
                 sizeof(line),
                 "state: %s  walk=%s  backup=%d",
                 PlacementLabel(map_row),
                 map_row.walk_route[0] ? map_row.walk_route : "-",
                 map_row.backup_anim);
        AppendUtf8Line(text, line);
        RefreshHudLockCache(player_ins, target_chr);
        return text;
    }

    if (map_name[0]) {
        snprintf(line, sizeof(line), "spawn map: (no slot for npc=%d on %s)", npc, map_name);
    } else {
        snprintf(line, sizeof(line), "spawn map: (no slot for npc=%d)", npc);
    }
    AppendUtf8Line(text, line);
    return text;
}

void RunProbeDump() {
    DumpPlayerProbe(GetPlayerIns());
    if (g_hud_enabled.load()) {
        void* player = GetPlayerIns();
        const std::string text = BuildDebugText(player, GetLockOnTarget(player));
        SetOverlayText(text);
    }
}

std::wstring AsciiToWide(const std::string& text) {
    std::wstring out;
    out.reserve(text.size());
    for (unsigned char c : text) {
        out.push_back(static_cast<wchar_t>(c));
    }
    return out;
}

std::string WideToUtf8(const std::wstring& text) {
    if (text.empty()) {
        return {};
    }
    const int needed = WideCharToMultiByte(
        CP_UTF8, 0, text.c_str(), -1, nullptr, 0, nullptr, nullptr);
    if (needed <= 1) {
        return {};
    }
    std::string out(static_cast<size_t>(needed - 1), '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.c_str(), -1, &out[0], needed, nullptr, nullptr);
    return out;
}

std::string ResolveMarkLogPath() {
    static const char* kDefaultRoot = "V:\\1_mel\\Ringrandom";
    char dll_path[MAX_PATH]{};
    HMODULE self = nullptr;
    if (GetModuleHandleExA(
            GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            reinterpret_cast<LPCSTR>(&ResolveMarkLogPath),
            &self)
        && self
        && GetModuleFileNameA(self, dll_path, MAX_PATH) > 0) {
        char* slash = strrchr(dll_path, '\\');
        if (slash) {
            *slash = '\0';
        }
        char root_file[MAX_PATH]{};
        snprintf(root_file, sizeof(root_file), "%s\\cnv_repo_root.txt", dll_path);
        FILE* root_fp = nullptr;
        if (fopen_s(&root_fp, root_file, "r") == 0 && root_fp) {
            char root[MAX_PATH]{};
            if (fgets(root, sizeof(root), root_fp)) {
                fclose(root_fp);
                size_t len = strlen(root);
                while (len > 0 && (root[len - 1] == '\n' || root[len - 1] == '\r')) {
                    root[--len] = '\0';
                }
                if (root[0]) {
                    std::string log_path = std::string(root) + "\\cnv_enemy_mark_log.txt";
                    return log_path;
                }
            } else {
                fclose(root_fp);
            }
        }
    }
    return std::string(kDefaultRoot) + "\\cnv_enemy_mark_log.txt";
}

void AppendMarkLogLine(const std::string& line) {
    const std::string path = ResolveMarkLogPath();
    FILE* file = nullptr;
    if (fopen_s(&file, path.c_str(), "a") != 0 || !file) {
        LogLine("enemy_debug: mark log open failed path=%s err=%lu", path.c_str(), GetLastError());
        return;
    }
    SYSTEMTIME st{};
    GetLocalTime(&st);
    fprintf(file,
            "[%04u-%02u-%02u %02u:%02u:%02u] %s\n",
            st.wYear,
            st.wMonth,
            st.wDay,
            st.wHour,
            st.wMinute,
            st.wSecond,
            line.c_str());
    fclose(file);
    LogLine("enemy_debug: mark saved -> %s", path.c_str());
}

MarkSnapshot CaptureMarkSnapshot(void* player_ins, void* target_chr) {
    return BuildMarkSnapshotFromLockOn(
        player_ins, target_chr, SlotResolvePolicy::Hud, "f6_live");
}

std::string BuildMarkLogLine(const MarkSnapshot& snap, const std::string& note_utf8) {
    char buf[1024];
    snprintf(buf,
             sizeof(buf),
             "note=%s | map=%s | slot=%s | slot_via=%s | slot_dist=%.1fm | mark_trust=%s | "
             "mark_source=%s | npc=%d | npc_en=%s | spawn_npc=%d | model=%s | skin=%s | "
             "donor_npc=%d | donor_en=%s | placement=%s | walk=%s | backup=%d | target_pos=(%.1f,%.1f,%.1f) | "
             "world_est=(%.1f,%.1f,%.1f) | player_local=(%.1f,%.1f,%.1f) | chunk=(%.1f,%.1f,%.1f)",
             note_utf8.c_str(),
             snap.map_name,
             snap.entity_name[0] ? snap.entity_name : "?",
             snap.slot_resolve[0] ? snap.slot_resolve : "-",
             snap.slot_dist_m >= 0.0f ? snap.slot_dist_m : -1.0f,
             snap.mark_trust[0] ? snap.mark_trust : "unresolved",
             snap.mark_source[0] ? snap.mark_source : "-",
             snap.npc,
             snap.npc_name_en[0] ? snap.npc_name_en : "-",
             snap.spawn_npc,
             snap.model[0] ? snap.model : "?",
             snap.template_id[0] ? snap.template_id : "?",
             snap.donor_npc,
             snap.donor_name_en[0] ? snap.donor_name_en : "-",
             snap.placement[0] ? snap.placement : "-",
             snap.walk_route[0] ? snap.walk_route : "-",
             snap.backup_anim,
             snap.target_x,
             snap.target_y,
             snap.target_z,
             snap.world_x,
             snap.world_y,
             snap.world_z,
             snap.player_lx,
             snap.player_ly,
             snap.player_lz,
             snap.chunk_x,
             snap.chunk_y,
             snap.chunk_z);
    return std::string(buf);
}

LRESULT CALLBACK MarkDialogWndProc(HWND hwnd, UINT msg, WPARAM wparam, LPARAM lparam) {
    switch (msg) {
        case WM_COMMAND:
            if (LOWORD(wparam) == kMarkOkId) {
                HWND edit = GetDlgItem(hwnd, kMarkEditId);
                if (edit) {
                    GetDlgItemTextW(hwnd, kMarkEditId, g_mark_note_wide, 512);
                }
                g_mark_note_accepted = true;
                DestroyWindow(hwnd);
                return 0;
            }
            if (LOWORD(wparam) == kMarkCancelId) {
                g_mark_note_accepted = false;
                DestroyWindow(hwnd);
                return 0;
            }
            break;
        case WM_CLOSE:
            g_mark_note_accepted = false;
            DestroyWindow(hwnd);
            return 0;
        case WM_DESTROY:
            g_mark_dialog_hwnd = nullptr;
            return 0;
        default:
            break;
    }
    return DefWindowProcW(hwnd, msg, wparam, lparam);
}

void RunMarkDialogModal() {
    void* player = GetPlayerIns();
    void* target = GetLockOnTarget(player);
    if (!target) {
        g_last_probe_status = "mark: lock an enemy first (F6)";
        LogLine("enemy_debug: mark aborted (no lock target)");
        return;
    }

    const int live_npc = ReadNpcParamId(target);
    const ULONGLONG now = GetTickCount64();
    if (g_hud_lock_cache.valid && g_hud_lock_cache.npc > 0 && g_hud_lock_cache.npc == live_npc
        && (now - g_hud_lock_cache.tick_ms) <= kHudLockCacheMaxAgeMs) {
        g_mark_snapshot = g_hud_lock_cache.snap;
        snprintf(g_mark_snapshot.mark_source, sizeof(g_mark_snapshot.mark_source), "f7_cache");
        g_last_probe_status = "mark: using F7 HUD snapshot";
    } else if (g_hud_enabled.load()) {
        g_mark_snapshot = BuildMarkSnapshotFromLockOn(player, target, SlotResolvePolicy::Hud, "f7_live");
        g_last_probe_status = "mark: F7 on, live snapshot";
    } else {
        g_mark_snapshot = BuildMarkSnapshotFromLockOn(player, target, SlotResolvePolicy::Hud, "f6_no_hud");
        g_last_probe_status = "mark: turn F7 ON first for reliable mark";
        LogLine("enemy_debug: mark without recent F7 cache npc=%d", live_npc);
    }

    g_mark_note_wide[0] = L'\0';
    g_mark_note_accepted = false;

    static const wchar_t* kMarkClass = L"CNVEnemyMarkDlg";
    static bool class_registered = false;
    if (!class_registered) {
        WNDCLASSEXW wc{};
        wc.cbSize = sizeof(wc);
        wc.lpfnWndProc = MarkDialogWndProc;
        wc.hInstance = GetModuleHandleW(nullptr);
        wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
        wc.hbrBackground = reinterpret_cast<HBRUSH>(COLOR_WINDOW + 1);
        wc.lpszClassName = kMarkClass;
        RegisterClassExW(&wc);
        class_registered = true;
    }

    const int dlg_w = 460;
    const int dlg_h = 180;
    RECT desk{};
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &desk, 0);
    const int x = desk.left + ((desk.right - desk.left) - dlg_w) / 2;
    const int y = desk.top + ((desk.bottom - desk.top) - dlg_h) / 3;

    g_mark_dialog_hwnd = CreateWindowExW(
        WS_EX_TOPMOST | WS_EX_DLGMODALFRAME,
        kMarkClass,
        L"CNV Mark Locked Enemy",
        WS_POPUP | WS_CAPTION | WS_SYSMENU,
        x,
        y,
        dlg_w,
        dlg_h,
        nullptr,
        nullptr,
        GetModuleHandleW(nullptr),
        nullptr);
    if (!g_mark_dialog_hwnd) {
        LogLine("enemy_debug: mark dialog create failed err=%lu", GetLastError());
        return;
    }

    CreateWindowExW(
        0,
        L"STATIC",
        L"Note (long-hair / bald / frozen):",
        WS_CHILD | WS_VISIBLE,
        12,
        12,
        430,
        22,
        g_mark_dialog_hwnd,
        nullptr,
        GetModuleHandleW(nullptr),
        nullptr);
    CreateWindowExW(
        WS_EX_CLIENTEDGE,
        L"EDIT",
        L"",
        WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL,
        12,
        38,
        430,
        28,
        g_mark_dialog_hwnd,
        reinterpret_cast<HMENU>(static_cast<INT_PTR>(kMarkEditId)),
        GetModuleHandleW(nullptr),
        nullptr);
    CreateWindowExW(
        0,
        L"BUTTON",
        L"Save",
        WS_CHILD | WS_VISIBLE | BS_DEFPUSHBUTTON,
        250,
        92,
        90,
        30,
        g_mark_dialog_hwnd,
        reinterpret_cast<HMENU>(static_cast<INT_PTR>(kMarkOkId)),
        GetModuleHandleW(nullptr),
        nullptr);
    CreateWindowExW(
        0,
        L"BUTTON",
        L"Cancel",
        WS_CHILD | WS_VISIBLE,
        352,
        92,
        90,
        30,
        g_mark_dialog_hwnd,
        reinterpret_cast<HMENU>(static_cast<INT_PTR>(kMarkCancelId)),
        GetModuleHandleW(nullptr),
        nullptr);

    ShowWindow(g_mark_dialog_hwnd, SW_SHOW);
    UpdateWindow(g_mark_dialog_hwnd);
    SetForegroundWindow(g_mark_dialog_hwnd);
    HWND edit = GetDlgItem(g_mark_dialog_hwnd, kMarkEditId);
    if (edit) {
        SetFocus(edit);
    }

    MSG msg{};
    while (g_mark_dialog_hwnd && IsWindow(g_mark_dialog_hwnd)) {
        if (GetMessageW(&msg, nullptr, 0, 0) <= 0) {
            break;
        }
        if (!IsDialogMessageW(g_mark_dialog_hwnd, &msg)) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }

    if (g_mark_note_accepted) {
        const std::string note = WideToUtf8(g_mark_note_wide);
        const std::string line = BuildMarkLogLine(g_mark_snapshot, note);
        AppendMarkLogLine(line);
        g_last_probe_status = "mark: saved";
    } else {
        g_last_probe_status = "mark: cancelled";
    }
}

void WriteSidecarFile(const std::string& text) {
    FILE* file = nullptr;
    if (fopen_s(&file, "mod\\dll\\cnv_enemy_debug.txt", "w") != 0 || !file) {
        return;
    }
    fputs(text.c_str(), file);
    fputc('\n', file);
    fclose(file);
}

void SetOverlayText(const std::string& text) {
    g_overlay_text_utf8 = text;
    g_overlay_text_wide = AsciiToWide(text);
    WriteSidecarFile(text);
    if (g_overlay_hwnd) {
        // Invalidate only — UpdateWindow from debug thread can deadlock / crash with game render.
        InvalidateRect(g_overlay_hwnd, nullptr, FALSE);
    }
}

void PaintOverlayClient(HDC hdc, const RECT& rc) {
    HBRUSH bg = CreateSolidBrush(RGB(0, 0, 0));
    FillRect(hdc, &rc, bg);
    DeleteObject(bg);

    SetBkMode(hdc, TRANSPARENT);
    SetTextColor(hdc, RGB(0, 255, 0));
    HFONT old_font = nullptr;
    if (g_overlay_font) {
        old_font = reinterpret_cast<HFONT>(SelectObject(hdc, g_overlay_font));
    }

    RECT text_rc = rc;
    text_rc.left += 8;
    text_rc.top += 8;
    text_rc.right -= 8;
    text_rc.bottom -= 8;

    const wchar_t* draw_text =
        g_overlay_text_wide.empty() ? L"(no text)" : g_overlay_text_wide.c_str();
    DrawTextW(hdc,
              draw_text,
              -1,
              &text_rc,
              DT_LEFT | DT_TOP | DT_WORDBREAK | DT_NOPREFIX | DT_EXPANDTABS);

    if (old_font) {
        SelectObject(hdc, old_font);
    }
}

LRESULT CALLBACK OverlayWndProc(HWND hwnd, UINT msg, WPARAM wparam, LPARAM lparam) {
    switch (msg) {
        case WM_ERASEBKGND:
            return 1;
        case WM_PAINT: {
            PAINTSTRUCT ps{};
            HDC hdc = BeginPaint(hwnd, &ps);
            RECT rc{};
            GetClientRect(hwnd, &rc);
            PaintOverlayClient(hdc, rc);
            EndPaint(hwnd, &ps);
            return 0;
        }
        case WM_DESTROY:
            PostQuitMessage(0);
            return 0;
        default:
            break;
    }
    return DefWindowProcW(hwnd, msg, wparam, lparam);
}

bool EnsureOverlayWindow() {
    if (g_overlay_hwnd) {
        return true;
    }

    static const wchar_t* kClassName = L"CNVEnemyDebugOverlay";
    WNDCLASSEXW wc{};
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = OverlayWndProc;
    wc.hInstance = GetModuleHandleW(nullptr);
    wc.lpszClassName = kClassName;
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.hbrBackground = reinterpret_cast<HBRUSH>(GetStockObject(BLACK_BRUSH));
    if (!GetClassInfoExW(wc.hInstance, kClassName, &wc)) {
        if (!RegisterClassExW(&wc)) {
            LogLine("enemy_debug: RegisterClassEx failed err=%lu", GetLastError());
            return false;
        }
    }

    g_overlay_hwnd = CreateWindowExW(
        WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
        kClassName,
        L"CNV Enemy Debug",
        WS_POPUP,
        20,
        120,
        kOverlayW,
        kOverlayH,
        nullptr,
        nullptr,
        GetModuleHandleW(nullptr),
        nullptr);
    if (!g_overlay_hwnd) {
        LogLine("enemy_debug: CreateWindowEx failed err=%lu", GetLastError());
        return false;
    }

    g_overlay_font = CreateFontW(
        20, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS,
        CLIP_DEFAULT_PRECIS, ANTIALIASED_QUALITY, FIXED_PITCH | FF_MODERN, L"Consolas");

    ShowWindow(g_overlay_hwnd, SW_HIDE);
    return true;
}

void SetOverlayVisible(bool visible) {
    if (!EnsureOverlayWindow()) {
        return;
    }
    ShowWindow(g_overlay_hwnd, visible ? SW_SHOWNOACTIVATE : SW_HIDE);
    if (visible) {
        SetOverlayText(g_overlay_text_utf8.empty() ? "CNV debug ON" : g_overlay_text_utf8);
    }
}

void DebugHudLoop() {
    if (!EnsureOverlayWindow()) {
        LogLine("enemy_debug: overlay init failed");
        return;
    }

    LoadNpcEnglishNames();
    LogLine("enemy_debug: worker ready (F7 HUD; F6=F7 cache; F8 probe; v8.9.46)");
    RegisterProbeHotkeys();
    bool prev_f7 = false;
    bool prev_f6 = false;
    bool prev_f8 = false;
    bool prev_f9 = false;

    while (true) {
        MSG msg{};
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) {
            if (msg.message == WM_HOTKEY) {
                if (msg.wParam == kHotkeyMarkId) {
                    RunMarkDialogModal();
                } else if (msg.wParam == kHotkeyProbeId || msg.wParam == kHotkeyProbeAltId) {
                    RunProbeDump();
                }
            }
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }

        const bool f7 = (GetAsyncKeyState(kHotkeyVk) & 0x8000) != 0;
        if (f7 && !prev_f7) {
            const bool next = !g_hud_enabled.load();
            g_hud_enabled.store(next);
            LogLine("enemy_debug: HUD %s", next ? "ON" : "OFF");
            if (!next) {
                SetOverlayVisible(false);
            } else {
                SetOverlayVisible(true);
                SetOverlayText("CNV debug ON - waiting for player...");
            }
        }
        prev_f7 = f7;

        const bool f6 = (GetAsyncKeyState(kMarkVk) & 0x8000) != 0;
        if (f6 && !prev_f6) {
            RunMarkDialogModal();
        }
        prev_f6 = f6;

        const bool f8 = (GetAsyncKeyState(kProbeVk) & 0x8000) != 0;
        if (f8 && !prev_f8) {
            RunProbeDump();
        }
        prev_f8 = f8;

        const bool f9 = (GetAsyncKeyState(kProbeVkAlt) & 0x8000) != 0;
        if (f9 && !prev_f9) {
            RunProbeDump();
        }
        prev_f9 = f9;

        if (g_hud_enabled.load()) {
            void* player = GetPlayerIns();
            void* target = GetLockOnTarget(player);
            const std::string text = BuildDebugText(player, target);
            if (text != g_overlay_text_utf8) {
                SetOverlayText(text);
            }
            const int npc = target ? ReadNpcParamId(target) : 0;
            if (npc != g_last_logged_npc) {
                g_last_logged_npc = npc;
                if (npc > 0) {
                    LogLine("enemy_debug target npc=%d", npc);
                }
            }
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
}
}  // namespace enemy_debug_internal

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
std::atomic<bool> g_worker_started{false};
std::atomic<bool> g_hud_enabled{false};
uint64_t g_world_chr_man_ptr_loc = 0;
uint64_t g_lock_tgt_man_ptr_loc = 0;
uint32_t g_lock_target_off = kDefaultLockTargetOff;
uint32_t g_map_id_off = kDefaultMapIdOff;
void* g_hooked_lock_target = nullptr;
int g_last_logged_capture_npc = 0;
void* g_last_logged_capture_ptr = nullptr;
std::atomic<uint32_t> g_capture_hits{0};
std::atomic<uint32_t> g_lock_patch_count{0};
void* g_last_raw_capture = nullptr;
int g_last_raw_npc = 0;
bool g_lock_capture_installed = false;
HWND g_overlay_hwnd = nullptr;
HFONT g_overlay_font = nullptr;
std::string g_overlay_text_utf8;
std::wstring g_overlay_text_wide;
std::string g_last_probe_status = "F8=probe | F6=mark locked enemy to log | F7=HUD toggle";
int g_last_logged_npc = 0;
bool g_probe_snapshot_valid = false;
uint64_t g_probe_snapshot[kProbeScanSlots];
uint32_t g_probe_dump_seq = 0;
std::unordered_map<int, std::string> g_npc_en_names;
bool g_npc_names_loaded = false;
HudLockCache g_hud_lock_cache{};
HWND g_mark_dialog_hwnd = nullptr;
MarkSnapshot g_mark_snapshot{};
wchar_t g_mark_note_wide[512]{};
bool g_mark_note_accepted = false;

uint64_t ReadU64(uint64_t addr) {
    if (!addr) {
        return 0;
    }
    __try {
        return *reinterpret_cast<uint64_t*>(addr);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return 0;
    }
}

int32_t ReadI32(uint64_t addr) {
    if (!addr) {
        return 0;
    }
    __try {
        return *reinterpret_cast<int32_t*>(addr);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return 0;
    }
}

uint32_t ReadU32(uint64_t addr) {
    if (!addr) {
        return 0;
    }
    __try {
        return *reinterpret_cast<uint32_t*>(addr);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return 0;
    }
}

uint8_t ReadU8(uint64_t addr) {
    if (!addr) {
        return 0;
    }
    __try {
        return *reinterpret_cast<uint8_t*>(addr);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return 0;
    }
}

float ReadF32(uint64_t addr) {
    if (!addr) {
        return 0.0f;
    }
    __try {
        return *reinterpret_cast<float*>(addr);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return 0.0f;
    }
}

bool IsSanePtr(uint64_t addr) {
    return addr >= 0x10000ull && addr < 0x00007FFFFFFFFFFFull;
}

bool IsPlausibleNpcId(int npc) {
    return npc >= kNpcIdMin && npc <= kNpcIdMax;
}

bool HasChrModules(void* p) {
    if (!p) {
        return false;
    }
    const uint64_t base = reinterpret_cast<uint64_t>(p);
    if (!IsSanePtr(base)) {
        return false;
    }
    return IsSanePtr(ReadU64(base + kChrModulesOff));
}

bool IsLikelyChrIns(void* p) {
    if (!HasChrModules(p)) {
        return false;
    }
    const int npc = ReadI32(reinterpret_cast<uint64_t>(p) + kChrNpcParamIdOff);
    return IsPlausibleNpcId(npc);
}

bool IsKnownSpawnNpc(int npc) {
    if (!EnemySpawnMap::IsLoaded()) {
        return true;
    }
    EnemySpawnMap::DebugRow row[1];
    return EnemySpawnMap::LookupDebugByNpc(npc, row, 1) > 0;
}

uint64_t DataModule(void* chr_ins) {
    const uint64_t mods = ReadU64(reinterpret_cast<uint64_t>(chr_ins) + kChrModulesOff);
    if (!mods) {
        return 0;
    }
    return ReadU64(mods + kModulesDataOff);
}

bool HasLivingEnemyData(void* chr_ins) {
    const uint64_t data = DataModule(chr_ins);
    if (!data) {
        return false;
    }
    const int hp = ReadI32(data + kDataHpOff);
    const int max_hp = ReadI32(data + kDataMaxHpOff);
    return max_hp > 0 && hp >= 0;
}

bool IsEnemyChrIns(void* player_ins, void* candidate) {
    if (!candidate || candidate == player_ins) {
        return false;
    }
    if (!HasChrModules(candidate)) {
        return false;
    }
    const int npc = ReadI32(reinterpret_cast<uint64_t>(candidate) + kChrNpcParamIdOff);
    if (!IsPlausibleNpcId(npc)) {
        return false;
    }
    if (player_ins) {
        const int player_npc =
            ReadI32(reinterpret_cast<uint64_t>(player_ins) + kChrNpcParamIdOff);
        if (npc == player_npc) {
            return false;
        }
    }
    return true;
}

int ReadNpcParamId(void* chr_ins) {
    if (!chr_ins) {
        return 0;
    }
    const int npc = ReadI32(reinterpret_cast<uint64_t>(chr_ins) + kChrNpcParamIdOff);
    if (!IsPlausibleNpcId(npc)) {
        return 0;
    }
    if (HasChrModules(chr_ins)) {
        return npc;
    }
  // Lock capture can yield a valid runtime npc id before ChrIns modules are wired.
    return IsKnownSpawnNpc(npc) ? npc : 0;
}

void* ChrPtrAt(uint64_t base, uint32_t off) {
    return reinterpret_cast<void*>(ReadU64(base + off));
}

uint64_t PhysicsModule(void* chr_ins) {
    const uint64_t mods = ReadU64(reinterpret_cast<uint64_t>(chr_ins) + kChrModulesOff);
    if (!mods) {
        return 0;
    }
    return ReadU64(mods + kModulesPhysicsOff);
}

uint64_t CollisionModule(void* chr_ins) {
    const uint64_t mods = ReadU64(reinterpret_cast<uint64_t>(chr_ins) + kChrModulesOff);
    if (!mods) {
        return 0;
    }
    return ReadU64(mods + kModulesCollisionOff);
}

bool ReadPosModule(uint64_t module, float& x, float& y, float& z) {
    if (!module) {
        return false;
    }
    x = ReadF32(module + kPhysicsPosOff + 0);
    y = ReadF32(module + kPhysicsPosOff + 4);
    z = ReadF32(module + kPhysicsPosOff + 8);
    if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z)) {
        return false;
    }
    if (x < kMinValidCoord || x > kMaxValidCoord || y < kMinValidCoord || y > kMaxValidCoord ||
        z < kMinValidCoord || z > kMaxValidCoord) {
        return false;
    }
    return true;
}

bool ReadPos(void* chr_ins, float& x, float& y, float& z) {
    if (ReadPosModule(PhysicsModule(chr_ins), x, y, z)) {
        return true;
    }
    return ReadPosModule(CollisionModule(chr_ins), x, y, z);
}

bool EstimatePlayerWorldPos(void* player_ins, float& wx, float& wy, float& wz) {
    if (!player_ins) {
        return false;
    }
    float plx = 0.0f;
    float ply = 0.0f;
    float plz = 0.0f;
    ReadPos(player_ins, plx, ply, plz);
    const uint64_t pbase = reinterpret_cast<uint64_t>(player_ins);
    const float cx = ReadF32(pbase + g_map_id_off - 16);
    const float cy = ReadF32(pbase + g_map_id_off - 12);
    const float cz = ReadF32(pbase + g_map_id_off - 8);
    wx = cx + plx;
    wy = cy + ply;
    wz = cz + plz;
    return std::isfinite(wx) && std::isfinite(wy) && std::isfinite(wz);
}

void* FindChrWithPosForNpc(void* player_ins, void* target_chr, int npc) {
    if (!player_ins || npc <= 0) {
        return nullptr;
    }
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
    if (target_chr && ReadNpcParamId(target_chr) == npc && ReadPos(target_chr, x, y, z)) {
        if (std::fabs(x) > 0.05f || std::fabs(y) > 0.05f || std::fabs(z) > 0.05f) {
            return target_chr;
        }
    }
    for (uint32_t off : kProbePollOffsets) {
        void* candidate = PollLockAtOffset(player_ins, off, nullptr);
        if (!candidate || ReadNpcParamId(candidate) != npc) {
            continue;
        }
        if (ReadPos(candidate, x, y, z)) {
            if (std::fabs(x) > 0.05f || std::fabs(y) > 0.05f || std::fabs(z) > 0.05f) {
                return candidate;
            }
        }
    }
    return nullptr;
}

bool EstimateEnemyWorldPos(void* player_ins, void* target_chr, float& wx, float& wy, float& wz) {
    if (!player_ins || !target_chr) {
        return false;
    }
    float tx = 0.0f;
    float ty = 0.0f;
    float tz = 0.0f;
    float plx = 0.0f;
    float ply = 0.0f;
    float plz = 0.0f;
    if (!ReadPos(target_chr, tx, ty, tz)) {
        return false;
    }
    if (std::fabs(tx) < 0.05f && std::fabs(ty) < 0.05f && std::fabs(tz) < 0.05f) {
        return false;
    }
    const bool has_player_local = ReadPos(player_ins, plx, ply, plz);
    const uint64_t pbase = reinterpret_cast<uint64_t>(player_ins);
    const float cx = ReadF32(pbase + g_map_id_off - 16);
    const float cy = ReadF32(pbase + g_map_id_off - 12);
    const float cz = ReadF32(pbase + g_map_id_off - 8);

    const bool looks_local =
        std::fabs(tx) < 256.0f && std::fabs(ty) < 256.0f && std::fabs(tz) < 256.0f;
    if (looks_local && has_player_local) {
        wx = cx + (tx - plx);
        wy = cy + (ty - ply);
        wz = cz + (tz - plz);
        return true;
    }
    wx = tx;
    wy = ty;
    wz = tz;
    return true;
}

bool ResolveLockOnDebugRow(
    void* player_ins,
    void* target_chr,
    EnemySpawnMap::DebugRow* out,
    float* out_dist_m,
    char* resolve_label,
    size_t resolve_label_len,
    SlotResolvePolicy policy) {
    if (!out || !target_chr) {
        return false;
    }
    *out = EnemySpawnMap::DebugRow{};
    if (out_dist_m) {
        *out_dist_m = -1.0f;
    }
    if (resolve_label && resolve_label_len > 0) {
        resolve_label[0] = '\0';
    }

    const int npc = ReadNpcParamId(target_chr);
    char map_name[32] = {};
    if (player_ins) {
        const uint32_t map_raw =
            ReadU32(reinterpret_cast<uint64_t>(player_ins) + g_map_id_off);
        FormatMapId(map_raw, map_name, sizeof(map_name));
    }

    if (map_name[0] && EnemySpawnMap::LookupDebugResolved(map_name, npc, out)) {
        if (resolve_label && resolve_label_len > 0) {
            snprintf(resolve_label, resolve_label_len, "spawn_map");
        }
        if (out_dist_m && player_ins && out->has_pos) {
            float wx = 0.0f;
            float wy = 0.0f;
            float wz = 0.0f;
            if (EstimateEnemyWorldPos(player_ins, target_chr, wx, wy, wz)) {
                const float dx = out->pos_x - wx;
                const float dy = out->pos_y - wy;
                const float dz = out->pos_z - wz;
                *out_dist_m = sqrtf(dx * dx + dy * dy + dz * dz);
            }
        }
        return out->entity_name[0] != '\0';
    }

    EnemySpawnMap::DebugRow matches[8];
    const size_t n = EnemySpawnMap::LookupDebugByNpc(npc, matches, 8);
    if (n == 1) {
        *out = matches[0];
        if (resolve_label && resolve_label_len > 0) {
            snprintf(resolve_label, resolve_label_len, "npc_only");
        }
        return out->entity_name[0] != '\0';
    }
    if (n > 1 && map_name[0]) {
        for (size_t i = 0; i < n; ++i) {
            if (_stricmp(matches[i].map_id, map_name) == 0) {
                *out = matches[i];
                if (resolve_label && resolve_label_len > 0) {
                    snprintf(resolve_label, resolve_label_len, "npc_map");
                }
                return out->entity_name[0] != '\0';
            }
        }
    }

    float wx = 0.0f;
    float wy = 0.0f;
    float wz = 0.0f;
    auto try_nearest = [&](float sx, float sy, float sz, const char* label) -> bool {
        if (!map_name[0]) {
            return false;
        }
        float dist_m = 0.0f;
        if (!EnemySpawnMap::LookupDebugNearestPos(
                map_name, sx, sy, sz, kSlotNearestMaxDistM, out, &dist_m)) {
            return false;
        }
        if (out_dist_m) {
            *out_dist_m = dist_m;
        }
        if (resolve_label && resolve_label_len > 0 && label) {
            snprintf(resolve_label, resolve_label_len, "%s", label);
        }
        return out->entity_name[0] != '\0';
    };

    if (policy == SlotResolvePolicy::Hud) {
        if (EstimateEnemyWorldPos(player_ins, target_chr, wx, wy, wz)) {
            if (try_nearest(wx, wy, wz, "nearest")) {
                if (!out_dist_m || *out_dist_m <= kSlotNearestWeakDistM) {
                    return true;
                }
            }
        }

        if (void* pos_chr = FindChrWithPosForNpc(player_ins, target_chr, npc)) {
            if (EstimateEnemyWorldPos(player_ins, pos_chr, wx, wy, wz)
                && try_nearest(wx, wy, wz, pos_chr == target_chr ? "nearest" : "nearest_alt")) {
                if (!out_dist_m || *out_dist_m <= kSlotNearestWeakDistM) {
                    return true;
                }
            }
        }

        if (EstimatePlayerWorldPos(player_ins, wx, wy, wz)
            && try_nearest(wx, wy, wz, "player_pos")) {
            if (!out_dist_m || *out_dist_m <= kSlotNearestWeakDistM) {
                return true;
            }
        }
    }

    if (n == 1) {
        *out = matches[0];
        if (resolve_label && resolve_label_len > 0) {
            snprintf(resolve_label, resolve_label_len, "npc_only");
        }
        return out->entity_name[0] != '\0';
    }
    if (n > 1 && map_name[0]) {
        for (size_t i = 0; i < n; ++i) {
            if (_stricmp(matches[i].map_id, map_name) == 0) {
                *out = matches[i];
                if (resolve_label && resolve_label_len > 0) {
                    snprintf(resolve_label, resolve_label_len, "npc_map");
                }
                return out->entity_name[0] != '\0';
            }
        }
    }
    return false;
}

bool ResolveWorldChrManPtr(SigScan& scanner, uint64_t& out_ptr_loc) {
    static const uint8_t kPat[] = {
        0x48, 0x8B, 0x9B, 0x08, 0xE5, 0x01, 0x00, 0x48, 0x85, 0xDB,
    };
    static const char kMask[] = "xxxxxxxxxx";
    auto* found = static_cast<uint8_t*>(
        scanner.FindPattern(kPat, kMask, static_cast<int>(sizeof(kPat))));
    if (!found) {
        LogLine("enemy_debug: signature miss WorldChrMan");
        return false;
    }
    for (int back = 3; back < 96; ++back) {
        auto* p = found - back;
        if (p[0] == 0x48 && p[1] == 0x8B && (p[2] == 0x1D || p[2] == 0x05)) {
            const int32_t rel = *reinterpret_cast<int32_t*>(p + 3);
            out_ptr_loc = reinterpret_cast<uint64_t>(p) + 7 + rel;
            LogLine("enemy_debug: WorldChrMan ptr @ 0x%llX",
                    static_cast<unsigned long long>(out_ptr_loc));
            return true;
        }
    }
    LogLine("enemy_debug: WorldChrMan rip scan failed");
    return false;
}

bool ResolveMapIdOffset(SigScan& scanner, uint32_t& out_off) {
    static const uint8_t kPat[] = {
        0xC7, 0x83, 0x00, 0x00, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0xFF,
        0x0F, 0x28, 0x0D,
    };
    static const char kMask[] = "xx????xxxxxx";
    auto* found = static_cast<uint8_t*>(
        scanner.FindPattern(kPat, kMask, static_cast<int>(sizeof(kPat))));
    if (!found) {
        LogLine("enemy_debug: map-id pattern miss; fallback off=0x%X", kDefaultMapIdOff);
        out_off = kDefaultMapIdOff;
        return false;
    }
    const int32_t rel = *reinterpret_cast<int32_t*>(found + 2);
    if (rel <= 0 || rel > 0x4000) {
        out_off = kDefaultMapIdOff;
        return false;
    }
    out_off = static_cast<uint32_t>(rel);
    LogLine("enemy_debug: map-id off=0x%X", out_off);
    return true;
}

void* GetPlayerIns() {
    if (!g_world_chr_man_ptr_loc) {
        return nullptr;
    }
    const uint64_t world_chr_man = ReadU64(g_world_chr_man_ptr_loc);
    if (!world_chr_man) {
        return nullptr;
    }
    return reinterpret_cast<void*>(ReadU64(world_chr_man + kPlayerInsOffset));
}

void FormatMapId(uint32_t map_id_raw, char* out, size_t out_len) {
    const uint32_t p3 = (map_id_raw >> 24) & 0xFFu;
    const uint32_t p2 = (map_id_raw >> 16) & 0xFFu;
    const uint32_t p1 = (map_id_raw >> 8) & 0xFFu;
    const uint32_t p0 = map_id_raw & 0xFFu;
    snprintf(out, out_len, "m%u_%02u_%02u_%02u", p3, p2, p1, p0);
}

const char* PlacementLabel(const EnemySpawnMap::DebugRow& row) {
    if (row.placement[0]) {
        if (_stricmp(row.placement, "patrol") == 0) {
            return "patrol";
        }
        if (_stricmp(row.placement, "perch_or_squat") == 0) {
            return "sit";
        }
        if (_stricmp(row.placement, "collision_anchor") == 0) {
            return "anchor";
        }
        if (_stricmp(row.placement, "aerial_model") == 0) {
            return "fly";
        }
        if (_stricmp(row.placement, "ground") == 0) {
            return "stand";
        }
        return row.placement;
    }
    if (row.walk_route[0]) {
        return "patrol";
    }
    if (row.backup_anim > 0) {
        return "sit";
    }
    return "stand";
}
}  // namespace enemy_debug_internal

#pragma once

#include <Windows.h>

#include <atomic>
#include <cstdint>
#include <string>
#include <unordered_map>

class SigScan;
namespace EnemySpawnMap {
struct DebugRow;
}

namespace enemy_debug_internal {

constexpr uint32_t kPlayerInsOffset = 0x1E508;
constexpr uint32_t kDefaultLockTargetOff = 0x6A0;
constexpr uint32_t kDefaultMapIdOff = 0x6C0;
constexpr uint32_t kChrNpcParamIdOff = 0x60;
constexpr uint32_t kChrModulesOff = 0x190;
constexpr uint32_t kModulesPhysicsOff = 0x68;
constexpr uint32_t kModulesCollisionOff = 0x78;
constexpr uint32_t kPhysicsPosOff = 0x70;
constexpr UINT kHotkeyVk = VK_F7;
constexpr UINT kMarkVk = VK_F6;
constexpr UINT kProbeVk = VK_F8;
constexpr UINT kProbeVkAlt = VK_F9;
constexpr int kHotkeyProbeId = 1;
constexpr int kHotkeyProbeAltId = 2;
constexpr int kHotkeyMarkId = 3;
constexpr int kMaxLockPatches = 4;
constexpr uint32_t kProbePollOffsets[] = {
    0x5C8, 0x5E8, 0x680, 0x688, 0x690, 0x698, 0x6A0, 0x6A8, 0x6B0, 0x6B8, 0x6C0, 0x6C8,
};
constexpr uint32_t kProbeScanStart = 0x500;
constexpr uint32_t kProbeScanEnd = 0x900;
constexpr size_t kProbeScanSlots = ((kProbeScanEnd - kProbeScanStart) / 8) + 1;

constexpr int kOverlayW = 820;
constexpr int kOverlayH = 520;
constexpr int kNpcIdMin = 1000;
constexpr int kNpcIdMax = 999999999;
constexpr uint32_t kModulesDataOff = 0x0;
constexpr uint32_t kDataHpOff = 0x138;
constexpr uint32_t kDataMaxHpOff = 0x13C;
constexpr float kMinValidCoord = -500000.0f;
constexpr float kMaxValidCoord = 500000.0f;
constexpr float kLockMaxDistM = 80.0f;
constexpr bool kEnableLockCapturePatch = true;
constexpr uint32_t kLockTgtManLockOnOff = 0x2831;
constexpr size_t kTargetedNpcPatchLen = 11;

constexpr float kSlotNearestMaxDistM = 80.0f;
constexpr float kSlotNearestWeakDistM = 10.0f;
constexpr ULONGLONG kHudLockCacheMaxAgeMs = 3000;

constexpr int kMarkEditId = 2001;
constexpr int kMarkOkId = 2002;
constexpr int kMarkCancelId = 2003;

struct MarkSnapshot {
    bool valid = false;
    char map_name[32]{};
    int npc = 0;
    char entity_name[64]{};
    char model[64]{};
    char template_id[128]{};
    int donor_npc = 0;
    float target_x = 0.0f;
    float target_y = 0.0f;
    float target_z = 0.0f;
    float player_lx = 0.0f;
    float player_ly = 0.0f;
    float player_lz = 0.0f;
    float chunk_x = 0.0f;
    float chunk_y = 0.0f;
    float chunk_z = 0.0f;
    char placement[32]{};
    char walk_route[64]{};
    int backup_anim = -1;
    float slot_dist_m = -1.0f;
    char slot_resolve[24]{};
    float world_x = 0.0f;
    float world_y = 0.0f;
    float world_z = 0.0f;
    int spawn_npc = 0;
    char npc_name_en[96]{};
    char donor_name_en[96]{};
    char mark_trust[16]{};
    char mark_source[16]{};
};

struct HudLockCache {
    bool valid = false;
    ULONGLONG tick_ms = 0;
    int npc = 0;
    MarkSnapshot snap{};
};

enum class SlotResolvePolicy { Hud, Mark };

extern std::atomic<bool> g_worker_started;
extern std::atomic<bool> g_hud_enabled;
extern uint64_t g_world_chr_man_ptr_loc;
extern uint64_t g_lock_tgt_man_ptr_loc;
extern uint32_t g_lock_target_off;
extern uint32_t g_map_id_off;
extern void* g_hooked_lock_target;
extern int g_last_logged_capture_npc;
extern void* g_last_logged_capture_ptr;
extern std::atomic<uint32_t> g_capture_hits;
extern std::atomic<uint32_t> g_lock_patch_count;
extern void* g_last_raw_capture;
extern int g_last_raw_npc;
extern bool g_lock_capture_installed;
extern HWND g_overlay_hwnd;
extern HFONT g_overlay_font;
extern std::string g_overlay_text_utf8;
extern std::wstring g_overlay_text_wide;
extern std::string g_last_probe_status;
extern int g_last_logged_npc;
extern bool g_probe_snapshot_valid;
extern uint64_t g_probe_snapshot[kProbeScanSlots];
extern uint32_t g_probe_dump_seq;
extern std::unordered_map<int, std::string> g_npc_en_names;
extern bool g_npc_names_loaded;
extern HudLockCache g_hud_lock_cache;
extern HWND g_mark_dialog_hwnd;
extern MarkSnapshot g_mark_snapshot;
extern wchar_t g_mark_note_wide[512];
extern bool g_mark_note_accepted;

uint64_t ReadU64(uint64_t addr);
int32_t ReadI32(uint64_t addr);
uint32_t ReadU32(uint64_t addr);
uint8_t ReadU8(uint64_t addr);
float ReadF32(uint64_t addr);
bool IsSanePtr(uint64_t addr);
bool IsPlausibleNpcId(int npc);
bool HasChrModules(void* p);
bool IsLikelyChrIns(void* p);
bool IsKnownSpawnNpc(int npc);
bool HasLivingEnemyData(void* chr_ins);
bool IsEnemyChrIns(void* player_ins, void* candidate);
int ReadNpcParamId(void* chr_ins);
void* ChrPtrAt(uint64_t base, uint32_t off);
bool ReadPos(void* chr_ins, float& x, float& y, float& z);
bool EstimatePlayerWorldPos(void* player_ins, float& wx, float& wy, float& wz);
void* FindChrWithPosForNpc(void* player_ins, void* target_chr, int npc);
bool EstimateEnemyWorldPos(void* player_ins, void* target_chr, float& wx, float& wy, float& wz);
void FormatMapId(uint32_t map_id_raw, char* out, size_t out_len);
const char* PlacementLabel(const EnemySpawnMap::DebugRow& row);
bool ResolveLockOnDebugRow(void* player_ins,
                           void* target_chr,
                           EnemySpawnMap::DebugRow* out,
                           float* out_dist_m,
                           char* resolve_label,
                           size_t resolve_label_len,
                           SlotResolvePolicy policy = SlotResolvePolicy::Hud);
bool ResolveWorldChrManPtr(SigScan& scanner, uint64_t& out_ptr_loc);
bool ResolveMapIdOffset(SigScan& scanner, uint32_t& out_off);
void* GetPlayerIns();
MarkSnapshot BuildMarkSnapshotFromLockOn(void* player_ins,
                                       void* target_chr,
                                       SlotResolvePolicy policy,
                                       const char* mark_source);
int AuthoritativeMarkNpc(const MarkSnapshot& snap);
void RefreshHudLockCache(void* player_ins, void* target_chr);

bool IsValidLockTarget(void* player_ins, void* candidate);
bool InstallLockTargetCapturePatches(SigScan& scanner, uint32_t& out_lock_off);
bool ResolveLockTgtManPtr(SigScan& scanner, uint64_t& out_ptr_loc);
bool ResolveLockTargetOffset(SigScan& scanner, uint32_t& out_off);
void* GetLockOnTarget(void* player_ins);
bool IsGameLockOnFlagSet();
void* PollLockAtOffset(void* player_ins, uint32_t off, int* out_npc);
void* PollLockFromPlayer(void* player_ins);

void LoadNpcEnglishNames();
const char* LookupNpcEnglishName(int npc_id);
void DumpPlayerProbe(void* player_ins);
void SetOverlayText(const std::string& text);
std::string BuildDebugText(void* player_ins, void* target_chr);
void RunProbeDump();
void RunMarkDialogModal();
void DebugHudLoop();
void DebugHudWorker(SigScan scanner);

}  // namespace enemy_debug_internal

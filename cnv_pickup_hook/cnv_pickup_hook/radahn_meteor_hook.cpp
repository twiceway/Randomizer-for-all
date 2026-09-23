#include "radahn_meteor_hook.h"



#include <Windows.h>



#include "enemy_spawn_map.h"

#include "log.h"

#include "sigscan.h"



#include "MinHook.h"



#include <atomic>

#include <cmath>

#include <cstdint>
#include <cstdio>
#include <cstring>

#include <fstream>

#include <mutex>

#include <string>

#include <thread>

#include <unordered_map>

#include <vector>



namespace {



using ApplySpEffectFn = void(__fastcall*)(void* chr_ins, int speffect_id, int unk);



ApplySpEffectFn g_apply_speffect = nullptr;

uint64_t g_world_chr_man_ptr_loc = 0;

void* g_ezstate_dispatch = nullptr;



uint32_t g_block_count = 0;

uint32_t g_land_count = 0;

uint32_t g_speffect_log_count = 0;

std::atomic<bool> g_land_thread_started{false};  // legacy; landing runs on game thread



constexpr uint32_t kPlayerInsOffset = 0x1E508;

constexpr uint32_t kChrNpcParamIdOff = 0x60;

constexpr uint32_t kChrHandleOff = 0x58;

constexpr uint32_t kChrModulesOff = 0x190;

constexpr uint32_t kModulesDataOff = 0x0;

constexpr uint32_t kModulesPhysicsOff = 0x68;

constexpr uint32_t kModulesCollisionOff = 0x78;

constexpr uint32_t kDataHpOff = 0x138;

constexpr uint32_t kDataMaxHpOff = 0x13C;

constexpr uint32_t kPhysicsPosOff = 0x70;



constexpr int kRequestAnimationEvent = 123;
constexpr int kLandAnimId = 3037;
constexpr bool kLandingShimEnabled = false;

constexpr DWORD kFlySwapCooldownMs = 8000;
constexpr DWORD kTrackGraceMs = 8000;
constexpr int kFlyAwaySpeffect = 13947;
constexpr int kLandTriggerSpeffect = 13906;
// Force phase-2 grounded state (same ids as NpcParam 47300041; NpcParam resident fx do not apply on spawn).
constexpr int kGroundSeedFx[] = {13902, 13904, 13928, 13926};
// Legacy landing shim constants (dead when kLandingShimEnabled=false).
constexpr DWORD kLandArmDelayMs = 4000;
constexpr DWORD kLandCooldownMs = 10000;
constexpr DWORD kLandRetryMs = 0;
constexpr int kLandBurstRetries = 0;
constexpr float kLandPlayerOffsetM = 5.0f;
constexpr float kMaxTrackPlayerDist = 55.0f;

constexpr float kMinValidCoord = -500000.0f;

constexpr float kMaxValidCoord = 500000.0f;



constexpr const char* kCanaryMarker = "CNV_RADAHN_CANARY_v8911";



struct TrackedRadahn {

    void* chr = nullptr;

    int npc = 0;

    float home_x = 0;

    float home_y = 0;

    float home_z = 0;

    bool has_home = false;

    bool logged_hp = false;

    bool land_armed = false;

    DWORD land_at_ms = 0;
    DWORD last_land_ms = 0;
    DWORD last_fly_swap_ms = 0;
    DWORD tracked_at_ms = 0;
    uint8_t land_retries_left = 0;
    bool grounded_seeded = false;
};



thread_local bool g_allow_radahn_fx_seed = false;

std::mutex g_track_mu;

std::vector<TrackedRadahn> g_tracked;



std::mutex g_fx_mu;

std::unordered_map<int, std::unordered_map<int, uint32_t>> g_fx_counts;



/* --- EzState (minimal port of TGA ezstate.h) --- */



enum EzStateFuncArgType : int { kEzFloat = 1, kEzInt32 = 2 };



struct EzStateExternalFuncArg {

    union {

        float as_float;

        int as_int;

        uint64_t as_unk_u64;

    } value;

    EzStateFuncArgType type;

};



struct EzStateExternalEventTemp_VMT {

    void (*dtor)(void*);

    void (*unk08)(void*);

    int (*event_id)(void*);

    int (*arg_count)(void*);

    EzStateExternalFuncArg* (*arg_at)(void*, int);

};



struct fake_ezstate_ext_event {

    EzStateExternalEventTemp_VMT* vtable;

    EzStateExternalFuncArg* args;

    int arg_count;

};



struct UnkTalkEventField08 {

    uint8_t pad0[0x30];

    uint64_t unk_chr_ins_handle;

};



struct CSTalkInsActiveMenuJob {

    uint8_t pad0[0x20];

    void* parent_talk_ins;

};



struct CSNpcTalkIns {

    uint8_t pad0[0xc];

    uint32_t unk_talk_param_field_1;

    uint32_t unk_talk_param_field_2;

    uint8_t pad14[0x40 - 0x14];

    uint64_t chr_ins_handle;

    uint8_t pad48[0x98 - 0x48];

    CSTalkInsActiveMenuJob* active_menu_job;

};



struct EzStateTalkEvent {

    void** vtable;

    UnkTalkEventField08* unk08;

    CSNpcTalkIns* npc_talk_ins;

    uint32_t unk18_popup_menu_related;

};



using EzStateDispatchFn = void(__fastcall*)(EzStateTalkEvent*, void*);



void FakeEzStub(void*) {}



int FakeEzEventId(void* self) {

    const auto* evt = static_cast<fake_ezstate_ext_event*>(self);

    return evt && evt->arg_count > 0 ? evt->args[0].value.as_int : 0;

}



int FakeEzArgCount(void* self) {

    const auto* evt = static_cast<fake_ezstate_ext_event*>(self);

    return evt ? evt->arg_count : 0;

}



EzStateExternalFuncArg* FakeEzArgAt(void* self, int index) {

    auto* evt = static_cast<fake_ezstate_ext_event*>(self);

    if (!evt || index < 0 || index >= evt->arg_count) {

        return nullptr;

    }

    return evt->args + index;

}



EzStateExternalEventTemp_VMT g_fake_ez_vtable = {

    FakeEzStub,

    FakeEzStub,

    FakeEzEventId,

    FakeEzArgCount,

    FakeEzArgAt,

};



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



bool WriteF32(uint64_t addr, float v) {

    if (!addr) {

        return false;

    }

    __try {

        *reinterpret_cast<float*>(addr) = v;

        return true;

    } __except (EXCEPTION_EXECUTE_HANDLER) {

        return false;

    }

}



bool IsLikelyChrIns(void* p) {

    if (!p) {

        return false;

    }

    return ReadU64(reinterpret_cast<uint64_t>(p) + kChrModulesOff) != 0;

}



int ReadNpcParamId(void* chr_ins) {

    if (!IsLikelyChrIns(chr_ins)) {

        return 0;

    }

    return ReadI32(reinterpret_cast<uint64_t>(chr_ins) + kChrNpcParamIdOff);

}



uint64_t ModulesBase(void* chr_ins) {

    return ReadU64(reinterpret_cast<uint64_t>(chr_ins) + kChrModulesOff);

}



uint64_t PhysicsModule(void* chr_ins) {

    const uint64_t mods = ModulesBase(chr_ins);

    if (!mods) {

        return 0;

    }

    return ReadU64(mods + kModulesPhysicsOff);

}



uint64_t CollisionModule(void* chr_ins) {

    const uint64_t mods = ModulesBase(chr_ins);

    if (!mods) {

        return 0;

    }

    return ReadU64(mods + kModulesCollisionOff);

}



uint64_t DataModule(void* chr_ins) {

    const uint64_t mods = ModulesBase(chr_ins);

    if (!mods) {

        return 0;

    }

    return ReadU64(mods + kModulesDataOff);

}



bool ReadPos(void* chr_ins, float& x, float& y, float& z) {

    const uint64_t phys = PhysicsModule(chr_ins);

    if (!phys) {

        return false;

    }

    x = ReadF32(phys + kPhysicsPosOff + 0);

    y = ReadF32(phys + kPhysicsPosOff + 4);

    z = ReadF32(phys + kPhysicsPosOff + 8);

    if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z)) {

        return false;

    }

    if (x < kMinValidCoord || x > kMaxValidCoord || y < kMinValidCoord || y > kMaxValidCoord ||

        z < kMinValidCoord || z > kMaxValidCoord) {

        return false;

    }

    return true;

}



bool WritePosModule(uint64_t module, float x, float y, float z) {

    if (!module) {

        return false;

    }

    return WriteF32(module + kPhysicsPosOff + 0, x) && WriteF32(module + kPhysicsPosOff + 4, y) &&

           WriteF32(module + kPhysicsPosOff + 8, z);

}



void ZeroVelocityModule(uint64_t module) {

    if (!module) {

        return;

    }

    for (uint32_t off : {0x7C, 0x80, 0x84, 0xA0, 0xA4, 0xA8}) {

        WriteF32(module + off, 0.0f);

    }

}



int WritePosAll(void* chr_ins, float x, float y, float z) {

    int n = 0;

    if (WritePosModule(PhysicsModule(chr_ins), x, y, z)) {

        ++n;

    }

    if (WritePosModule(CollisionModule(chr_ins), x, y, z)) {

        ++n;

    }

    ZeroVelocityModule(PhysicsModule(chr_ins));
    ZeroVelocityModule(CollisionModule(chr_ins));
    return n;
}



bool ReadHp(void* chr_ins, int32_t& hp, int32_t& max_hp) {

    const uint64_t data = DataModule(chr_ins);

    if (!data) {

        return false;

    }

    hp = ReadI32(data + kDataHpOff);

    max_hp = ReadI32(data + kDataMaxHpOff);

    return max_hp > 0 && hp >= 0;

}



uint64_t ChrInsHandle(void* chr_ins) {

    const uint64_t h = ReadU64(reinterpret_cast<uint64_t>(chr_ins) + kChrHandleOff);

    if (h) {

        return h;

    }

    return reinterpret_cast<uint64_t>(chr_ins);

}



bool IsRadahnChr(void* chr_ins) {

    const int npc = ReadNpcParamId(chr_ins);

    if (npc <= 0) {

        return false;

    }

    if (npc == 47300040 || npc == 47300041) {

        return true;

    }

    return EnemySpawnMap::IsRadahnNpc(npc);

}



bool IsMeteorFlyChainSpeffect(int id) {
    switch (id) {
        case 13901:  // greatbow swap -> meteor setup
        case 13903:  // cragblades -> Act13 meteor at low hp
        case 13906:  // arena landing trigger (no emevd roadside)
        case 13907:  // phase interrupt
        case 13947:  // meteor fly root-motion
            return true;
        default:
            return false;
    }
}



bool IsFlyTransitionSpeffect(int id) {
    return IsMeteorFlyChainSpeffect(id);
}

void ApplyRadahnFxDirect(void* chr_ins, int speffect_id, int unk) {
    if (!g_apply_speffect || !chr_ins) {
        return;
    }
    g_allow_radahn_fx_seed = true;
    g_apply_speffect(chr_ins, speffect_id, unk);
    g_allow_radahn_fx_seed = false;
}



void SeedGroundedRadahn(void* chr_ins, int unk) {
    if (!chr_ins || !IsLikelyChrIns(chr_ins) || !IsRadahnChr(chr_ins)) {
        return;
    }
    const int npc = ReadNpcParamId(chr_ins);
    for (int fx : kGroundSeedFx) {
        ApplyRadahnFxDirect(chr_ins, fx, unk);
    }
    LogLine("radahn_meteor seed grounded fx npc=%d ids=13902,13904,13928,13926", npc);
}

bool ResolveWorldChrManPtr(SigScan& scanner, uint64_t& out_ptr_loc) {

    static const uint8_t kPat[] = {

        0x48, 0x8B, 0x9B, 0x08, 0xE5, 0x01, 0x00, 0x48, 0x85, 0xDB,

    };

    static const char kMask[] = "xxxxxxxxxx";

    auto* found = static_cast<uint8_t*>(

        scanner.FindPattern(kPat, kMask, static_cast<int>(sizeof(kPat))));

    if (!found) {

        LogLine("radahn_meteor: signature miss WorldChrMan (player+0x1E508)");

        return false;

    }

    for (int back = 3; back < 96; ++back) {

        auto* p = found - back;

        if (p[0] == 0x48 && p[1] == 0x8B && (p[2] == 0x1D || p[2] == 0x05)) {

            const int32_t rel = *reinterpret_cast<int32_t*>(p + 3);

            out_ptr_loc = reinterpret_cast<uint64_t>(p) + 7 + rel;

            LogLine("radahn_meteor: WorldChrMan ptr @ 0x%llX (from kill-path anchor)",

                    static_cast<unsigned long long>(out_ptr_loc));

            return true;

        }

    }

    LogLine("radahn_meteor: WorldChrMan rip scan failed near 0x%llX",

            reinterpret_cast<unsigned long long>(found));

    return false;

}



bool ResolveEzStateDispatch(SigScan& scanner) {

    static const uint8_t kPat[] = {

        0x48, 0x8B, 0xDA, 0x4C, 0x8B, 0xF1, 0x33, 0xFF, 0x89, 0x7D,

    };

    static const char kMask[] = "xxxxxxxxxx";

    auto* found = static_cast<uint8_t*>(

        scanner.FindPattern(kPat, kMask, static_cast<int>(sizeof(kPat))));

    if (!found) {

        LogLine("radahn_meteor: signature miss EzState dispatcher");

        return false;

    }

    g_ezstate_dispatch = found - 0x47;

    LogLine("radahn_meteor: EzState dispatch @ 0x%llX",

            reinterpret_cast<unsigned long long>(g_ezstate_dispatch));

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



bool RunEzStateEvent(void* chr_ins, int event_id, int param, bool has_param) {
    if (!g_ezstate_dispatch || !chr_ins) {
        return false;
    }

    EzStateExternalFuncArg args[2] = {};
    args[0].value.as_int = event_id;
    args[0].type = kEzInt32;
    int count = 1;
    if (has_param) {
        args[1].value.as_int = param;
        args[1].type = kEzInt32;
        count = 2;
    }

    fake_ezstate_ext_event ext_event{};
    ext_event.vtable = &g_fake_ez_vtable;
    ext_event.args = args;
    ext_event.arg_count = count;

    UnkTalkEventField08 unk08{};
    CSNpcTalkIns talk_ins{};
    CSTalkInsActiveMenuJob menu_job{};
    const uint64_t handle = ChrInsHandle(chr_ins);
    unk08.unk_chr_ins_handle = handle;
    talk_ins.chr_ins_handle = handle;
    menu_job.parent_talk_ins = &talk_ins;
    talk_ins.active_menu_job = &menu_job;

    EzStateTalkEvent talk_event{};
    talk_event.vtable = nullptr;
    talk_event.unk08 = &unk08;
    talk_event.npc_talk_ins = &talk_ins;
    talk_event.unk18_popup_menu_related = 0;

    __try {
        reinterpret_cast<EzStateDispatchFn>(g_ezstate_dispatch)(&talk_event, &ext_event);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

bool RequestAnimation(void* chr_ins, int anim_id) {
    return RunEzStateEvent(chr_ins, kRequestAnimationEvent, anim_id, true);
}



bool FileContainsNeedle(const char* path, const char* needle) {

    std::ifstream in(path, std::ios::binary);

    if (!in) {

        return false;

    }

    in.seekg(0, std::ios::end);

    const auto sz = static_cast<size_t>(in.tellg());

    if (sz == 0 || sz > 64u * 1024u * 1024u) {

        return false;

    }

    in.seekg(0, std::ios::beg);

    std::string buf(sz, '\0');

    in.read(buf.data(), static_cast<std::streamsize>(sz));

    return buf.find(needle) != std::string::npos;

}



void LogDiskAssetDiagnostics() {

    LogLine("radahn_meteor disk: looking for canary=%s + AI stamp (anibnd skipped; DLL landing shim)",

            kCanaryMarker);



    const char* ai_paths[] = {

        "mod\\script\\473000_battle.luabnd.dcx",

        "mod\\script\\ai\\out\\each\\473000_battle.luabnd.dcx",

    };

    for (const char* p : ai_paths) {

        const DWORD attr = GetFileAttributesA(p);

        if (attr == INVALID_FILE_ATTRIBUTES) {

            LogLine("radahn_meteor disk: AI MISSING %s", p);

            continue;

        }

        WIN32_FILE_ATTRIBUTE_DATA fad{};

        if (GetFileAttributesExA(p, GetFileExInfoStandard, &fad)) {

            const uint64_t sz =

                (static_cast<uint64_t>(fad.nFileSizeHigh) << 32) | fad.nFileSizeLow;

            const bool has = FileContainsNeedle(p, kCanaryMarker);

            LogLine("radahn_meteor disk: AI %s size=%llu raw_canary=%s",

                    p,

                    static_cast<unsigned long long>(sz),

                    has ? "YES" : "NO");

        }

    }



    const char* stamp = "mod\\dll\\cnv_radahn_phase1_stamp.txt";

    std::ifstream in(stamp);

    if (!in) {

        LogLine("radahn_meteor disk: stamp MISSING %s (optional: NpcSoulPatch --ensure-radahn-phase1)",

                stamp);

        return;

    }

    LogLine("radahn_meteor disk: stamp BEGIN %s", stamp);

    std::string line;

    int n = 0;

    while (std::getline(in, line) && n < 12) {

        LogLine("radahn_meteor disk: stamp| %s", line.c_str());

        ++n;

    }

    LogLine("radahn_meteor disk: stamp END");

}



void NoteRadahnSpeffect(int npc, int speffect_id, void* chr_ins) {

    uint32_t count = 0;

    bool first_for_id = false;

    {

        std::lock_guard<std::mutex> lock(g_fx_mu);

        auto& per = g_fx_counts[npc];

        auto it = per.find(speffect_id);

        if (it == per.end()) {

            per[speffect_id] = 1;

            count = 1;

            first_for_id = true;

        } else {

            count = ++(it->second);

        }

    }



    ++g_speffect_log_count;

    const bool phase_ish = (speffect_id >= 13900 && speffect_id <= 13950) || speffect_id == 5400 ||

                           speffect_id == 5401;

    if (first_for_id || (phase_ish && (count <= 8 || (count % 25) == 0)) ||

        (!phase_ish && (count == 1 || count == 10 || (count % 100) == 0))) {

        int32_t hp = 0, max_hp = 0;

        float rate = -1.0f;

        if (ReadHp(chr_ins, hp, max_hp) && max_hp > 0) {

            rate = static_cast<float>(hp) / static_cast<float>(max_hp);

        }

        float x = 0, y = 0, z = 0;

        const bool pos = ReadPos(chr_ins, x, y, z);

        if (pos) {

            LogLine(

                "radahn_meteor speffect npc=%d id=%d count=%u hp=%d/%d rate=%.3f pos=(%.1f,%.1f,%.1f)%s",

                npc,

                speffect_id,

                count,

                hp,

                max_hp,

                rate,

                x,

                y,

                z,

                IsMeteorFlyChainSpeffect(speffect_id) ? " BLOCK" : "");

        } else {

            LogLine("radahn_meteor speffect npc=%d id=%d count=%u hp=%d/%d rate=%.3f%s",

                    npc,

                    speffect_id,

                    count,

                    hp,

                    max_hp,

                    rate,

                    IsMeteorFlyChainSpeffect(speffect_id) ? " BLOCK" : "");

        }

    }

}



TrackedRadahn* FindTrackedLocked(void* chr_ins) {

    for (auto& t : g_tracked) {

        if (t.chr == chr_ins) {

            return &t;

        }

    }

    return nullptr;

}



void ArmLanding(TrackedRadahn& t, const char* why) {
    const DWORD now = GetTickCount();
    if (t.tracked_at_ms && (now - t.tracked_at_ms) < kTrackGraceMs) {
        return;
    }
    if (t.land_armed && t.land_at_ms > now) {
        return;
    }
    if (t.last_land_ms && (now - t.last_land_ms) < kLandCooldownMs) {
        return;
    }
    if (!kLandingShimEnabled) {
        LogLine("radahn_meteor FLY npc=%d why=%s (landing shim OFF)",
                t.npc,
                why);
        return;
    }
    t.land_armed = true;
    t.land_at_ms = now + kLandArmDelayMs;
    t.land_retries_left = static_cast<uint8_t>(kLandBurstRetries);
    LogLine("radahn_meteor ARM npc=%d why=%s land_in=%ums retries=%u",
            t.npc,
            why,
            kLandArmDelayMs,
            t.land_retries_left);
}



void NoteRadahn(void* chr_ins) {

    if (!IsRadahnChr(chr_ins)) {

        return;

    }

    const int npc = ReadNpcParamId(chr_ins);

    float x = 0, y = 0, z = 0;

    const bool have_pos = ReadPos(chr_ins, x, y, z);



    std::lock_guard<std::mutex> lock(g_track_mu);

    if (TrackedRadahn* existing = FindTrackedLocked(chr_ins)) {

        if (!existing->logged_hp) {

            int32_t hp = 0, max_hp = 0;

            if (ReadHp(chr_ins, hp, max_hp)) {

                const float rate =

                    max_hp > 0 ? (static_cast<float>(hp) / static_cast<float>(max_hp)) : -1.0f;

                LogLine("radahn_meteor hp npc=%d hp=%d max=%d rate=%.3f (empty-touch fly diagnose)",

                        npc,

                        hp,

                        max_hp,

                        rate);

                existing->logged_hp = true;

            }

        }

        if (have_pos && !existing->has_home) {

            existing->home_x = x;

            existing->home_y = y;

            existing->home_z = z;

            existing->has_home = true;

        }

        return;

    }



    TrackedRadahn t;
    t.chr = chr_ins;
    t.npc = npc;
    t.tracked_at_ms = GetTickCount();

    if (have_pos) {
        void* player = GetPlayerIns();
        if (player) {
            float px = 0, py = 0, pz = 0;
            if (ReadPos(player, px, py, pz)) {
                const float dx = x - px;
                const float dy = y - py;
                const float dz = z - pz;
                const float pdist = std::sqrt(dx * dx + dy * dy + dz * dz);
                if (pdist > kMaxTrackPlayerDist) {
                    LogLine(
                        "radahn_meteor track skip phantom npc=%d chr=%p dist_player=%.1f pos=(%.1f,%.1f,%.1f)",
                        npc,
                        chr_ins,
                        pdist,
                        x,
                        y,
                        z);
                    return;
                }
            }
        }
        t.home_x = x;
        t.home_y = y;
        t.home_z = z;
        t.has_home = true;
        LogLine("radahn_meteor track npc=%d chr=%p home=(%.1f,%.1f,%.1f)", npc, chr_ins, x, y, z);

    } else {

        LogLine("radahn_meteor track npc=%d chr=%p (no physics yet)", npc, chr_ins);

    }

    int32_t hp = 0, max_hp = 0;

    if (ReadHp(chr_ins, hp, max_hp)) {

        const float rate = max_hp > 0 ? (static_cast<float>(hp) / static_cast<float>(max_hp)) : -1.0f;

        LogLine("radahn_meteor hp npc=%d hp=%d max=%d rate=%.3f (empty-touch fly diagnose)",

                npc,

                hp,

                max_hp,

                rate);

        t.logged_hp = true;

    }

    g_tracked.push_back(t);

}



void MaybeSeedGroundedRadahn(void* chr_ins) {
    bool need_seed = false;
  {
        std::lock_guard<std::mutex> lock(g_track_mu);
        TrackedRadahn* t = FindTrackedLocked(chr_ins);
        if (!t || t->grounded_seeded) {
            return;
        }
        t->grounded_seeded = true;
        need_seed = true;
    }
    if (need_seed) {
        SeedGroundedRadahn(chr_ins, 0);
    }
}



bool ComputeLandPos(const TrackedRadahn& t, float& lx, float& ly, float& lz) {

    void* player = GetPlayerIns();

    float px = t.home_x;

    float py = t.home_y;

    float pz = t.home_z;

    if (player && ReadPos(player, px, py, pz)) {

        float dx = t.home_x - px;

        float dz = t.home_z - pz;

        const float len = std::sqrt(dx * dx + dz * dz);

        if (len > 1.0f) {

            lx = px + (dx / len) * kLandPlayerOffsetM;

            lz = pz + (dz / len) * kLandPlayerOffsetM;

        } else {

            lx = px + kLandPlayerOffsetM;

            lz = pz;

        }

        ly = py;
        return true;
    }

    if (t.has_home) {

        lx = t.home_x;

        ly = t.home_y;

        lz = t.home_z;

        return true;

    }

    return false;

}



bool PerformLanding(TrackedRadahn& t) {
    if (!kLandingShimEnabled || !t.chr || !IsLikelyChrIns(t.chr) || !IsRadahnChr(t.chr)) {
        return false;
    }

    float from_x = 0, from_y = 0, from_z = 0;
    ReadPos(t.chr, from_x, from_y, from_z);

    float lx = 0, ly = 0, lz = 0;
    if (!ComputeLandPos(t, lx, ly, lz)) {
        return false;
    }

    const int writes = WritePosAll(t.chr, lx, ly, lz);
    const bool anim_ok = RequestAnimation(t.chr, kLandAnimId);

    ++g_land_count;
    t.last_land_ms = GetTickCount();
    if (t.land_retries_left > 0) {
        --t.land_retries_left;
        t.land_armed = true;
        t.land_at_ms = t.last_land_ms + kLandRetryMs;
    } else {
        t.land_armed = false;
    }

    LogLine(
        "radahn_meteor LAND npc=%d writes=%d anim3037=%d from=(%.1f,%.1f,%.1f) -> (%.1f,%.1f,%.1f) retries_left=%u count=%u",
        t.npc,
        writes,
        anim_ok ? 1 : 0,
        from_x,
        from_y,
        from_z,
        lx,
        ly,
        lz,
        t.land_retries_left,
        g_land_count);
    return writes > 0 || anim_ok;
}



bool TrySwapFlyToLand(void* chr_ins, int unk) {
    (void)chr_ins;
    (void)unk;
    return false;
}



void __fastcall HookApplySpEffect(void* chr_ins, int speffect_id, int unk) {

    NoteRadahn(chr_ins);
    MaybeSeedGroundedRadahn(chr_ins);

    if (!g_allow_radahn_fx_seed && IsRadahnChr(chr_ins) && IsMeteorFlyChainSpeffect(speffect_id)) {
        NoteRadahnSpeffect(ReadNpcParamId(chr_ins), speffect_id, chr_ins);
        ++g_block_count;
        if (g_block_count <= 24 || (g_block_count % 25) == 0) {
            LogLine("radahn_meteor block fly-chain fx=%d npc=%d count=%u chr=%p",
                    speffect_id,
                    ReadNpcParamId(chr_ins),
                    g_block_count,
                    chr_ins);
        }
        return;
    }

    if (IsRadahnChr(chr_ins)) {
        NoteRadahnSpeffect(ReadNpcParamId(chr_ins), speffect_id, chr_ins);
    }

    if (g_apply_speffect) {
        g_apply_speffect(chr_ins, speffect_id, unk);
    }

}



}  // namespace



bool InstallRadahnMeteorHook(SigScan& scanner) {

    LogDiskAssetDiagnostics();



    ResolveWorldChrManPtr(scanner, g_world_chr_man_ptr_loc);

    ResolveEzStateDispatch(scanner);



    static const uint8_t kPat[] = {

        0x0F, 0x28, 0x0D, 0x00, 0x00, 0x00, 0x00, 0x00, 0x8D, 0x00, 0x00, 0x0F, 0x29, 0x00,

        0x00, 0x00, 0x0F, 0xB6, 0xD8,

    };

    static const char kMask[] = "xxx?????x??xx???xxx";

    auto* found = static_cast<uint8_t*>(

        scanner.FindPattern(kPat, kMask, static_cast<int>(sizeof(kPat))));

    if (!found) {

        LogLine("radahn_meteor: signature miss ApplySpEffect");

        return false;

    }

    void* entry = found - 0x1D;

    LogLine("radahn_meteor: ApplySpEffect @ 0x%llX",

            reinterpret_cast<unsigned long long>(entry));



    if (MH_CreateHook(entry,

                      reinterpret_cast<void*>(&HookApplySpEffect),

                      reinterpret_cast<void**>(&g_apply_speffect)) != MH_OK) {

        LogLine("radahn_meteor: MH_CreateHook failed");

        return false;

    }

    if (MH_EnableHook(entry) != MH_OK) {

        LogLine("radahn_meteor: MH_EnableHook failed");

        return false;

    }



    LogLine("radahn_meteor: ready v8.9.25 (seed grounded fx; block fly-chain 13901/03/06/07/47)");
    LogLine("radahn_meteor: expect seed line at track; no 13947 swap");

    return true;

}


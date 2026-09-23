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
bool WriteRel32Jmp(uint8_t* from, void* to, size_t patch_len) {
    if (patch_len < 5) {
        return false;
    }
    const int64_t rel = reinterpret_cast<uint8_t*>(to) - (from + 5);
    if (rel < INT32_MIN || rel > INT32_MAX) {
        return false;
    }
    DWORD old = 0;
    if (!VirtualProtect(from, patch_len, PAGE_EXECUTE_READWRITE, &old)) {
        return false;
    }
    from[0] = 0xE9;
    *reinterpret_cast<int32_t*>(from + 1) = static_cast<int32_t>(rel);
    for (size_t i = 5; i < patch_len; ++i) {
        from[i] = 0x90;
    }
    VirtualProtect(from, patch_len, old, &old);
    FlushInstructionCache(GetCurrentProcess(), from, patch_len);
    return true;
}

uint8_t* AllocNear(void* near_addr, size_t size) {
    SYSTEM_INFO si{};
    GetSystemInfo(&si);
    const uintptr_t gran = si.dwAllocationGranularity ? si.dwAllocationGranularity : 0x10000;
    const uintptr_t center = reinterpret_cast<uintptr_t>(near_addr);

    for (uintptr_t delta = gran; delta < 0x70000000ull; delta += gran) {
        const uintptr_t probes[2] = {
            (center > delta) ? ((center - delta) & ~(gran - 1)) : 0,
            (center + delta) & ~(gran - 1),
        };
        for (uintptr_t probe : probes) {
            if (probe < 0x10000) {
                continue;
            }
            void* p = VirtualAlloc(reinterpret_cast<void*>(probe),
                                   size,
                                   MEM_COMMIT | MEM_RESERVE,
                                   PAGE_EXECUTE_READWRITE);
            if (p) {
                return static_cast<uint8_t*>(p);
            }
        }
    }
    return static_cast<uint8_t*>(
        VirtualAlloc(nullptr, size, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
}

void* ResolveCapturedChrIns(void* captured) {
    if (!captured) {
        return nullptr;
    }
    const uint64_t base = reinterpret_cast<uint64_t>(captured);
    const uint64_t inner_raw = ReadU64(base + 8);
    if (IsSanePtr(inner_raw)) {
        void* inner = reinterpret_cast<void*>(inner_raw);
        if (HasChrModules(inner) && IsPlausibleNpcId(ReadNpcParamId(inner))) {
            return inner;
        }
    }
    if (HasChrModules(captured) && IsPlausibleNpcId(ReadNpcParamId(captured))) {
        return captured;
    }
    return captured;
}

extern "C" void __fastcall HookCaptureLockTarget(void* target_chr) {
    g_capture_hits.fetch_add(1, std::memory_order_relaxed);
    g_last_raw_capture = target_chr;
    void* chr_ins = ResolveCapturedChrIns(target_chr);

    int npc = 0;
    if (chr_ins) {
        npc = ReadI32(reinterpret_cast<uint64_t>(chr_ins) + kChrNpcParamIdOff);
    }
    g_last_raw_npc = npc;

    const bool capture_ok =
        chr_ins && IsPlausibleNpcId(npc)
        && (HasChrModules(chr_ins) || IsKnownSpawnNpc(npc));
    if (capture_ok) {
        const bool changed =
            chr_ins != g_hooked_lock_target || npc != g_last_logged_capture_npc;
        g_hooked_lock_target = chr_ins;
        if (changed) {
            g_last_logged_capture_ptr = chr_ins;
            g_last_logged_capture_npc = npc;
            LogLine("enemy_debug capture: ptr=%p raw=%p npc=%d%s",
                    chr_ins,
                    target_chr,
                    npc,
                    HasChrModules(chr_ins) ? "" : " (spawn_map)");
        }
        return;
    }

    if (!target_chr) {
        if (g_hooked_lock_target) {
            g_hooked_lock_target = nullptr;
            g_last_logged_capture_ptr = nullptr;
            g_last_logged_capture_npc = 0;
            LogLine("enemy_debug capture: clear");
        }
    } else if (chr_ins != g_last_logged_capture_ptr || npc != g_last_logged_capture_npc) {
        g_last_logged_capture_ptr = chr_ins;
        g_last_logged_capture_npc = npc;
        LogLine("enemy_debug capture: reject ptr=%p raw=%p npc=%d", chr_ins, target_chr, npc);
    }
}

bool InstallTargetedNpcCapturePatch(SigScan& scanner, uint32_t& out_lock_off) {
    // TGA "Targeted Npc Info": mov rcx,[rax+08]; mov [r13+rel],rcx — ChrIns is in rax.
    static const uint8_t kPat[] = {
        0x48, 0x8B, 0x48, 0x08, 0x49, 0x89, 0x8D, 0x00, 0x00, 0x00, 0x00,
    };
    static const char kMask[] = "xxxxxxx????";
    auto* found = static_cast<uint8_t*>(
        scanner.FindPattern(kPat, kMask, static_cast<int>(sizeof(kPat))));
    if (!found) {
        LogLine("enemy_debug: TargetedNpc capture pattern miss");
        return false;
    }

    const int32_t rel = *reinterpret_cast<int32_t*>(found + 7);
    if (rel <= 0 || rel > 0x4000) {
        LogLine("enemy_debug: TargetedNpc capture rel out of range rel=0x%X", rel);
        return false;
    }
    out_lock_off = static_cast<uint32_t>(rel);

    uint8_t* patch_at = found;
    uint8_t* after = patch_at + kTargetedNpcPatchLen;

    auto* stub = AllocNear(patch_at, 160);
    if (!stub) {
        LogLine("enemy_debug: TargetedNpc capture stub alloc failed");
        return false;
    }

    // stub: capture rax (ChrIns), replay both instructions, jmp back.
    size_t o = 0;
    stub[o++] = 0x50;  // push rax
    stub[o++] = 0x48;
    stub[o++] = 0x89;
    stub[o++] = 0xC1;  // mov rcx, rax
    stub[o++] = 0x48;
    stub[o++] = 0x83;
    stub[o++] = 0xEC;
    stub[o++] = 0x20;
    stub[o++] = 0x48;
    stub[o++] = 0xB8;
    *reinterpret_cast<uint64_t*>(stub + o) = reinterpret_cast<uint64_t>(&HookCaptureLockTarget);
    o += 8;
    stub[o++] = 0xFF;
    stub[o++] = 0xD0;
    stub[o++] = 0x48;
    stub[o++] = 0x83;
    stub[o++] = 0xC4;
    stub[o++] = 0x20;
    stub[o++] = 0x58;  // pop rax
    stub[o++] = 0x48;
    stub[o++] = 0x8B;
    stub[o++] = 0x48;
    stub[o++] = 0x08;  // mov rcx,[rax+08]
    stub[o++] = 0x49;
    stub[o++] = 0x89;
    stub[o++] = 0x8D;
    *reinterpret_cast<int32_t*>(stub + o) = rel;
    o += 4;
    stub[o++] = 0xE9;
    *reinterpret_cast<int32_t*>(stub + o) = static_cast<int32_t>(after - (stub + o + 4));
    o += 4;

    if (!WriteRel32Jmp(patch_at, stub, kTargetedNpcPatchLen)) {
        VirtualFree(stub, 0, MEM_RELEASE);
        LogLine("enemy_debug: TargetedNpc capture patch write failed");
        return false;
    }

    g_lock_patch_count.store(1, std::memory_order_relaxed);
    LogLine("enemy_debug: TargetedNpc capture patched @ 0x%llX off=0x%X (rax)",
            reinterpret_cast<unsigned long long>(found),
            out_lock_off);
    return true;
}

bool InstallLockTargetCapturePatches(SigScan& scanner, uint32_t& out_lock_off) {
    return InstallTargetedNpcCapturePatch(scanner, out_lock_off);
}

bool ResolveLockTgtManPtr(SigScan& scanner, uint64_t& out_ptr_loc) {
    static const uint8_t kPat[] = {
        0x48, 0x8B, 0x0D, 0x00, 0x00, 0x00, 0x00, 0x0F, 0x57, 0xD2, 0xF3, 0x0F, 0x10,
    };
    static const char kMask[] = "xxx????xxxxxx";
    auto* found = static_cast<uint8_t*>(
        scanner.FindPattern(kPat, kMask, static_cast<int>(sizeof(kPat))));
    if (!found) {
        LogLine("enemy_debug: LockTgtMan pattern miss");
        return false;
    }
    const int32_t rel = *reinterpret_cast<int32_t*>(found + 3);
    out_ptr_loc = reinterpret_cast<uint64_t>(found) + 7 + rel;
    LogLine("enemy_debug: LockTgtMan ptr @ 0x%llX", static_cast<unsigned long long>(out_ptr_loc));
    return true;
}

bool IsGameLockOnFlagSet() {
    if (!g_lock_tgt_man_ptr_loc) {
        return false;
    }
    const uint64_t lock_man = ReadU64(g_lock_tgt_man_ptr_loc);
    if (!IsSanePtr(lock_man)) {
        return false;
    }
    return ReadU8(lock_man + kLockTgtManLockOnOff) != 0;
}

void* PollLockAtOffset(void* player_ins, uint32_t off, int* out_npc) {
    if (!player_ins) {
        return nullptr;
    }
    void* candidate = ChrPtrAt(reinterpret_cast<uint64_t>(player_ins), off);
    if (!candidate) {
        return nullptr;
    }
    const int npc = ReadNpcParamId(candidate);
    if (out_npc) {
        *out_npc = npc;
    }
    return npc > 0 ? candidate : nullptr;
}

void* PollLockFromPlayer(void* player_ins) {
    if (!player_ins) {
        return nullptr;
    }
    for (uint32_t off : kProbePollOffsets) {
        int npc = 0;
        void* candidate = PollLockAtOffset(player_ins, off, &npc);
        if (candidate && IsEnemyChrIns(player_ins, candidate)) {
            return candidate;
        }
    }
    return nullptr;
}

bool IsValidLockTarget(void* player_ins, void* candidate) {
    if (!IsEnemyChrIns(player_ins, candidate)) {
        return false;
    }
    if (!HasLivingEnemyData(candidate)) {
        return false;
    }
    const int npc = ReadI32(reinterpret_cast<uint64_t>(candidate) + kChrNpcParamIdOff);
    if (!IsKnownSpawnNpc(npc)) {
        return false;
    }

    float px = 0.0f, py = 0.0f, pz = 0.0f;
    float tx = 0.0f, ty = 0.0f, tz = 0.0f;
    if (!ReadPos(player_ins, px, py, pz) || !ReadPos(candidate, tx, ty, tz)) {
        return false;
    }
    if (std::fabs(tx) < 0.1f && std::fabs(ty) < 0.1f && std::fabs(tz) < 0.1f) {
        return false;
    }

    const float dx = tx - px;
    const float dy = ty - py;
    const float dz = tz - pz;
    const float dist_sq = dx * dx + dy * dy + dz * dz;
    const float max_dist_sq = kLockMaxDistM * kLockMaxDistM;
    if (dist_sq < 0.09f || dist_sq > max_dist_sq) {
        return false;
    }
    return true;
}

bool ResolveLockTargetOffset(SigScan& scanner, uint32_t& out_off) {
    static const uint8_t kPat[] = {
        0x48, 0x8B, 0x48, 0x08, 0x49, 0x89, 0x8D, 0x00, 0x00, 0x00, 0x00,
    };
    static const char kMask[] = "xxxxxxx????";
    auto* found = static_cast<uint8_t*>(
        scanner.FindPattern(kPat, kMask, static_cast<int>(sizeof(kPat))));
    if (!found) {
        LogLine("enemy_debug: lock-target pattern miss; fallback off=0x%X", kDefaultLockTargetOff);
        out_off = kDefaultLockTargetOff;
        return false;
    }
    const int32_t rel = *reinterpret_cast<int32_t*>(found + 7);
    if (rel <= 0 || rel > 0x4000) {
        LogLine("enemy_debug: lock-target offset out of range rel=0x%X; fallback", rel);
        out_off = kDefaultLockTargetOff;
        return false;
    }
    out_off = static_cast<uint32_t>(rel);
    LogLine("enemy_debug: lock-target off=0x%X", out_off);
    return true;
}

void* GetLockOnTarget(void* player_ins) {
    auto resolve_capture_ptr = []() -> void* {
        void* hooked = ResolveCapturedChrIns(g_hooked_lock_target);
        if (!hooked) {
            hooked = g_hooked_lock_target;
        }
        if (!hooked && g_last_raw_capture) {
            hooked = ResolveCapturedChrIns(g_last_raw_capture);
            if (!hooked) {
                hooked = g_last_raw_capture;
            }
        }
        return hooked;
    };

    if (IsGameLockOnFlagSet()) {
        void* hooked = resolve_capture_ptr();
        if (hooked) {
            const int npc = ReadNpcParamId(hooked);
            if (IsKnownSpawnNpc(npc)) {
                return hooked;
            }
            if (IsEnemyChrIns(player_ins, hooked)) {
                return hooked;
            }
        }
    }

    if (player_ins) {
        int lock_npc = 0;
        void* game_lock = PollLockAtOffset(player_ins, g_lock_target_off, &lock_npc);
        if (game_lock && IsEnemyChrIns(player_ins, game_lock)) {
            return game_lock;
        }
    }

    void* polled = PollLockFromPlayer(player_ins);
    if (polled && IsEnemyChrIns(player_ins, polled)) {
        return polled;
    }

    void* hooked = resolve_capture_ptr();
    if (hooked && IsEnemyChrIns(player_ins, hooked)) {
        return hooked;
    }

    if (hooked && IsGameLockOnFlagSet()) {
        const int npc = ReadNpcParamId(hooked);
        if (IsPlausibleNpcId(npc)) {
            return hooked;
        }
    }
    return nullptr;
}
}  // namespace enemy_debug_internal

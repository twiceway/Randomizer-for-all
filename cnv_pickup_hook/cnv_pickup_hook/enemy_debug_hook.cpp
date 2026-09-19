#include "enemy_debug_hook.h"

#include "enemy_debug_shared.h"
#include "log.h"
#include "sigscan.h"

#include <thread>

namespace enemy_debug_internal {

void DebugHudWorker(SigScan scanner) {
    ResolveWorldChrManPtr(scanner, g_world_chr_man_ptr_loc);
    ResolveLockTgtManPtr(scanner, g_lock_tgt_man_ptr_loc);
    if (kEnableLockCapturePatch) {
        g_lock_capture_installed = InstallLockTargetCapturePatches(scanner, g_lock_target_off);
    } else {
        g_lock_capture_installed = false;
        LogLine("enemy_debug: lock capture OFF (probe-only; no code patch)");
    }
    if (!g_lock_capture_installed) {
        ResolveLockTargetOffset(scanner, g_lock_target_off);
    }
    ResolveMapIdOffset(scanner, g_map_id_off);
    DebugHudLoop();
}

}  // namespace enemy_debug_internal

bool StartEnemyDebugHud(SigScan& scanner) {
    if (enemy_debug_internal::g_worker_started.exchange(true)) {
        return true;
    }
    std::thread(enemy_debug_internal::DebugHudWorker, scanner).detach();
    return true;
}

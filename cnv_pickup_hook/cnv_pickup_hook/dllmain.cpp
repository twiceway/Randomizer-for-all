#include <windows.h>

#include "hook.h"

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(module);
        StartPickupHookWorker();
    }
    return TRUE;
}

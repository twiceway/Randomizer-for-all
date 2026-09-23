#include "sigscan.h"

bool SigScan::GetImageInfo() {
    module_handle = GetModuleHandleA("eldenring.exe");
    if (!module_handle) {
        return false;
    }

    MEMORY_BASIC_INFORMATION mem_info{};
    if (VirtualQuery(module_handle, &mem_info, sizeof(mem_info)) == 0) {
        return false;
    }

    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(module_handle);
    auto* pe = reinterpret_cast<IMAGE_NT_HEADERS*>(
        reinterpret_cast<ULONG_PTR>(mem_info.AllocationBase) + dos->e_lfanew);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE || pe->Signature != IMAGE_NT_SIGNATURE) {
        return false;
    }

    base_address = mem_info.AllocationBase;
    image_size = pe->OptionalHeader.SizeOfImage;
    return true;
}

void* SigScan::FindSignature(Signature& sig) {
    return FindPattern(reinterpret_cast<const uint8_t*>(sig.signature), sig.mask, sig.length);
}

void* SigScan::FindPattern(const uint8_t* pattern, const char* mask, int length) {
    if (!pattern || !mask || length <= 0 || !base_address || image_size < static_cast<SIZE_T>(length)) {
        return nullptr;
    }
    auto* scan = static_cast<uint8_t*>(base_address);
    uint8_t* max_address = scan + image_size - length;

    while (scan < max_address) {
        int matched = 0;
        for (int i = 0; i < length; ++i) {
            if (mask[i] == '?' || scan[i] == pattern[i]) {
                ++matched;
            } else {
                break;
            }
        }
        if (matched == length) {
            return scan;
        }
        ++scan;
    }
    return nullptr;
}

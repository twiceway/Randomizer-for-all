#pragma once
#include <windows.h>
#include <cstdint>

struct Signature {
    const char* signature;
    const char* mask;
    int length;
    int offset;
};

class SigScan {
public:
    bool GetImageInfo();
    void* FindSignature(Signature& sig);
    // Pattern may contain 0x00 bytes (C string Signature cannot).
    void* FindPattern(const uint8_t* pattern, const char* mask, int length);
    void* GetBaseAddress() const { return base_address; }
    SIZE_T GetImageSize() const { return image_size; }

private:
    HMODULE module_handle = nullptr;
    void* base_address = nullptr;
    SIZE_T image_size = 0;
};

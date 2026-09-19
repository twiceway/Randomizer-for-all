#include "runtime_map.h"

#include "globals.h"
#include "log.h"

#include <cstdio>
#include <cstring>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace RuntimeMap {

namespace {

struct TargetSpec {
    uint32_t raw = 0;
    uint32_t cat = 0;
};

std::unordered_set<uint32_t> g_target_ids;
std::unordered_map<uint32_t, uint32_t> g_target_cats;
std::vector<LotPatch> g_lot_patches;
uint32_t g_seed = 0;
bool g_loaded = false;

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

uint32_t PickupTypeNibble(uint32_t cat) {
    switch (cat) {
        case 0:
            return 0;
        case 1:
            return 4;
        case 2:
            return 3;
        case 3:
            return 5;
        case 4:
            return 5;
        case 5:
            return 6;
        default:
            return 0;
    }
}

uint32_t EncodePickupId(uint32_t raw_id, uint32_t cat) {
    const uint32_t masked = raw_id & kItemIdMask;
    if (cat == 0) {
        return masked;
    }
    if (cat == 1) {
        return kGoodsTypePrefix | masked;
    }
    const uint32_t nibble = PickupTypeNibble(cat);
    return (nibble << 28) | masked;
}

bool IsBellBearingGoods(uint32_t raw_id) {
  // Memory stone / bell bearing band (not golden runes 2900-2999).
    return raw_id >= 229000 && raw_id <= 229099;
}

}  // namespace

bool Load(const char* path) {
    g_target_ids.clear();
    g_target_cats.clear();
    g_lot_patches.clear();
    g_seed = 0;
    g_loaded = false;

    FILE* file = nullptr;
    if (fopen_s(&file, path, "r") != 0 || !file) {
        LogLine("runtime map: not found (%s)", path ? path : "(null)");
        return false;
    }

    char line[256];
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
            if (strcmp(key, "seed") == 0) {
                ParseUint(value, g_seed);
            }
            continue;
        }

        if (strncmp(line, "lot ", 4) != 0) {
            continue;
        }

        uint32_t lot_id = 0;
        uint32_t slot = 0;
        uint32_t target = 0;
        uint32_t target_cat = 0;
        uint32_t runtime_source = 0;
        const int parsed =
            sscanf_s(line, "lot %u %u %u %u %u", &lot_id, &slot, &target, &target_cat, &runtime_source);
        if (parsed >= 3 && lot_id > 0 && slot >= 1 && slot <= 8 && target > 0) {
            g_lot_patches.push_back(
                LotPatch{lot_id,
                         slot,
                         target,
                         parsed >= 4 ? target_cat : 0,
                         parsed >= 5 ? runtime_source : 0});
            g_target_ids.insert(target);
            if (parsed >= 4) {
                g_target_cats[target] = target_cat;
            }
        }
    }

    fclose(file);
    g_loaded = !g_lot_patches.empty();
    LogLine("runtime map: %s lots=%zu seed=%u",
            g_loaded ? "loaded" : "empty",
            g_lot_patches.size(),
            g_seed);
    return g_loaded;
}

bool IsLoaded() {
    return g_loaded;
}

uint32_t Seed() {
    return g_seed;
}

size_t PairCount() {
    return 0;
}

size_t LotPatchCount() {
    return g_lot_patches.size();
}

const LotPatch* LotPatches() {
    return g_lot_patches.empty() ? nullptr : g_lot_patches.data();
}

const LotPatch* LotPatchAt(size_t index) {
    if (index >= g_lot_patches.size()) {
        return nullptr;
    }
    return &g_lot_patches[index];
}

bool HasSource(uint32_t raw_id) {
    (void)raw_id;
    return false;
}

uint32_t TargetForRaw(uint32_t raw_id) {
    return raw_id;
}

uint32_t TargetCategoryForRaw(uint32_t raw_id) {
    (void)raw_id;
    return 0;
}

bool IsKnownTarget(uint32_t raw_id) {
    return g_target_ids.find(raw_id) != g_target_ids.end();
}

uint32_t CategoryForKnownTarget(uint32_t raw_id) {
    const auto it = g_target_cats.find(raw_id);
    if (it != g_target_cats.end()) {
        return it->second;
    }
    return 0;
}

bool IsUniqueTarget(uint32_t raw_id, uint32_t cat) {
    if (cat == 0 || cat == 2 || cat == 3 || cat == 4 || cat == 5) {
        return true;
    }
    if (cat == 1) {
        if (IsBellBearingGoods(raw_id)) {
            return true;
        }
        if (raw_id == 10010 || raw_id == 10020 || raw_id == 130) {
            return true;
        }
        if (raw_id >= 1001 && raw_id <= 1023) {
            return true;
        }
    }
    return false;
}

uint32_t RemapEncoded(uint32_t encoded_id) {
    return encoded_id;
}

uint32_t EncodeTargetPickupId(uint32_t raw_id, uint32_t cat) {
    return EncodePickupId(raw_id, cat);
}

}  // namespace RuntimeMap

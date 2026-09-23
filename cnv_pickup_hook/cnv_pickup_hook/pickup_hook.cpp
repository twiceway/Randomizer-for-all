#include "globals.h"
#include "log.h"
#include "runtime_map.h"
#include "enemy_spawn_map.h"
#include "enemy_debug_hook.h"
#include "radahn_meteor_hook.h"
#include "pickup_item_rules.h"
#include "sigscan.h"

#include <MinHook.h>
#include <chrono>
#include <cwchar>
#include <intrin.h>
#include <thread>

namespace {

using namespace cnv_pickup_item_rules;

struct GiveCallSites {
    uint64_t exe_base = 0;
    uint64_t give_item = 0;
    uint64_t map_give_callsite = 0;
    uint64_t lua_give_callsite = 0;
};

give_item_function* g_vanilla_give_item = nullptr;
void* g_map_hook_target = nullptr;
get_inventoryid_function g_find_inventory_id = nullptr;
uint64_t g_game_data_man_ptr_loc = 0;
uint64_t g_map_item_man = 0;
uint64_t g_solo_repo_ptr = 0;
GiveCallSites g_sites;
uint32_t g_give_item_seq = 0;
thread_local bool g_give_item_remapped = false;

uint32_t RawItemId(uint32_t encoded_id);
uint32_t ItemTypeNibble(uint32_t encoded_id);
bool ShouldReplaceItem(uint32_t encoded_id);
bool PlayerOwnsEncodedItem(uint32_t encoded_id);
void NormalizeGiveItemEncoding(ItemGiveStruct* item_info);
void MapPickupDetour(uint64_t map_item_manager, ItemGiveStruct* item_info, void* item_details);
void NormalizeUniquePickupFields(ItemGiveStruct* item_info);
ItemLotRow* FindItemLotRow(uint64_t solo_repo, uint32_t lot_id);
void TryUniqueLotPickupFix(uint64_t solo_repo_ptr, ItemGiveStruct* item_info);
void ApplyLotPatchPickupFallback(uint64_t solo_repo_ptr, ItemGiveStruct* item_info);

uint64_t Rva(void* addr) {
    if (!addr || !g_sites.exe_base) {
        return 0;
    }
    return reinterpret_cast<uint64_t>(addr) - g_sites.exe_base;
}

void LogStackFrames(const char* tag, int skip, int count) {
    void* frames[16] = {};
    const USHORT captured = CaptureStackBackTrace(
        static_cast<DWORD>(skip),
        static_cast<DWORD>(count),
        frames,
        nullptr);
    for (USHORT i = 0; i < captured; ++i) {
        LogLine("%s stack[%u]=0x%llX rva=0x%llX",
                tag,
                i,
                reinterpret_cast<unsigned long long>(frames[i]),
                static_cast<unsigned long long>(Rva(frames[i])));
    }
}

const char* ClassifyReturnAddress(void* ret_addr) {
    if (!ret_addr) {
        return "null";
    }
    const uint64_t ret = reinterpret_cast<uint64_t>(ret_addr);

    if (g_sites.map_give_callsite) {
        const int64_t delta = static_cast<int64_t>(ret) - static_cast<int64_t>(g_sites.map_give_callsite);
        if (delta >= -0x200 && delta <= 0x200) {
            LogLine("  caller delta from map give site = %+lld (0x%llX)", delta, static_cast<long long>(delta));
            return "MapItemManagerImp (map/chest pickup)";
        }
    }

    if (g_sites.lua_give_callsite) {
        const int64_t delta = static_cast<int64_t>(ret) - static_cast<int64_t>(g_sites.lua_give_callsite);
        if (delta >= -0x200 && delta <= 0x200) {
            LogLine("  caller delta from lua give site = %+lld (0x%llX)", delta, static_cast<long long>(delta));
            return "LuaEventManagerImp (AwardItems/boss/pillar)";
        }
    }

    if (g_sites.give_item) {
        const int64_t delta = static_cast<int64_t>(ret) - static_cast<int64_t>(g_sites.give_item);
        if (delta >= 0 && delta <= 0x400) {
            LogLine("  caller delta from give_item entry = %+lld", static_cast<long long>(delta));
            return "inside/near give_item (tail call?)";
        }
    }

    if (g_sites.map_give_callsite) {
        LogLine("  caller delta from map give site = %+lld",
                static_cast<long long>(static_cast<int64_t>(ret) -
                                       static_cast<int64_t>(g_sites.map_give_callsite)));
    }
    if (g_sites.lua_give_callsite) {
        LogLine("  caller delta from lua give site = %+lld",
                static_cast<long long>(static_cast<int64_t>(ret) -
                                       static_cast<int64_t>(g_sites.lua_give_callsite)));
    }

    return "unknown/other";
}

void LogGiveItemEnter(uint64_t map_item_manager, ItemGiveStruct* item_info, void* item_details) {
    const uint32_t seq = ++g_give_item_seq;
    void* ret_addr = _ReturnAddress();

    LogLine("--- map give #%u ---", seq);
    LogLine("  caller_ret=0x%llX rva=0x%llX route=%s",
            reinterpret_cast<unsigned long long>(ret_addr),
            static_cast<unsigned long long>(Rva(ret_addr)),
            ClassifyReturnAddress(ret_addr));
    LogLine("  map_item_man=0x%llX item_info=0x%llX item_details=0x%llX",
            static_cast<unsigned long long>(map_item_manager),
            reinterpret_cast<unsigned long long>(item_info),
            reinterpret_cast<unsigned long long>(item_details));

    if (!item_info) {
        LogLine("  item_info is null");
        LogStackFrames("  ", 2, 6);
        return;
    }

    const uint32_t max_items = static_cast<uint32_t>(sizeof(item_info->item_info) / sizeof(ItemInfo));
    const uint32_t count =
        item_info->item_struct_count > max_items ? max_items : item_info->item_struct_count;
    LogLine("  item_struct_count=%u", item_info->item_struct_count);

    for (uint32_t i = 0; i < count; ++i) {
        const ItemInfo* slot = &item_info->item_info[i];
        LogLine("  slot[%u]: id=%u raw=%u type=%u qty=%u relay=%u ash=%u replace=%s",
                i,
                slot->item_id,
                RawItemId(slot->item_id),
                ItemTypeNibble(slot->item_id),
                slot->item_quantity,
                slot->item_relayvalue,
                slot->item_ashes_of_war,
                ShouldReplaceItem(slot->item_id) ? "YES" : "no");
    }

    LogStackFrames("  ", 2, 8);
}

void LogKnownCallSites() {
    LogLine("exe base=0x%llX", static_cast<unsigned long long>(g_sites.exe_base));
    LogLine("give_item       = 0x%llX rva=0x%llX (vanilla ptr, not hooked)",
            static_cast<unsigned long long>(g_sites.give_item),
            static_cast<unsigned long long>(Rva(reinterpret_cast<void*>(g_sites.give_item))));
    LogLine("map give site   = 0x%llX rva=0x%llX (MapItemManagerImp — HOOKED)",
            static_cast<unsigned long long>(g_sites.map_give_callsite),
            static_cast<unsigned long long>(Rva(reinterpret_cast<void*>(g_sites.map_give_callsite))));
    LogLine("lua give site   = 0x%llX rva=0x%llX (LuaEventManagerImp — NOT hooked, gather vanilla)",
            static_cast<unsigned long long>(g_sites.lua_give_callsite),
            static_cast<unsigned long long>(Rva(reinterpret_cast<void*>(g_sites.lua_give_callsite))));
}

bool ResolveLukeGiveCallSites(SigScan& scanner) {
    Signature map_sig{
        "\x4C\x8D\x45\x34\x48\x8D\x55\x90",
        "xxxxxxxx",
        8,
        0,
    };
    if (auto* found = scanner.FindSignature(map_sig)) {
        g_sites.map_give_callsite = reinterpret_cast<uint64_t>(found) + 11;
    } else {
        LogLine("signature miss: MapItemManagerImp give callsite");
    }

    Signature lua_sig{
        "\xE8\xFF\xFF\xFF\xFF\x83\x7D\x98\x00\x74",
        "x????xxxxx",
        10,
        0,
    };
    if (auto* found = scanner.FindSignature(lua_sig)) {
        g_sites.lua_give_callsite = reinterpret_cast<uint64_t>(found);
    } else {
        LogLine("signature miss: LuaEventManagerImp give callsite");
    }

    return g_sites.map_give_callsite != 0 || g_sites.lua_give_callsite != 0;
}

void LogTestLotRows(uint64_t) {
    // Lot row logging disabled in v6 (runtime map drives replacements).
}

uint32_t RawItemId(uint32_t encoded_id) {
    return encoded_id & kItemIdMask;
}

uint32_t ItemTypeNibble(uint32_t encoded_id) {
    return encoded_id >> 28;
}

bool ShouldReplaceItem(uint32_t encoded_id) {
    return RuntimeMap::HasSource(RawItemId(encoded_id));
}

bool PlayerOwnsEncodedItem(uint32_t encoded_id) {
    if (!g_find_inventory_id || !g_game_data_man_ptr_loc) {
        return false;
    }
    const uint64_t game_data_man = *reinterpret_cast<uint64_t*>(g_game_data_man_ptr_loc);
    if (!game_data_man) {
        return false;
    }
    const uint64_t inventory_manager = *reinterpret_cast<uint64_t*>(game_data_man + 0x08);
    if (!inventory_manager) {
        return false;
    }
    uint32_t probe_id = encoded_id;
    return g_find_inventory_id(inventory_manager + 0x408, &probe_id) >= 0;
}

void RememberMapItemMan(uint64_t man) {
    if (man && man != g_map_item_man) {
        g_map_item_man = man;
        LogLine("MapItemMan captured @ 0x%llX", static_cast<unsigned long long>(man));
    }
}

void BuildWeaponGiveStruct(ItemGiveStruct* item_info, uint32_t weapon_id) {
    item_info->item_struct_count = 1;
    item_info->item_info[0].item_id = weapon_id;
    item_info->item_info[0].item_quantity = 1;
    item_info->item_info[0].item_relayvalue = 0;
    item_info->item_info[0].item_ashes_of_war = UINT32_MAX;
}

void ForceGiveWeapon(uint64_t map_item_manager, uint32_t weapon_id) {
    if (!g_vanilla_give_item || !map_item_manager) {
        return;
    }
    ItemGiveStruct give = {};
    BuildWeaponGiveStruct(&give, weapon_id);
    g_vanilla_give_item(map_item_manager, &give, nullptr);
}

constexpr uint32_t kDuplicateFallbackRune = 2900;

void ApplyDuplicateFallback(ItemInfo* slot) {
    slot->item_id = kGoodsTypePrefix | kDuplicateFallbackRune;
    slot->item_quantity = 1;
    slot->item_relayvalue = 0;
    slot->item_ashes_of_war = UINT32_MAX;
}

void RewritePickupItems(ItemGiveStruct* item_info) {
    if (!item_info || item_info->item_struct_count == 0) {
        return;
    }

    g_give_item_remapped = false;
    const uint32_t max_items = static_cast<uint32_t>(sizeof(item_info->item_info) / sizeof(ItemInfo));
    const uint32_t count =
        item_info->item_struct_count > max_items ? max_items : item_info->item_struct_count;

    for (uint32_t i = 0; i < count; ++i) {
        ItemInfo* slot = &item_info->item_info[i];
        const uint32_t raw_id = RawItemId(slot->item_id);
        // Lot patches (corpse glow etc.) are applied above; skip only legacy pair remap.
        if (IsGatheringMaterial(raw_id)) {
            continue;
        }
        const bool mapped_source = RuntimeMap::HasSource(raw_id);
        const bool known_target = RuntimeMap::IsKnownTarget(raw_id);

        if (!mapped_source && !known_target) {
            continue;
        }

        uint32_t tgt_raw = raw_id;
        uint32_t tgt_cat = 0;
        uint32_t new_id = slot->item_id;

        if (mapped_source) {
            tgt_raw = RuntimeMap::TargetForRaw(raw_id);
            tgt_cat = RuntimeMap::TargetCategoryForRaw(raw_id);
            new_id = RuntimeMap::RemapEncoded(slot->item_id);
        } else {
            tgt_cat = RuntimeMap::CategoryForKnownTarget(raw_id);
            if (tgt_cat == 0) {
                tgt_cat = ItemTypeNibble(slot->item_id) == 4 ? 1 : 0;
            }
        }

        if (RuntimeMap::IsUniqueTarget(tgt_raw, tgt_cat) &&
            PlayerOwnsEncodedItem(mapped_source ? new_id : slot->item_id)) {
            LogLine("give_item duplicate unique raw %u -> %u, fallback rune %u",
                    raw_id,
                    tgt_raw,
                    kDuplicateFallbackRune);
            ApplyDuplicateFallback(slot);
            g_give_item_remapped = true;
            continue;
        }

        if (!mapped_source) {
            continue;
        }

        LogLine("give_item REPLACE slot %u: raw %u -> raw %u",
                i,
                raw_id,
                RawItemId(new_id));
        LogLine("  before: id=%u qty=%u relay=%u ash=%u",
                slot->item_id,
                slot->item_quantity,
                slot->item_relayvalue,
                slot->item_ashes_of_war);
        slot->item_id = new_id;
        if (tgt_cat != 1 || RuntimeMap::IsUniqueTarget(tgt_raw, tgt_cat)) {
            slot->item_quantity = 1;
        }
        if (RuntimeMap::IsUniqueTarget(tgt_raw, tgt_cat)) {
            slot->item_relayvalue = 0;
            if (tgt_cat == 0) {
                slot->item_ashes_of_war = UINT32_MAX;
            }
        }
        g_give_item_remapped = true;
        LogLine("  after:  id=%u qty=%u relay=%u ash=%u",
                slot->item_id,
                slot->item_quantity,
                slot->item_relayvalue,
                slot->item_ashes_of_war);
    }
}

void MapPickupDetour(uint64_t map_item_manager, ItemGiveStruct* item_info, void* item_details) {
    LogGiveItemEnter(map_item_manager, item_info, item_details);
    RememberMapItemMan(map_item_manager);

    if (g_solo_repo_ptr) {
        ApplyLotPatchPickupFallback(g_solo_repo_ptr, item_info);
        TryUniqueLotPickupFix(g_solo_repo_ptr, item_info);
    }
    RewritePickupItems(item_info);
    NormalizeGiveItemEncoding(item_info);
    NormalizeUniquePickupFields(item_info);

    if (g_vanilla_give_item) {
        g_vanilla_give_item(map_item_manager, item_info, item_details);
    }
    LogLine("--- map give #%u done ---", g_give_item_seq);
}

void NormalizeUniquePickupFields(ItemGiveStruct* item_info) {
    if (!item_info || item_info->item_struct_count == 0) {
        return;
    }
    const uint32_t max_items =
        static_cast<uint32_t>(sizeof(item_info->item_info) / sizeof(ItemInfo));
    const uint32_t count =
        item_info->item_struct_count > max_items ? max_items : item_info->item_struct_count;
    for (uint32_t i = 0; i < count; ++i) {
        ItemInfo* slot = &item_info->item_info[i];
        uint32_t raw_id = RawItemId(slot->item_id);
        const uint32_t base_ash = SpiritAshBaseId(raw_id);
        if (base_ash != raw_id) {
            const uint32_t nibble = ItemTypeNibble(slot->item_id);
            const uint32_t new_id = nibble == 0 ? base_ash : slot->item_id - raw_id + base_ash;
            LogLine("give_item spirit ash tier fix slot %u: raw %u -> base %u (id %u -> %u)",
                    i,
                    raw_id,
                    base_ash,
                    slot->item_id,
                    new_id);
            slot->item_id = new_id;
            raw_id = base_ash;
        }
        uint32_t cat = RuntimeMap::CategoryForKnownTarget(raw_id);
        if (cat == 0) {
            const uint32_t nibble = ItemTypeNibble(slot->item_id);
            cat = nibble == 4 ? 1 : (nibble == 5 ? 4 : 0);
        }
        if (IsSpiritAshGoods(raw_id) || RuntimeMap::IsUniqueTarget(raw_id, cat)) {
            if (slot->item_quantity != 1 || slot->item_relayvalue != 0) {
                LogLine("give_item normalize unique slot %u: raw %u qty %u -> 1 relay %u -> 0",
                        i,
                        raw_id,
                        slot->item_quantity,
                        slot->item_relayvalue);
            }
            slot->item_quantity = 1;
            slot->item_relayvalue = 0;
            if (cat == 0) {
                slot->item_ashes_of_war = UINT32_MAX;
            }
        }
    }
}

void NormalizeGiveItemEncoding(ItemGiveStruct* item_info) {
    if (!item_info || item_info->item_struct_count == 0) {
        return;
    }
    const uint32_t max_items =
        static_cast<uint32_t>(sizeof(item_info->item_info) / sizeof(ItemInfo));
    const uint32_t count =
        item_info->item_struct_count > max_items ? max_items : item_info->item_struct_count;
    for (uint32_t i = 0; i < count; ++i) {
        ItemInfo* slot = &item_info->item_info[i];
        const uint32_t nibble = ItemTypeNibble(slot->item_id);
        const uint32_t raw = RawItemId(slot->item_id);
        if (nibble == 8) {
            const uint32_t fixed = (5u << 28) | raw;
            LogLine("give_item encode fix slot %u: id %u (type 8) -> %u (type 5 gem)",
                    i,
                    slot->item_id,
                    fixed);
            slot->item_id = fixed;
        }
    }
}

bool ResolveSoloParamRepository(SigScan& scanner, uint64_t& out_repo) {
    Signature sig{
        "\x48\x8B\x0D\xFF\xFF\xFF\xFF\x48\x85\xC9\x0F\x84\xFF\xFF\xFF\xFF\x45\x33\xC0\xBA\x90",
        "xxx????xxxxx????xxxxx",
        21,
        0,
    };
    auto* found = scanner.FindSignature(sig);
    if (!found) {
        LogLine("signature miss: solo_param_repository");
        return false;
    }
    const auto rip = reinterpret_cast<uint64_t>(found);
    out_repo = rip + *(int32_t*)(rip + 3) + 7;
    LogLine("solo_param_repository ptr @ 0x%llX", static_cast<unsigned long long>(out_repo));
    return out_repo != 0;
}

bool ResolveGameDataManPtr(SigScan& scanner, uint64_t& out_ptr_location) {
    Signature sig{
        "\x48\x8B\x05\xFF\xFF\xFF\xFF\x48\x8B\x48\x08\x48\x85\xC9\x74\xFF\x0F\xB6\x81\xE4",
        "xxx????xxxxxxxx?xxxx",
        20,
        0,
    };
    auto* found = scanner.FindSignature(sig);
    if (!found) {
        LogLine("signature miss: GameDataMan");
        return false;
    }
    const auto rip = reinterpret_cast<uint64_t>(found);
    out_ptr_location = rip + *(int32_t*)(rip + 3) + 7;
    LogLine("GameDataMan ptr @ 0x%llX", static_cast<unsigned long long>(out_ptr_location));
    return out_ptr_location != 0;
}

bool ResolveMapItemMan(SigScan& scanner, uint64_t& out_man) {
    Signature sig{
        "\x48\x8B\x0D\xFF\xFF\xFF\xFF\xC7\x44\x24\x50\xFF\xFF\xFF\xFF",
        "xxx????xxxxxxxx",
        15,
        0,
    };
    auto* found = scanner.FindSignature(sig);
    if (!found) {
        LogLine("signature miss: MapItemMan");
        return false;
    }
    const auto rip = reinterpret_cast<uint64_t>(found);
    const uint64_t ptr = rip + *(int32_t*)(rip + 3) + 7;
    out_man = *(uint64_t*)ptr;
    if (out_man) {
        LogLine("MapItemMan @ 0x%llX", static_cast<unsigned long long>(out_man));
    }
    return out_man != 0;
}

void ResolveMapItemManLoop() {
    SigScan scanner;
    if (!scanner.GetImageInfo()) {
        LogLine("MapItemMan retry: no image");
        return;
    }
    for (int attempt = 0; attempt < 240; ++attempt) {
        uint64_t man = 0;
        if (ResolveMapItemMan(scanner, man)) {
            RememberMapItemMan(man);
            return;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }
    LogLine("MapItemMan unresolved after retries (will capture from give_item)");
}

bool GetItemLotTableAt(
    uint64_t solo_repo_ptr,
    uint64_t table_off,
    uint64_t& out_itemlot,
    uint32_t& out_entries,
    uint64_t& out_id_repo) {
    const uint64_t repo = *(uint64_t*)solo_repo_ptr;
    if (!repo) {
        return false;
    }

    uint64_t itemlot = *(uint64_t*)(repo + table_off);
    if (!itemlot) {
        return false;
    }
    itemlot = *(uint64_t*)(itemlot + 0x80);
    itemlot = *(uint64_t*)(itemlot + 0x80);
    if (!itemlot) {
        return false;
    }

    out_itemlot = itemlot;
    out_entries = *(uint32_t*)(itemlot - 0x0C);
    const uint32_t start_offset = (*(uint32_t*)(itemlot - 0x10) + 15) & ~15u;
    out_id_repo = itemlot + start_offset;
    return true;
}

bool GetItemLotTable(uint64_t solo_repo_ptr, uint64_t& out_itemlot, uint32_t& out_entries, uint64_t& out_id_repo) {
    // ItemLotParam_map — confirmed offset used by CNV hook / Luke map shuffle.
    return GetItemLotTableAt(solo_repo_ptr, 0x670, out_itemlot, out_entries, out_id_repo);
}

bool GetItemLotTableByName(
    uint64_t solo_repo_ptr,
    const wchar_t* want_name,
    uint64_t& out_itemlot,
    uint32_t& out_entries,
    uint64_t& out_id_repo) {
    const uint64_t repo = *(uint64_t*)solo_repo_ptr;
    if (!repo || !want_name) {
        return false;
    }
    // Luke RandomiseGenericParamContainer walk (SoloParamRepository entries).
    for (int i = 0; i < 185; ++i) {
        const int param_offset = i * 0x48;
        if (*(int*)(repo + param_offset + 0x80) <= 0) {
            continue;
        }
        uint64_t param_container = *(uint64_t*)(repo + param_offset + 0x88);
        if (!param_container) {
            continue;
        }
        wchar_t* container_name = (wchar_t*)(param_container + 0x18);
        if (*(uint32_t*)(param_container + 0x28) >= 8) {
            container_name = (wchar_t*)(*(uint64_t*)container_name);
        }
        if (!container_name) {
            continue;
        }
        if (wcsncmp(want_name, container_name, wcslen(want_name)) != 0) {
            continue;
        }
        uint64_t itemlot = *(uint64_t*)(param_container + 0x80);
        if (!itemlot) {
            return false;
        }
        itemlot = *(uint64_t*)(itemlot + 0x80);
        if (!itemlot) {
            return false;
        }
        out_itemlot = itemlot;
        out_entries = *(uint32_t*)(itemlot - 0x0C);
        const uint32_t start_offset = (*(uint32_t*)(itemlot - 0x10) + 15) & ~15u;
        out_id_repo = itemlot + start_offset;
        return true;
    }
    return false;
}

ItemLotRow* FindItemLotRowInTable(
    uint64_t itemlot,
    uint32_t param_entries,
    uint64_t id_repo,
    uint32_t lot_id) {
    for (uint32_t i = 1; i < param_entries; ++i) {
        const uint32_t id = *(uint32_t*)(id_repo + (i * 8));
        if (id != lot_id) {
            continue;
        }
        const int32_t entry = *(int32_t*)(id_repo + (i * 8) + 4);
        if (entry < 0) {
            continue;
        }
        const uint32_t container_offset = (static_cast<uint32_t>(entry) + 3) * 3;
        return reinterpret_cast<ItemLotRow*>(
            itemlot + *(uint64_t*)(itemlot + (container_offset * 8)));
    }
    return nullptr;
}

ItemLotRow* FindItemLotRow(uint64_t solo_repo, uint32_t lot_id) {
    uint64_t itemlot = 0;
    uint32_t param_entries = 0;
    uint64_t id_repo = 0;
    if (GetItemLotTable(solo_repo, itemlot, param_entries, id_repo)) {
        ItemLotRow* row = FindItemLotRowInTable(itemlot, param_entries, id_repo, lot_id);
        if (row) {
            return row;
        }
    }
    // Narrow fallback: enemy drop table (scarab / remnant lots if ever patched here).
    if (GetItemLotTableByName(
            solo_repo, L"ItemLotParam_enemy", itemlot, param_entries, id_repo)) {
        return FindItemLotRowInTable(itemlot, param_entries, id_repo, lot_id);
    }
    return nullptr;
}

bool ResolveInventoryIdFunction(SigScan& scanner) {
    Signature sig{
        "\x40\x56\x48\x83\xEC\x20\x83\xCE",
        "xxxxxxxx",
        8,
        0,
    };
    auto* found = scanner.FindSignature(sig);
    if (!found) {
        LogLine("signature miss: find_inventoryid");
        return false;
    }
    g_find_inventory_id = reinterpret_cast<get_inventoryid_function>(found);
    LogLine("find_inventoryid @ 0x%llX", reinterpret_cast<unsigned long long>(found));
    return true;
}

MapItemType CsvCatToMapItemType(uint32_t csv_cat) {
    switch (csv_cat) {
        case 0:
            return kMapItemWeapon;
        case 1:
            return kMapItemGoods;
        case 2:
            return kMapItemArmour;
        case 3:
            return kMapItemAccessory;
        case 4:
            return kMapItemGem;
        case 5:
            return kMapItemGoods;
        default:
            return kMapItemGoods;
    }
}

bool IsLotPatchApplied(uint64_t solo_repo_ptr, const RuntimeMap::LotPatch& patch) {
    if (IsSpellRuneCrushLot(patch.lot_id)) {
        return false;
    }
    ItemLotRow* row = FindItemLotRow(solo_repo_ptr, patch.lot_id);
    if (!row || patch.slot < 1 || patch.slot > 8) {
        return false;
    }
    return row->item_id_array[patch.slot - 1] == patch.target_raw;
}

bool LotPatchMatchesPickup(
    uint64_t solo_repo_ptr,
    const RuntimeMap::LotPatch& patch,
    uint32_t raw_id) {
    if (patch.target_raw == raw_id) {
        return false;
    }
    ItemLotRow* row = FindItemLotRow(solo_repo_ptr, patch.lot_id);
    if (!row || patch.slot < 1 || patch.slot > 8) {
        return false;
    }
    const uint32_t mem_id = row->item_id_array[patch.slot - 1];
    if (mem_id == raw_id) {
        return true;
    }
    if (patch.runtime_source != 0 && raw_id == patch.runtime_source &&
        mem_id == patch.target_raw) {
        return true;
    }
    return false;
}

bool ApplyLotPatch(uint64_t solo_repo_ptr, const RuntimeMap::LotPatch& patch) {
    if (IsSpellRuneCrushLot(patch.lot_id)) {
        return false;
    }
    ItemLotRow* row = FindItemLotRow(solo_repo_ptr, patch.lot_id);
    if (!row || patch.slot < 1 || patch.slot > 8) {
        return false;
    }
    const uint32_t idx = patch.slot - 1;
    const uint32_t current_id = row->item_id_array[idx];
    if (IsSpellRuneItem(current_id) && !IsSpellRuneItem(patch.target_raw)) {
        return false;
    }
    row->item_id_array[idx] = patch.target_raw;
    row->item_type_array[idx] = CsvCatToMapItemType(patch.target_cat);
    return true;
}

bool PatchAllSourceLots(uint64_t solo_repo_ptr) {
    if (!solo_repo_ptr || RuntimeMap::LotPatchCount() == 0) {
        return false;
    }
    size_t applied = 0;
    for (size_t i = 0; i < RuntimeMap::LotPatchCount(); ++i) {
        const RuntimeMap::LotPatch* patch = RuntimeMap::LotPatchAt(i);
        if (patch && ApplyLotPatch(solo_repo_ptr, *patch)) {
            ++applied;
        }
    }
    if (applied > 0) {
        LogLine("lot patch applied %zu / %zu lots", applied, RuntimeMap::LotPatchCount());
    }
    return applied > 0;
}

bool PatchVanguardLots(uint64_t) {
    return false;
}

void ApplyLotPatchPickupFallback(uint64_t solo_repo_ptr, ItemGiveStruct* item_info) {
    if (!solo_repo_ptr || !item_info || item_info->item_struct_count == 0) {
        return;
    }
    const uint32_t max_items =
        static_cast<uint32_t>(sizeof(item_info->item_info) / sizeof(ItemInfo));
    const uint32_t count =
        item_info->item_struct_count > max_items ? max_items : item_info->item_struct_count;

    for (uint32_t i = 0; i < count; ++i) {
        ItemInfo* slot = &item_info->item_info[i];
        const uint32_t raw_id = RawItemId(slot->item_id);
        if (raw_id == 0) {
            continue;
        }

        const RuntimeMap::LotPatch* match = nullptr;
        size_t match_count = 0;
        for (size_t p = 0; p < RuntimeMap::LotPatchCount(); ++p) {
            const RuntimeMap::LotPatch* patch = RuntimeMap::LotPatchAt(p);
            if (!patch || patch->slot < 1 || patch->slot > 8) {
                continue;
            }
            if (!LotPatchMatchesPickup(solo_repo_ptr, *patch, raw_id)) {
                continue;
            }
            match = patch;
            ++match_count;
        }

        if (match_count != 1 || !match) {
            continue;
        }

        const uint32_t new_id = RuntimeMap::EncodeTargetPickupId(match->target_raw, match->target_cat);
        LogLine("lot pickup fallback slot %u: lot %u slot %u raw %u -> raw %u",
                i,
                match->lot_id,
                match->slot,
                raw_id,
                match->target_raw);
        slot->item_id = new_id;
        if (RuntimeMap::IsUniqueTarget(match->target_raw, match->target_cat)) {
            slot->item_quantity = 1;
            slot->item_relayvalue = 0;
        }
        ApplyLotPatch(solo_repo_ptr, *match);
        g_give_item_remapped = true;
    }
}

void TryUniqueLotPickupFix(uint64_t solo_repo_ptr, ItemGiveStruct* item_info) {
    if (!solo_repo_ptr || !item_info || item_info->item_struct_count == 0) {
        return;
    }
    const uint32_t max_items =
        static_cast<uint32_t>(sizeof(item_info->item_info) / sizeof(ItemInfo));
    const uint32_t count =
        item_info->item_struct_count > max_items ? max_items : item_info->item_struct_count;

    for (uint32_t i = 0; i < count; ++i) {
        ItemInfo* slot = &item_info->item_info[i];
        const uint32_t raw_id = RawItemId(slot->item_id);
        if (raw_id == 0) {
            continue;
        }

        const RuntimeMap::LotPatch* match = nullptr;
        size_t match_count = 0;
        for (size_t p = 0; p < RuntimeMap::LotPatchCount(); ++p) {
            const RuntimeMap::LotPatch* patch = RuntimeMap::LotPatchAt(p);
            if (!patch || patch->slot < 1 || patch->slot > 8) {
                continue;
            }
            if (!LotPatchMatchesPickup(solo_repo_ptr, *patch, raw_id)) {
                continue;
            }
            match = patch;
            ++match_count;
        }

        if (match_count != 1 || !match) {
            if (match_count > 1) {
                LogLine("lot pickup ambiguous raw %u (%zu candidates)", raw_id, match_count);
            }
            continue;
        }

        ApplyLotPatch(solo_repo_ptr, *match);
        const uint32_t new_id = RuntimeMap::EncodeTargetPickupId(match->target_raw, match->target_cat);
        LogLine("lot pickup fix slot %u: lot %u slot %u raw %u -> raw %u",
                i,
                match->lot_id,
                match->slot,
                raw_id,
                match->target_raw);
        slot->item_id = new_id;
        if (RuntimeMap::IsUniqueTarget(match->target_raw, match->target_cat)) {
            slot->item_quantity = 1;
            slot->item_relayvalue = 0;
        }
        g_give_item_remapped = true;
    }
}

void LotPatchLoop(uint64_t solo_repo_ptr) {
    if (!solo_repo_ptr || RuntimeMap::LotPatchCount() == 0) {
        return;
    }
    int pass = 0;
    size_t last_applied = static_cast<size_t>(-1);
    bool logged_complete = false;
    while (true) {
        size_t applied = 0;
        for (size_t i = 0; i < RuntimeMap::LotPatchCount(); ++i) {
            const RuntimeMap::LotPatch* patch = RuntimeMap::LotPatchAt(i);
            if (!patch) {
                continue;
            }
            if (IsLotPatchApplied(solo_repo_ptr, *patch) || ApplyLotPatch(solo_repo_ptr, *patch)) {
                ++applied;
            }
        }
        if (applied != last_applied) {
            LogLine("lot patch pass %d: %zu / %zu", ++pass, applied, RuntimeMap::LotPatchCount());
            last_applied = applied;
            logged_complete = false;
        } else if (!logged_complete && applied == RuntimeMap::LotPatchCount()) {
            LogLine("lot patch: full coverage (%zu lots)", applied);
            logged_complete = true;
        }
        const bool complete = applied == RuntimeMap::LotPatchCount();
        const auto delay = complete ? std::chrono::seconds(10)
                                    : (pass < 120 ? std::chrono::milliseconds(100)
                                                  : std::chrono::milliseconds(500));
        std::this_thread::sleep_for(delay);
    }
}

void InventoryWatchLoop() {
    // Disabled in v6 — give_item hook handles all pickup paths.
}

bool InstallHooks(SigScan& scanner) {
    Signature give_fn{
        "\x8B\x02\x83\xF8\x0A",
        "xxxxx",
        5,
        0,
    };
    auto* give_addr = scanner.FindSignature(give_fn);
    if (!give_addr) {
        LogLine("signature miss: give item function");
        return false;
    }
    give_addr = static_cast<char*>(give_addr) - 82;
    g_sites.give_item = reinterpret_cast<uint64_t>(give_addr);
    g_vanilla_give_item = reinterpret_cast<give_item_function*>(give_addr);
    LogLine("give_item @ 0x%llX (vanilla, not hooked)", static_cast<unsigned long long>(g_sites.give_item));

    if (!ResolveLukeGiveCallSites(scanner)) {
        LogLine("abort: map/lua give callsite signatures missing");
        return false;
    }
    LogKnownCallSites();

    if (!g_sites.map_give_callsite) {
        LogLine("abort: MapItemManagerImp give callsite missing");
        return false;
    }

    g_map_hook_target = reinterpret_cast<void*>(g_sites.map_give_callsite);

    if (MH_Initialize() != MH_OK) {
        LogLine("MinHook init failed");
        return false;
    }

    if (MH_CreateHook(g_map_hook_target, reinterpret_cast<void*>(&MapPickupDetour), nullptr) != MH_OK) {
        LogLine("MinHook create failed: map give callsite");
        return false;
    }
    if (MH_EnableHook(g_map_hook_target) != MH_OK) {
        LogLine("MinHook enable failed: map give callsite");
        return false;
    }

    DWORD old_protect = 0;
    if (VirtualProtect(g_map_hook_target, 8, PAGE_EXECUTE_READWRITE, &old_protect)) {
        const uint8_t call_op = 0xE8;
        memcpy(g_map_hook_target, &call_op, sizeof(call_op));
        VirtualProtect(g_map_hook_target, 8, old_protect, &old_protect);
    }

    LogLine("hook enabled: map give callsite ONLY (gather/lua path untouched)");
    return true;
}

void WorkerMain() {
    LogInit();
    LogLine("cnv_pickup_hook v8.9.46 (F7/F6 npc english name)");

    const bool map_ok = RuntimeMap::Load("mod\\dll\\cnv_runtime_map.txt");
    const bool enemy_map_ok = EnemySpawnMap::Load("mod\\dll\\cnv_enemy_spawn_map.txt");
    if (!map_ok) {
        LogLine("WARN: no runtime map — generate via tools/cnv_randomizer GUI then Deploy");
    } else {
        LogLine("runtime map seed=%u lots=%zu", RuntimeMap::Seed(), RuntimeMap::LotPatchCount());
    }
    if (!enemy_map_ok) {
        LogLine("WARN: no enemy spawn map - radahn tagging may be limited");
    } else {
        LogLine("enemy spawn map seed=%u entries=%zu",
                EnemySpawnMap::Seed(),
                EnemySpawnMap::EntryCount());
    }

    std::this_thread::sleep_for(std::chrono::seconds(1));

    SigScan scanner;
    if (!scanner.GetImageInfo()) {
        LogLine("failed to get eldenring.exe image");
        return;
    }
    g_sites.exe_base = reinterpret_cast<uint64_t>(scanner.GetBaseAddress());
    LogLine("eldenring.exe image base=0x%llX size=0x%llX",
            static_cast<unsigned long long>(g_sites.exe_base),
            static_cast<unsigned long long>(scanner.GetImageSize()));

    uint64_t solo_repo_ptr = 0;
    if (!ResolveSoloParamRepository(scanner, solo_repo_ptr)) {
        LogLine("abort: no solo param repository");
        return;
    }
    g_solo_repo_ptr = solo_repo_ptr;

    ResolveGameDataManPtr(scanner, g_game_data_man_ptr_loc);
    ResolveInventoryIdFunction(scanner);

    ResolveMapItemMan(scanner, g_map_item_man);
    std::thread(ResolveMapItemManLoop).detach();
    std::thread(LotPatchLoop, solo_repo_ptr).detach();

    const bool hooked = InstallHooks(scanner);
    bool radahn_hook = false;
    if (hooked) {
        radahn_hook = InstallRadahnMeteorHook(scanner);
    }

    if (!map_ok || !hooked) {
        LogLine("FAILED: map=%d hook=%d radahn_meteor=%d",
                map_ok ? 1 : 0,
                hooked ? 1 : 0,
                radahn_hook ? 1 : 0);
    } else {
        LogLine("ready: seed=%u lots=%zu radahn_meteor=%d",
                RuntimeMap::Seed(),
                RuntimeMap::LotPatchCount(),
                radahn_hook ? 1 : 0);
    }

    StartEnemyDebugHud(scanner);
}

}  // namespace

void StartPickupHookWorker() {
    std::thread(WorkerMain).detach();
}

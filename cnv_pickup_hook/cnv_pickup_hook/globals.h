#pragma once

#include <cstdint>

#include <windows.h>

// Runtime MapItemType in eldenring.exe (LukeYui)
enum MapItemType : uint32_t {
    kMapItemGoods = 1,
    kMapItemWeapon = 2,
    kMapItemArmour = 3,
    kMapItemAccessory = 4,
    kMapItemGem = 5,
};

constexpr uint32_t kItemIdMask = 0x0FFFFFFF;
constexpr uint32_t kGoodsTypePrefix = 0x40000000;

// eldenring.exe: ItemPopup is a few KB after give_item (CNV 3.0 rva delta 0x3B40).
constexpr ptrdiff_t kItemPopupOffsetFromGive = 0x3B40;

struct ItemInfo {
    uint32_t item_id;
    uint32_t item_quantity;
    uint32_t item_relayvalue;
    uint32_t item_ashes_of_war;
};

struct ItemGiveStruct {
    uint32_t item_struct_count;
    ItemInfo item_info[10];
};

struct ItemLotRow {
    uint32_t item_id_array[8];
    MapItemType item_type_array[8];
};

typedef void give_item_function(uint64_t, ItemGiveStruct*, void*);
typedef void item_popup_function(void*, void*);
typedef int (*get_inventoryid_function)(uint64_t, uint32_t*);

#include "pickup_item_rules.h"

namespace cnv_pickup_item_rules {

bool IsSpiritAshGoods(uint32_t raw_id) {
    if (raw_id >= 2200000 && raw_id <= 2399999) {
        return true;
    }
    if (raw_id >= 2320000 && raw_id <= 2329999) {
        return true;
    }
    return false;
}

uint32_t SpiritAshBaseId(uint32_t raw_id) {
    if (!IsSpiritAshGoods(raw_id)) {
        return raw_id;
    }
    return (raw_id / 10u) * 10u;
}

bool IsSpellRuneCrushLot(uint32_t lot_id) {
    // Keep in sync with goods_subcats.SPELL_CRUSH_LOT_IDS (not the full 942370xxx band).
    return lot_id == 942370020u;
}

bool IsSpellRuneItem(uint32_t raw_id) {
    if (raw_id >= 17000 && raw_id <= 17999) {
        return true;
    }
    if (raw_id >= 2002900 && raw_id <= 2002960) {
        return true;
    }
    return false;
}

bool IsGatheringMaterial(uint32_t raw_id) {
    // Keep in sync with goods_subcats.is_gathering_material_id / MATERIAL_ORPHAN_RANGES.
    if (raw_id >= 15000 && raw_id <= 15999) {
        return true;
    }
    if (raw_id >= 20000 && raw_id <= 20999) {
        return true;
    }
    return false;
}

}  // namespace cnv_pickup_item_rules

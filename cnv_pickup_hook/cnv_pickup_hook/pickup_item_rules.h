#pragma once

#include <cstdint>

namespace cnv_pickup_item_rules {

bool IsSpiritAshGoods(uint32_t raw_id);
uint32_t SpiritAshBaseId(uint32_t raw_id);
bool IsSpellRuneCrushLot(uint32_t lot_id);
bool IsSpellRuneItem(uint32_t raw_id);
bool IsGatheringMaterial(uint32_t raw_id);

}  // namespace cnv_pickup_item_rules

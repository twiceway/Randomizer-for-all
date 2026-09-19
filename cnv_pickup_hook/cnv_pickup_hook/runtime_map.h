#pragma once



#include <cstdint>



namespace RuntimeMap {



struct LotPatch {

    uint32_t lot_id = 0;

    uint32_t slot = 0;  // 1-8, matches spoiler / CSV

    uint32_t target_raw = 0;

    uint32_t target_cat = 0;

    uint32_t runtime_source = 0;  // CNV give_item id when it differs from CSV

};



bool Load(const char* path);

bool IsLoaded();

uint32_t Seed();

size_t PairCount();

size_t LotPatchCount();



bool HasSource(uint32_t raw_id);

uint32_t TargetForRaw(uint32_t raw_id);

uint32_t TargetCategoryForRaw(uint32_t raw_id);

uint32_t RemapEncoded(uint32_t encoded_id);
uint32_t EncodeTargetPickupId(uint32_t raw_id, uint32_t cat);

bool IsUniqueTarget(uint32_t raw_id, uint32_t cat);
bool IsKnownTarget(uint32_t raw_id);
uint32_t CategoryForKnownTarget(uint32_t raw_id);



const LotPatch* LotPatches();

const LotPatch* LotPatchAt(size_t index);



}  // namespace RuntimeMap


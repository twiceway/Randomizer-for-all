"""Apply dlc_trash_taxonomy.json → enemy_archetypes + model_prefix_display_zh."""
from __future__ import annotations

import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent
TAXONOMY = SCRIPT / "dlc_trash_taxonomy.json"
ARCHETYPES = SCRIPT / "enemy_archetypes.json"
CATEGORIES = SCRIPT / "enemy_categories.json"

# 新 DLC 分类模型不再塞进旧 soldier/wolf/critter/dlc_m61
STRIP_FROM_ARCH_IDS = frozenset(
    {"soldier", "wolf", "critter", "crustacean", "dlc_m61"}
)


def taxonomy_models(data: dict) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for arch in data.get("archetypes") or []:
        aid = str(arch.get("id") or "")
        models: set[str] = set()
        for entry in arch.get("entries") or []:
            for m in entry.get("models") or []:
                models.add(str(m).lower())
        if aid and models:
            out[aid] = models
    return out


def taxonomy_zh(data: dict) -> dict[str, str]:
    zh: dict[str, str] = {}
    for arch in data.get("archetypes") or []:
        for entry in arch.get("entries") or []:
            label = str(entry.get("zh") or "").strip()
            if not label:
                continue
            for m in entry.get("models") or []:
                zh.setdefault(str(m).lower(), label)
    return zh


def merge_prefix_list(base: list[str], add: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in list(base) + list(add):
        pl = str(raw).lower()
        if not pl or pl in seen:
            continue
        seen.add(pl)
        out.append(pl)
    return sorted(out)


def main() -> None:
    tax = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    by_arch = taxonomy_models(tax)
    all_tax = set().union(*by_arch.values())
    zh_map = taxonomy_zh(tax)

    arch = json.loads(ARCHETYPES.read_text(encoding="utf-8-sig"))
    arch_list = list(arch.get("trash_archetypes") or [])
    by_id = {str(a.get("id")): a for a in arch_list}

    for aid, models in sorted(by_arch.items()):
        label = ""
        for raw in tax.get("archetypes") or []:
            if str(raw.get("id")) == aid:
                label = str(raw.get("label_zh") or aid)
                break
        if aid in by_id:
            by_id[aid]["label_zh"] = label
            by_id[aid]["models"] = sorted(models)
        else:
            arch_list.append({"id": aid, "label_zh": label, "models": sorted(models)})
            by_id[aid] = arch_list[-1]

    for strip_id in STRIP_FROM_ARCH_IDS:
        if strip_id not in by_id:
            continue
        old = [str(m).lower() for m in (by_id[strip_id].get("models") or [])]
        by_id[strip_id]["models"] = sorted(m for m in old if m not in all_tax)

    arch["trash_archetypes"] = arch_list
    arch["version"] = int(arch.get("version") or 0) + 1
    ARCHETYPES.write_text(json.dumps(arch, ensure_ascii=False, indent=2), encoding="utf-8")

    cats = json.loads(CATEGORIES.read_text(encoding="utf-8-sig"))
    display = dict(cats.get("model_prefix_display_zh") or {})
    display.update(zh_map)
    cats["model_prefix_display_zh"] = display

    force = sorted(all_tax)
    cats["dlc_trash_donor_model_prefixes"] = merge_prefix_list(
        cats.get("dlc_trash_donor_model_prefixes") or [],
        force,
    )
    cats["dlc_trash_taxonomy_force_prefixes"] = force
    cats["dlc_trash_taxonomy_definition"] = (
        "用户口径 DLC 小怪分类（dlc_trash_taxonomy.json）；强制进 1 池捐皮前缀"
    )
    # ensure dlc origin for taxonomy models
    rules = list(cats.get("donor_origin_by_model_prefix") or [])
    for m in sorted(all_tax):
        rules = [r for r in rules if str(r.get("prefix", "")).lower() != m]
        rules.append({"prefix": m, "origin": "dlc"})
    rules.sort(key=lambda r: str(r.get("prefix", "")))
    cats["donor_origin_by_model_prefix"] = rules

    CATEGORIES.write_text(json.dumps(cats, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"taxonomy models={len(all_tax)} archetypes={len(by_arch)}")
    print(f"wrote {ARCHETYPES.name} v{arch['version']}")
    print(f"wrote {CATEGORIES.name}")


if __name__ == "__main__":
    main()

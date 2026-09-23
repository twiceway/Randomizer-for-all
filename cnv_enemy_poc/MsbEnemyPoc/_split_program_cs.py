"""Pure-move split Program.cs into partial class files."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "Program.cs"

USINGS = """using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;
using SoulsFormats;
using SoulsFormats.Cryptography;

"""

CLI = {
    "Main",
    "ResolveGameDir",
    "ResolveMsbOverride",
    "ResolveToolRoot",
    "ResolveRingrandomRoot",
    "ResolveModMapStudioDir",
    "ResolveCsvDir",
    "ResolveSeed",
    "ResolveIndexOutPath",
    "ResolvePickupIndexOutPath",
    "ResolveMaxMaps",
    "ResolveSpawnMapPath",
    "ResolveMapFilter",
    "ResolveParallelDegree",
    "ResolveMaxParallelDegree",
    "ResolveMapInflightLimit",
    "ResolveDynamicParallel",
    "ResolveQuietApply",
    "ResolveProfileApply",
    "ResolveNoMsbSourceCache",
    "FindCachedMsb",
}

PATCH = {
    "ResolvePatchSource",
    "RunBossBatch",
    "ScanDonors",
    "ResolveDonor",
    "FindDonorInProbeMaps",
    "CollectDonors",
    "TryReadMapEnemies",
    "TryReadMapBytes",
    "TryReadBytesFromBhd",
    "BuildDonorPart",
    "GetDonorEnemyIndex",
    "FindEnemyPartEntryByName",
    "ApplyMountSuppress",
    "IsRealDragonModel",
}

APPLY = {
    "ApplySpawnMap",
    "ParseSpawnMap",
    "ProcessMapGroupWork",
    "ApplyMapGroupsDynamic",
    "ApplySpawnMapGroup",
    "MaybeLogMapHeartbeat",
    "LoadCnvMapModelIndex",
    "TryLoadMapModelIndexCache",
    "TrySaveCnvMapModelIndexCache",
    "BuildMapModelNameSet",
    "GetMapModelNameSetForApply",
    "MarkCnvMapModelIndexDirty",
    "RecordMapModelNamesFromMsb",
    "RecordMapModelNames",
    "BuildEnemyModelRegistry",
    "ModelRegistryCachePath",
    "ComputeMapStudioFingerprint",
    "MsbSourceCacheRoot",
    "MsbSourceCacheFingerprint",
    "MsbSourceCacheFilePath",
    "TryWriteMsbSourceCache",
    "EnsureBhdFileIndex",
    "TryWriteMsbSourceCacheFromMod",
    "WarmSourceMapDiskCache",
    "TryWriteOutputMsbeCopy",
    "TryLoadModelRegistryCache",
    "TrySaveModelRegistryCache",
    "EnsureModelsReferencedByEnemyParts",
    "BuildEnemyLookupByName",
    "ResolveRadahnHelperTemplate",
    "BuildRadahnLandingHelper",
    "TryInjectRadahnLandingHelper",
    "LoadEnemySlotEntityIndex",
    "ResolveBossEntityIdFromIndex",
    "WriteRadahnLandingManifest",
    "EnsureEnemyModel",
    "SupplementModelRegistryFromSpawnEntries",
    "CollectWarmMapFiles",
    "TryReadMsbFromPath",
    "TryReadMsbSafe",
    "WriteMsbeToPath",
    "MsbeWriteCompression",
    "FindEnemyModelEntry",
    "MapModelIndexCachePath",
}

PATCH_TYPES = {"DonorEntry"}
APPLY_TYPES = {
    "MapApplyProgress",
    "ApplyProfileStats",
    "MapModelIndexCacheFile",
    "RegistryCacheEntry",
    "RegistryCacheFile",
    "MapApplyResult",
    "RadahnLandingRecord",
    "SpawnMapEntry",
}

PATCH_FIELDS = {
    "Batch1Plan",
    "Batch2Plan",
    "GodrickProbeMaps",
    "EldenBeastProbeMaps",
    "DragonProbeMaps",
    "RuneMediumProbeMaps",
    "DragonModelPrefixes",
    "RealFlyingDragonPrefixes",
    "RealFieldDragonPrefixes",
}

APPLY_FIELDS = {
    "MsbSourceCacheEnabled",
    "MsbSourceCacheHits",
    "MsbSourceCacheMisses",
    "ApplyProfileEnabled",
    "ApplyProfile",
    "CnvMapModelIndex",
    "CnvMapModelIndexDirty",
    "CnvMapModelIndexFingerprint",
    "ModelEnsureStubCount",
    "ModelEnsureUpgradeCount",
    "ModelRegistryScopedToSpawn",
    "ModelRegistryMissCache",
    "MapApplyInflight",
    "DonorEnemyByMapCache",
    "BhdFileIndex",
    "RadahnHelperTemplate",
    "RadahnEntityIndex",
    "LastMapHeartbeatMs",
}


def member_name(line: str) -> str | None:
    for pat in (
        r"^    static (?:readonly )?(?:[\w<>\[\]?,\s]+\s+)?(\w+)\s*[\(<]",
        r"^    static (?:readonly )?(?:[\w<>\[\]?,\s]+\s+)?(\w+)\s*=",
        r"^    sealed (?:record|class) (\w+)",
        r"^    const \w+ (\w+)",
    ):
        m = re.match(pat, line)
        if m:
            return m.group(1)
    return None


def is_member_start(line: str) -> bool:
    return member_name(line) is not None


def extract_block(lines: list[str], start: int) -> tuple[list[str], int]:
    block = [lines[start]]
    if block[0].rstrip().endswith(";") and "=>" in block[0]:
        return block, start + 1
    # multi-line expression body
    if "=>" in block[0] and not block[0].rstrip().endswith(";"):
        i = start + 1
        while i < len(lines):
            block.append(lines[i])
            if lines[i].rstrip().endswith(";"):
                return block, i + 1
            i += 1
        return block, i
    depth = 0
    started = False
    i = start + 1
    while i < len(lines):
        block.append(lines[i])
        for ch in lines[i]:
            if ch == "{":
                depth += 1
                started = True
            elif ch == "}":
                depth -= 1
        i += 1
        if started and depth <= 0:
            break
    return block, i


def classify(name: str | None) -> str:
    if not name:
        return "core"
    if name in CLI:
        return "cli"
    if name in PATCH or name in PATCH_TYPES or name in PATCH_FIELDS:
        return "patch"
    if name in APPLY or name in APPLY_TYPES or name in APPLY_FIELDS:
        return "apply"
    if name == "MsbMapModelIndexSource":
        return "apply"
    return "core"


def write_partial(path: Path, body: str, note: str) -> None:
    header = USINGS
    if note == "patch":
        header += "// @deprecated POC — not production apply-map path (T-073 R4.1)\n\n"
    else:
        header += f"// {note}\n\n"
    path.write_text(header + "static partial class Program\n{\n" + body + "\n}\n", encoding="utf-8")


def main() -> None:
    lines = SRC.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next(i for i, ln in enumerate(lines) if ln.startswith("static partial class Program")) + 1
    end = next(i for i in range(len(lines) - 1, -1, -1) if lines[i].strip() == "}")
    inner = lines[start:end]

    buckets: dict[str, list[str]] = {k: [] for k in ("core", "cli", "apply", "patch")}
    i = 0
    while i < len(inner):
        ln = inner[i]
        if not is_member_start(ln):
            i += 1
            continue
        name = member_name(ln)
        block, i = extract_block(inner, i)
        buckets[classify(name)].extend(block)
        buckets[classify(name)].append("\n")

    write_partial(ROOT / "Program.Cli.cs", "".join(buckets["cli"]), "CLI routing + argument resolution (T-073 R3)")
    write_partial(ROOT / "Program.ApplyMap.cs", "".join(buckets["apply"]), "apply-map pipeline (T-073 R3)")
    write_partial(ROOT / "Program.Patch.cs", "".join(buckets["patch"]), "patch")
    write_partial(ROOT / "Program.cs", "".join(buckets["core"]), "Shared MSB I/O, index export, list/inspect")

    for p in ["Program.cs", "Program.Cli.cs", "Program.ApplyMap.cs", "Program.Patch.cs"]:
        print(f"{p}: {sum(1 for _ in open(ROOT / p, encoding='utf-8'))} lines")


if __name__ == "__main__":
    main()

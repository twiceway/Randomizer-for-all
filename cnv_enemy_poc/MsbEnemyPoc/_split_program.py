#!/usr/bin/env python3
"""Pure-move split of Program.cs into partial files."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "Program.cs"

COMMON_USINGS = """\
using System.Reflection;
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

PATCH_HEADER = """\
// @deprecated POC — not production apply-map path (T-073 R4.1)

"""

CLI_MEMBERS = {
    "Main",
    "ResolveGameDir",
    "ResolveMsbOverride",
    "ResolveSpawnMapPath",
    "ResolveMapFilter",
    "ResolveParallelDegree",
    "ResolveMaxParallelDegree",
    "ResolveMapInflightLimit",
    "ResolveDynamicParallel",
    "ResolveQuietApply",
    "ResolveProfileApply",
    "ResolveNoMsbSourceCache",
    "ResolveIndexOutPath",
    "ResolvePickupIndexOutPath",
    "ResolveMaxMaps",
    "ResolveSeed",
    "ResolveToolRoot",
    "ResolveRingrandomRoot",
    "ResolveModMapStudioDir",
    "ResolveCsvDir",
    "FindCachedMsb",
    "ResolveIndexIncludeZeroNpc",
}

PATCH_MEMBERS = {
    "RunBossBatch",
    "Batch1Plan",
    "Batch2Plan",
    "GodrickProbeMaps",
    "EldenBeastProbeMaps",
    "DragonProbeMaps",
    "RuneMediumProbeMaps",
    "DragonModelPrefixes",
    "RealFlyingDragonPrefixes",
    "RealFieldDragonPrefixes",
    "ResolveDonor",
    "FindDonorInProbeMaps",
    "CollectDonors",
    "ScanDonors",
    "BuildDonorPart",
    "ApplyMountSuppress",
    "DonorEntry",
    "IsRealDragonModel",
    "TryReadMapEnemies",
    "TryReadMapBytes",
    "TryReadBytesFromBhd",
    "GetDonorEnemyIndex",
    "FindEnemyPartEntryByName",
    "DonorEnemyByMapCache",
    "RunPatchMode",
}

APPLY_MEMBERS = {
    "ApplySpawnMap",
    "ParseSpawnMap",
    "ProcessMapGroupWork",
    "ApplyMapGroupsDynamic",
    "ApplySpawnMapGroup",
    "MaybeLogMapHeartbeat",
    "BuildEnemyModelRegistry",
    "EnsureEnemyModel",
    "WarmSourceMapDiskCache",
    "LoadCnvMapModelIndex",
    "TryLoadMapModelIndexCache",
    "TrySaveCnvMapModelIndexCache",
    "BuildMapModelNameSet",
    "GetMapModelNameSetForApply",
    "MarkCnvMapModelIndexDirty",
    "RecordMapModelNamesFromMsb",
    "RecordMapModelNames",
    "ModelRegistryCachePath",
    "ComputeMapStudioFingerprint",
    "MsbSourceCacheRoot",
    "MsbSourceCacheFingerprint",
    "MsbSourceCacheFilePath",
    "TryWriteMsbSourceCache",
    "TryWriteMsbSourceCacheFromMod",
    "TryLoadModelRegistryCache",
    "TrySaveModelRegistryCache",
    "EnsureModelsReferencedByEnemyParts",
    "BuildEnemyLookupByName",
    "MapApplyResult",
    "RadahnLandingRecord",
    "RadahnHelperTemplate",
    "RadahnHelperDonorMap",
    "RadahnHelperDonorEntityId",
    "IsRadahnDonorModel",
    "ResolveRadahnHelperTemplate",
    "PickRadahnHelperEntityId",
    "BuildRadahnLandingHelper",
    "TryInjectRadahnLandingHelper",
    "RadahnEntityIndex",
    "ResolveBossEntityIdFromIndex",
    "LoadEnemySlotEntityIndex",
    "WriteRadahnLandingManifest",
    "SpawnMapEntry",
    "ApplyProfileStats",
    "MapApplyProgress",
    "MsbMapModelIndexSource",
    "MapModelIndexCachePath",
    "MapModelIndexCacheFile",
    "RegistryCacheEntry",
    "RegistryCacheFile",
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
    "MsbSourceCacheFileLocks",
    "BhdFileIndex",
    "BhdFileIndexLock",
    "LastMapHeartbeatMs",
    "ResolveDonorMapId",
    "SyntheticTemplateSource",
    "SyntheticSourceOverrides",
    "SyntheticTemplateSources",
    "LoadSyntheticTemplateSources",
    "ScoreSyntheticIndexSource",
    "IsEnemyModelStub",
    "GetEnemyModelInstanceCount",
    "FindEnemyModelOnMsb",
    "TryReplaceEnemyModelOnMsb",
    "AddEnemyModelToMsb",
    "EnemyModelSibPath",
    "CreateEnemyModelStub",
    "SupplementModelRegistryFromSpawnEntries",
    "CollectWarmMapFiles",
    "TryReadMsbFromPath",
    "MsbeWriteCompression",
    "WriteMsbeToPath",
    "TryReadMsbSafe",
    "FindEnemyModelEntry",
    "IsValidDonorMapId",
    "EnsureBhdFileIndex",
    "TryWriteOutputMsbeCopy",
    "SiegeWeaponModelPrefixes",
    "IsSiegeWeaponPartName",
    "IndexSiegeMountRiders",
    "CollectWalkRouteNames",
    "SanitizeDanglingWalkRoutes",
    "CollectCollisionPartNames",
    "SanitizeDanglingCollisionParts",
    "TryDeleteFileIfExists",
    "WriteOverlayMsbPair",
}


def skip_ws(text: str, pos: int) -> int:
    n = len(text)
    while pos < n and text[pos] in " \t\r\n":
        pos += 1
    return pos


def member_name(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^\[[^\]]*\]\s*", "", text)
    text = re.sub(
        r"^(?:(?:public|private|protected|internal|static|readonly|sealed|const|volatile|async|extern|unsafe|new|partial)\s+)+",
        "",
        text,
    )
    for kw in ("sealed record", "sealed class", "record struct", "record", "class", "struct", "enum"):
        if text.startswith(kw):
            rest = text[len(kw) :].lstrip()
            m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)", rest)
            return m.group(1) if m else "_unknown"
    m = re.match(r"(?:[\w<>,\[\]?.\s]+?)\s+([A-Za-z_][A-Za-z0-9_]*)\s*[\(=;{]", text, re.DOTALL)
    if m:
        return m.group(1)
    m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*=", text)
    if m:
        return m.group(1)
    return "_unknown"


def extract_class_members(class_body: str) -> list[str]:
    members: list[str] = []
    n = len(class_body)
    i = 0
    depth = 0
    member_start: int | None = None

    while i < n:
        ch = class_body[i]
        if ch == "{":
            if depth == 0 and member_start is None:
                k = i - 1
                while k >= 0 and class_body[k] in " \t\r\n":
                    k -= 1
                while k >= 0 and class_body[k] != "\n":
                    k -= 1
                member_start = k + 1
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and member_start is not None:
                end = i
                j = skip_ws(class_body, i + 1)
                if j < n and class_body[j] == ";":
                    end = j
                    i = j
                members.append(class_body[member_start : end + 1].strip())
                member_start = None
        elif ch == ";" and depth == 0:
            if member_start is not None:
                members.append(class_body[member_start : i + 1].strip())
                member_start = None
            else:
                # expression-bodied / field at depth 0
                k = i - 1
                while k >= 0 and class_body[k] in " \t\r\n":
                    k -= 1
                while k >= 0 and class_body[k] != "\n" and class_body[k] != ";":
                    k -= 1
                line_start = k + 1
                chunk = class_body[line_start : i + 1].strip()
                if chunk and not chunk.startswith("//"):
                    members.append(chunk)
        elif depth == 0 and ch not in " \t\r\n" and member_start is None:
            k = i
            while k > 0 and class_body[k - 1] not in "\n":
                k -= 1
            member_start = k
        i += 1

    return [m for m in members if m]


def assign_target(name: str) -> str:
    if name in CLI_MEMBERS:
        return "cli"
    if name in PATCH_MEMBERS:
        return "patch"
    if name in APPLY_MEMBERS:
        return "apply"
    return "core"


def wrap_file(preamble: str, body: str, extra_header: str = "") -> str:
    return preamble.rstrip() + "\n\nstatic partial class Program\n{\n" + extra_header + body + "\n}\n"


def main() -> None:
    source = SRC.read_text(encoding="utf-8")
    m = re.search(r"static partial class Program\s*\{", source)
    if not m:
        raise SystemExit("class Program not found")
    preamble = source[: m.start()]
    body_start = m.end()

  # find matching closing brace for class
    depth = 1
    i = body_start
    while i < len(source) and depth > 0:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
        i += 1
    class_body = source[body_start : i - 1]

    raw_members = extract_class_members(class_body)
    print(f"Extracted {len(raw_members)} members")

    buckets: dict[str, list[str]] = {"core": [], "cli": [], "apply": [], "patch": []}
    for text in raw_members:
        name = member_name(text)
        target = assign_target(name)
        buckets[target].append(text)
        print(f"  {name:40s} -> {target}")

    for key, filename, header in [
        ("core", "Program.cs", ""),
        ("cli", "Program.Cli.cs", ""),
        ("apply", "Program.ApplyMap.cs", ""),
        ("patch", "Program.Patch.cs", PATCH_HEADER),
    ]:
        body = "\n\n".join(buckets[key])
        content = wrap_file(COMMON_USINGS if key != "core" else preamble, body, header)
        out = ROOT / filename
        out.write_text(content, encoding="utf-8")
        lines = content.count("\n") + (0 if content.endswith("\n") else 1)
        print(f"Wrote {filename}: {lines} lines ({len(buckets[key])} members)")


if __name__ == "__main__":
    main()

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

// @deprecated POC — not production apply-map path (T-073 R4.1)

static partial class Program
{
    static string? ResolvePatchSource(string gameDir, StringBuilder detailLog)
    {
        var modMsb = ModMsbPath(gameDir);
        if (!File.Exists(modMsb))
        {
            Log(detailLog, "patch_source=missing_cnv_mod_msb");
            Console.Error.WriteLine($"Missing CNV MSB: {modMsb}");
            Console.Error.WriteLine("Repair/reinstall Convergence — do NOT use Smithbox export as source.");
            return null;
        }

        var modBytes = File.ReadAllBytes(modMsb);
        var modMsbData = ReadMsbe(modBytes);
        var sentinels = CountModel(modMsbData, TargetModel);
        var soldiers = CountModel(modMsbData, SourceModel);

        if (soldiers == 0 && sentinels > 0)
        {
            Log(detailLog, $"patch_source=blocked cnv_msb_already_patched sentinels={sentinels}");
            Console.Error.WriteLine("CNV mod/map/MapStudio/m60_42_37_00.msb.dcx already has Tree Sentinels (was overwritten earlier).");
            Console.Error.WriteLine("Repair Convergence once, then patch again (output goes to mod/cnv_enemy/).");
            return null;
        }

        if (modBytes.Length < 60_000)
        {
            Console.WriteLine($"WARNING: CNV MSB only {modBytes.Length} bytes (expected ~73 KB). Repair Convergence before patch.");
            Log(detailLog, $"WARNING=small_cnv_msb bytes={modBytes.Length}");
        }

        Log(detailLog, $"patch_source=cnv_mod_msb path={modMsb} bytes={modBytes.Length} soldiers={soldiers}");
        Console.WriteLine($"Patch source (read-only): {modMsb} ({modBytes.Length} bytes, {soldiers} soldiers)");
        return modMsb;
    }

    sealed record DonorEntry(
        string Label,
        string MapFile,
        string EnemyName,
        string Model,
        int Npc,
        int Think,
        int Chara);

    static readonly (string SlotName, string DonorKey, string Note)[] Batch1Plan =
    {
        ("c4311_9018", "random_dragon", "巡逻兵 — 龙体型 / 地形"),
        ("c4311_9010", "godrick", "营地巡逻 — 葛瑞克转阶段"),
        ("c4311_9022", "elden_beast", "林边巡逻 — 艾尔登之兽（皮蛋）"),
    };

    static readonly string[] GodrickProbeMaps =
    {
        "m60_43_35_00.msb.dcx", "m60_43_34_00.msb.dcx", "m60_43_31_00.msb.dcx", "m60_43_33_00.msb.dcx",
        "m60_39_50_00.msb.dcx",
    };

    static readonly string[] EldenBeastProbeMaps =
    {
        "m60_61_44_00.msb.dcx", "m60_61_46_00.msb.dcx", "m60_62_47_00.msb.dcx", "m60_60_54_00.msb.dcx",
        "m60_61_45_00.msb.dcx",
    };

    static readonly string[] DragonProbeMaps =
    {
        "m60_45_39_00.msb.dcx", "m60_41_51_00.msb.dcx", "m60_43_33_00.msb.dcx", "m60_42_36_00.msb.dcx",
    };

    static readonly string[] RuneMediumProbeMaps =
    {
        "m60_42_36_00.msb.dcx", "m60_42_37_00.msb.dcx", "m60_41_51_00.msb.dcx",
    };

    static readonly string[] DragonModelPrefixes =
    {
        "c4800", "c4810", "c4880", "c4900", "c4920", "c4930", "c4940", "c4950", "c4960",
    };

    static readonly string[] RealFlyingDragonPrefixes = { "c4500", "c4502" };
    static readonly string[] RealFieldDragonPrefixes = { "c4810" };

    static int ScanDonors(string gameDir, StringBuilder detailLog)
    {
        var mapStudio = CnvMapStudioDir(gameDir);
        if (!Directory.Exists(mapStudio))
        {
            Console.Error.WriteLine($"Missing {mapStudio}");
            return 1;
        }

        Console.WriteLine($"Scanning donor templates under {mapStudio}");
        var dragons = new List<DonorEntry>();
        var realDragons = new List<DonorEntry>();
        var godricks = new List<DonorEntry>();
        var beasts = new List<DonorEntry>();

        foreach (var path in Directory.EnumerateFiles(mapStudio, "m60_*.msb.dcx").OrderBy(p => p))
        {
            MSBE msb;
            try
            {
                msb = ReadMsbe(File.ReadAllBytes(path));
            }
            catch (Exception ex)
            {
                Console.WriteLine($"  SKIP {Path.GetFileName(path)} ({ex.Message})");
                continue;
            }

            var mapFile = Path.GetFileName(path);
            foreach (var enemy in msb.Parts.Enemies)
            {
                var model = enemy.ModelName ?? "";
                if (string.IsNullOrWhiteSpace(model))
                {
                    continue;
                }

                if (DragonModelPrefixes.Any(p => model.StartsWith(p, StringComparison.OrdinalIgnoreCase)))
                {
                    dragons.Add(new DonorEntry("dragon", mapFile, enemy.Name, model, enemy.NPCParamID, enemy.ThinkParamID, enemy.CharaInitID));
                }

                if (RealFlyingDragonPrefixes.Any(p => model.StartsWith(p, StringComparison.OrdinalIgnoreCase))
                    || RealFieldDragonPrefixes.Any(p => model.StartsWith(p, StringComparison.OrdinalIgnoreCase)))
                {
                    realDragons.Add(new DonorEntry("real_dragon", mapFile, enemy.Name, model, enemy.NPCParamID, enemy.ThinkParamID, enemy.CharaInitID));
                }
                else if (model.StartsWith("c4750", StringComparison.OrdinalIgnoreCase))
                {
                    godricks.Add(new DonorEntry("godrick", mapFile, enemy.Name, model, enemy.NPCParamID, enemy.ThinkParamID, enemy.CharaInitID));
                }
                else if (model.StartsWith("c5200", StringComparison.OrdinalIgnoreCase))
                {
                    beasts.Add(new DonorEntry("elden_beast_c5200", mapFile, enemy.Name, model, enemy.NPCParamID, enemy.ThinkParamID, enemy.CharaInitID));
                }
                else if (model.StartsWith("c2200", StringComparison.OrdinalIgnoreCase))
                {
                    beasts.Add(new DonorEntry("elden_beast", mapFile, enemy.Name, model, enemy.NPCParamID, enemy.ThinkParamID, enemy.CharaInitID));
                }
            }
        }

        void PrintGroup(string title, List<DonorEntry> entries)
        {
            Console.WriteLine();
            Console.WriteLine($"== {title} ({entries.Count}) ==");
            foreach (var e in entries.OrderBy(e => e.MapFile).ThenBy(e => e.EnemyName).Take(40))
            {
                var line = $"  {e.MapFile}  {e.EnemyName}  model={e.Model}  npc={e.Npc}  think={e.Think}  chara={e.Chara}";
                Console.WriteLine(line);
                Log(detailLog, line.Trim());
            }
            if (entries.Count > 40)
            {
                Console.WriteLine($"  ... and {entries.Count - 40} more");
            }
        }

        PrintGroup("DRAGONS (legacy batch1 pool)", dragons);
        PrintGroup("REAL DRAGONS c4500/c4502/c4810", realDragons);
        PrintGroup("GODRICK c4750", godricks);
        PrintGroup("ELDEN BEAST c2200 / c5200", beasts);

        var cachePath = Path.Combine(ResolveToolRoot(), "boss_donors_scan.txt");
        File.WriteAllText(cachePath, detailLog.ToString(), Encoding.UTF8);
        Console.WriteLine();
        Console.WriteLine($"Wrote {cachePath}");
        WriteDetailLog(detailLog, "scan-donors");
        return 0;
    }

    static List<DonorEntry> CollectDonors(string gameDir, Func<string, bool> modelMatch, string label)
    {
        var mapStudio = CnvMapStudioDir(gameDir);
        var results = new List<DonorEntry>();
        if (!Directory.Exists(mapStudio))
        {
            return results;
        }

        foreach (var path in Directory.EnumerateFiles(mapStudio, "m60_*.msb.dcx"))
        {
            MSBE msb;
            try
            {
                msb = ReadMsbe(File.ReadAllBytes(path));
            }
            catch
            {
                continue;
            }

            var mapFile = Path.GetFileName(path);
            foreach (var enemy in msb.Parts.Enemies)
            {
                var model = enemy.ModelName ?? "";
                if (!modelMatch(model))
                {
                    continue;
                }

                results.Add(new DonorEntry(label, mapFile, enemy.Name, model, enemy.NPCParamID, enemy.ThinkParamID, enemy.CharaInitID));
            }
        }

        return results;
    }

    static bool IsRealDragonModel(string model) =>
        RealFlyingDragonPrefixes.Any(p => model.StartsWith(p, StringComparison.OrdinalIgnoreCase))
        || RealFieldDragonPrefixes.Any(p => model.StartsWith(p, StringComparison.OrdinalIgnoreCase));

    static DonorEntry? ResolveDonor(string key, string gameDir, int seed, StringBuilder detailLog)
    {
        if (key == "random_dragon")
        {
            var pool = CollectDonors(gameDir, m => DragonModelPrefixes.Any(p => m.StartsWith(p, StringComparison.OrdinalIgnoreCase)), "dragon");
            if (pool.Count == 0)
            {
                return null;
            }

            pool.Sort((a, b) => string.Compare($"{a.MapFile}:{a.EnemyName}", $"{b.MapFile}:{b.EnemyName}", StringComparison.Ordinal));
            var idx = (int)((uint)seed % (uint)pool.Count);
            var pick = pool[idx];
            Log(detailLog, $"dragon_pick seed={seed} index={idx}/{pool.Count} {pick.MapFile}:{pick.EnemyName} model={pick.Model}");
            return pick;
        }

        if (key == "real_dragon")
        {
            var pool = CollectDonors(gameDir, IsRealDragonModel, "real_dragon");
            foreach (var mapFile in DragonProbeMaps)
            {
                var enemies = TryReadMapEnemies(gameDir, mapFile, detailLog);
                if (enemies == null)
                {
                    continue;
                }

                foreach (var enemy in enemies)
                {
                    var model = enemy.ModelName ?? "";
                    if (!IsRealDragonModel(model))
                    {
                        continue;
                    }

                    var entry = new DonorEntry("real_dragon", mapFile, enemy.Name, model, enemy.NPCParamID, enemy.ThinkParamID, enemy.CharaInitID);
                    if (!pool.Any(p => p.MapFile == entry.MapFile && p.EnemyName == entry.EnemyName))
                    {
                        pool.Add(entry);
                    }
                }
            }

            if (pool.Count == 0)
            {
                return null;
            }

            pool.Sort((a, b) => string.Compare($"{a.MapFile}:{a.EnemyName}", $"{b.MapFile}:{b.EnemyName}", StringComparison.Ordinal));
            var realIdx = (int)((uint)seed % (uint)pool.Count);
            var realPick = pool[realIdx];
            Log(detailLog, $"real_dragon_pick seed={seed} index={realIdx}/{pool.Count} {realPick.MapFile}:{realPick.EnemyName} model={realPick.Model}");
            return realPick;
        }

        if (key == "godrick")
        {
            var pick = FindDonorInProbeMaps(gameDir, GodrickProbeMaps, m => m.StartsWith("c4750", StringComparison.OrdinalIgnoreCase), "godrick", detailLog);
            if (pick != null)
            {
                return pick;
            }
            Log(detailLog, "godrick_pick=fallback_csv npc=47500014 think=47500000");
            return new DonorEntry("godrick", "csv_fallback", "synthetic_c4750", "c4750", 47500014, 47500000, -1);
        }

        if (key == "elden_beast")
        {
            var pick = FindDonorInProbeMaps(gameDir, EldenBeastProbeMaps, m => m.StartsWith("c2200", StringComparison.OrdinalIgnoreCase), "elden_beast", detailLog);
            if (pick != null)
            {
                return pick;
            }
            Log(detailLog, "elden_beast_pick=fallback_csv npc=22000078 think=22000000");
            return new DonorEntry("elden_beast", "csv_fallback", "synthetic_c2200", "c2200", 22000078, 22000000, -1);
        }

        if (key == "rune_trash")
        {
            var pick = FindDonorInProbeMaps(gameDir, new[] { $"{MapId}.msb.dcx" }, m => m.StartsWith("c4311", StringComparison.OrdinalIgnoreCase), "rune_trash", detailLog);
            if (pick != null && pick.Npc != 43110010)
            {
                return pick;
            }
            Log(detailLog, "rune_trash_pick=fallback_csv npc=43111210 think=43110000");
            return new DonorEntry("rune_trash", "csv_fallback", "synthetic_c4311_spear", "c4311", 43111210, 43110000, -1);
        }

        if (key == "rune_medium")
        {
            var pick = FindDonorInProbeMaps(gameDir, RuneMediumProbeMaps, m => m.StartsWith("c4200", StringComparison.OrdinalIgnoreCase), "rune_medium", detailLog);
            if (pick != null)
            {
                return pick;
            }
            Log(detailLog, "rune_medium_pick=fallback_csv npc=42000000 think=42000000");
            return new DonorEntry("rune_medium", "csv_fallback", "synthetic_c4200", "c4200", 42000000, 42000000, -1);
        }

        if (key == "rune_heavy")
        {
            var pick = FindDonorInProbeMaps(gameDir, RuneMediumProbeMaps, m => m.StartsWith("c3251", StringComparison.OrdinalIgnoreCase), "rune_heavy", detailLog);
            if (pick != null)
            {
                return pick;
            }
            Log(detailLog, "rune_heavy_pick=fallback_csv npc=32510010 think=32510900");
            return new DonorEntry("rune_heavy", "csv_fallback", "synthetic_c3251", "c3251", 32510010, 32510900, -1);
        }

        return null;
    }

    static DonorEntry? FindDonorInProbeMaps(
        string gameDir,
        IEnumerable<string> mapFiles,
        Func<string, bool> modelMatch,
        string label,
        StringBuilder detailLog)
    {
        foreach (var mapFile in mapFiles)
        {
            var enemies = TryReadMapEnemies(gameDir, mapFile, detailLog);
            if (enemies == null)
            {
                continue;
            }

            var hit = enemies.FirstOrDefault(e => modelMatch(e.ModelName ?? ""));
            if (hit == null)
            {
                continue;
            }

            var pick = new DonorEntry(label, mapFile, hit.Name, hit.ModelName, hit.NPCParamID, hit.ThinkParamID, hit.CharaInitID);
            Log(detailLog, $"{label}_pick {pick.MapFile}:{pick.EnemyName} model={pick.Model} npc={pick.Npc} think={pick.Think}");
            return pick;
        }

        return null;
    }

    static byte[]? TryReadMapBytes(string gameDir, string mapFileName, StringBuilder detailLog)
    {
        var modPath = Path.Combine(CnvMapStudioDir(gameDir), mapFileName);
        if (File.Exists(modPath))
        {
            Log(detailLog, $"map_bytes={modPath}");
            return File.ReadAllBytes(modPath);
        }

        var msbeName = mapFileName.Replace(".msb.dcx", ".msbe.dcx", StringComparison.OrdinalIgnoreCase);
        foreach (var rel in new[] { $"map/mapstudio/{mapFileName}", $"map/mapstudio/{msbeName}" })
        {
            var bytes = TryReadBytesFromBhd(gameDir, rel, detailLog);
            if (bytes != null)
            {
                return bytes;
            }
        }

        Log(detailLog, $"map_bytes_missing={mapFileName}");
        return null;
    }

    static byte[]? TryReadBytesFromBhd(string gameDir, string relPath, StringBuilder detailLog)
    {
        try
        {
            var hash = HashHelper.FromPathHash(relPath);
            EnsureBhdFileIndex(gameDir);
            if (BhdFileIndex != null && BhdFileIndex.TryGetValue(hash, out var entry))
            {
                using var bdt = File.OpenRead(entry.Item1);
                Log(detailLog, $"bhd_pick={relPath} indexed");
                return entry.Item2.ReadFile(bdt);
            }

            foreach (var bhdName in new[] { "Data0.bhd", "Data1.bhd", "Data2.bhd", "Data3.bhd", "DLC.bhd" })
            {
                var bhdPath = Path.Combine(gameDir, bhdName);
                if (!File.Exists(bhdPath))
                {
                    continue;
                }

                using var bhdStream = File.OpenRead(bhdPath);
                var bhd = BHD5.Read(bhdStream, BHD5.Game.EldenRing);
                var bdtPath = Path.ChangeExtension(bhdPath, ".bdt");
                using var bdt = File.OpenRead(bdtPath);
                foreach (var bucket in bhd.Buckets)
                {
                    for (var i = 0; i < bucket.Count; i++)
                    {
                        var header = bucket[i];
                        if (header.FileNameHash != hash)
                        {
                            continue;
                        }

                        Log(detailLog, $"bhd_pick={relPath} from {bhdName}");
                        return header.ReadFile(bdt);
                    }
                }
            }
        }
        catch (Exception ex)
        {
            Log(detailLog, $"bhd_error {relPath}: {ex.Message}");
        }

        return null;
    }

    static void ApplyMountSuppress(MSBE.Part.Enemy target, PatchRecord record)
    {
        record.BeforeModel = target.ModelName;
        record.BeforeNpc = target.NPCParamID;
        record.BeforeThink = target.ThinkParamID;
        record.BeforeChara = target.CharaInitID;
        record.BeforeBackupAnim = target.BackupEventAnimID;
        record.BeforeWalkRoute = target.WalkRouteName ?? "";
        record.PosX = target.Position.X;
        record.PosY = target.Position.Y;
        record.PosZ = target.Position.Z;

        // 勿改 model/npc 为 c0000/0（全图会崩）。沉到地下 + 清巡逻，马体不进场。
        target.WalkRouteName = "";
        target.BackupEventAnimID = -1;
        var pos = target.Position;
        target.Position = new System.Numerics.Vector3(pos.X, -100000f, pos.Z);

        record.AfterModel = target.ModelName;
        record.AfterNpc = target.NPCParamID;
        record.AfterThink = target.ThinkParamID;
        record.AfterChara = target.CharaInitID;
        record.AfterBackupAnim = target.BackupEventAnimID;
        record.AfterWalkRoute = target.WalkRouteName ?? "";
        record.RouteCleared = true;
    }

    static int RunBossBatch(
        string gameDir,
        MSBE msb,
        IList<MSBE.Part.Enemy> enemies,
        StringBuilder detailLog,
        string[] args,
        (string SlotName, string DonorKey, string Note)[] plan,
        int defaultSeed,
        string batchTag,
        string spoilerFileName,
        string titleFormat,
        string subtitle,
        string checkLine)
    {
        var seed = ResolveSeed(args, defaultSeed);
        Log(detailLog, $"{batchTag}_seed={seed}");
        Console.WriteLine(string.Format(titleFormat, seed));
        Console.WriteLine(subtitle);
        Console.WriteLine();

        var donorNotes = new List<string>();

        foreach (var (slotName, donorKey, note) in plan)
        {
            var target = enemies.FirstOrDefault(e => string.Equals(e.Name, slotName, StringComparison.OrdinalIgnoreCase));
            if (target == null)
            {
                Console.Error.WriteLine($"Missing slot {slotName} on {MapId}");
                WriteDetailLog(detailLog, $"{batchTag}_failed=missing_slot:{slotName}");
                return 1;
            }

            var donorMeta = ResolveDonor(donorKey, gameDir, seed, detailLog);
            if (donorMeta == null)
            {
                Console.Error.WriteLine($"No donor for {donorKey}. Run: ENEMY_POC.bat scan-donors");
                WriteDetailLog(detailLog, $"{batchTag}_failed=no_donor:{donorKey}");
                return 1;
            }

            var donorPart = FindEnemyPartEntryByName(gameDir, donorMeta.MapFile, donorMeta.EnemyName, detailLog);
            var donorEnemy = BuildDonorPart(donorMeta, donorPart);

            EnsureEnemyModel(msb, donorEnemy.ModelName, gameDir, detailLog);

            var record = new PatchRecord
            {
                Name = target.Name,
                EntityId = target.EntityID,
                PosX = target.Position.X,
                PosY = target.Position.Y,
                PosZ = target.Position.Z,
                Groups = string.Join(",", target.EntityGroupIDs),
            };

            ApplyDonorTransplant(target, donorEnemy, record, donorBehaviorRef: donorPart);

            var donorSrc = donorPart != null
                ? $"{donorMeta.MapFile}:{donorMeta.EnemyName}"
                : $"csv_fallback {donorMeta.Model}";
            var summary =
                $"  SLOT {slotName} ({note})  <=  {donorKey} from {donorSrc}  model={donorEnemy.ModelName}  npc={donorEnemy.NPCParamID}  think={donorEnemy.ThinkParamID}  chara={donorEnemy.CharaInitID}  sit_clear={record.SitCleared}";
            Console.WriteLine(summary);
            Log(detailLog, summary.Trim());
            donorNotes.Add($"{slotName}\t{donorKey}\t{donorSrc}\t{donorEnemy.ModelName}");
        }

        var outDir = OverlayMapStudioDir(gameDir);
        Directory.CreateDirectory(outDir);
        var outMsb = Path.Combine(outDir, $"{MapId}.msb.dcx");
        var outMsbe = Path.Combine(outDir, $"{MapId}.msbe.dcx");
        var written = WriteMsbe(msb);
        File.WriteAllBytes(outMsb, written);
        File.WriteAllBytes(outMsbe, written);

        var spoilerPath = Path.Combine(ResolveToolRoot(), spoilerFileName);
        var spoiler = new StringBuilder();
        spoiler.AppendLine($"# {batchTag} — Gatefront test placements");
        spoiler.AppendLine($"seed={seed}");
        spoiler.AppendLine($"map={MapId}");
        spoiler.AppendLine("# slot\tdonor_key\tdonor_map\tdonor_entity\tmodel");
        foreach (var line in donorNotes)
        {
            spoiler.AppendLine(line);
        }
        spoiler.AppendLine();
        spoiler.AppendLine("In-game: quit fully -> Start_Convergence -> new char or NG -> Gatefront");
        spoiler.AppendLine(checkLine);
        File.WriteAllText(spoilerPath, spoiler.ToString(), Encoding.UTF8);

        Log(detailLog, $"wrote_msb={outMsb} bytes={written.Length}");
        Log(detailLog, $"spoiler={spoilerPath}");
        Console.WriteLine();
        Console.WriteLine($"Wrote overlay {outMsb}");
        Console.WriteLine($"Spoiler {spoilerPath}");
        WriteMe3OverlayInstructions(gameDir, detailLog);
        Console.WriteLine("In-game: fully quit game -> Start_Convergence.bat -> Gatefront (关卡前哨)");

        var manifestPath = Path.Combine(outDir, $"cnv_enemy_{batchTag}_manifest.txt");
        File.WriteAllText(manifestPath, detailLog.ToString(), Encoding.UTF8);
        WriteDetailLog(detailLog, $"{batchTag}_ok");
        return 0;
    }

    static MSBE.Part.Enemy BuildDonorPart(DonorEntry meta, MSBE.Part.Enemy? donorPart)
    {
        if (donorPart != null)
        {
            return donorPart;
        }

        return new MSBE.Part.Enemy
        {
            Name = meta.EnemyName,
            ModelName = meta.Model,
            NPCParamID = meta.Npc,
            ThinkParamID = meta.Think,
            CharaInitID = meta.Chara,
        };
    }

    static MSBE.Part.Enemy? FindEnemyPartEntryByName(string gameDir, string mapFile, string enemyName, StringBuilder detailLog)
    {
        if (string.Equals(mapFile, "csv_fallback", StringComparison.OrdinalIgnoreCase))
        {
            return null;
        }

        var index = GetDonorEnemyIndex(gameDir, mapFile, detailLog);
        if (index.TryGetValue(enemyName, out var hit))
        {
            return hit;
        }

        foreach (var enemy in index.Values)
        {
            if (string.Equals(enemy.ModelName, enemyName, StringComparison.OrdinalIgnoreCase))
            {
                return enemy;
            }
        }

        return null;
    }

}

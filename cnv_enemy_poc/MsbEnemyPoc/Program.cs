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

// Shared MSB I/O, index export, list/inspect

static partial class Program
{
    const string MapId = "m60_42_37_00";

    const string MapRelPath = "map/mapstudio/m60_42_37_00.msbe.dcx";

    const uint WagonGroupId = 1042375810u;

    const string SourceModel = "c4311"; // Godrick Soldier (Gatefront caravan)

    const string TargetModel = "c3251";  // Tree Sentinel

    const int TargetNpcParam = 32510010; // Tree Sentinel (Limgrave field)

    const int TargetThinkParam = 32510900; // from m60_42_36_00 field sentinel

    const int SourceNpcParam = 43110010;   // Gatefront Godrick soldier (sword+shield)
    const string EnemyOverlayPackage = "cnv_enemy";



    static int Main(string[] args)

    {

        var gameDir = ResolveGameDir(args);

        var msbOverride = ResolveMsbOverride(args);

        var mode = args.FirstOrDefault(a => !a.StartsWith("--")) ?? "list";

        var detailLog = new StringBuilder();



        Log(detailLog, $"mode={mode}");

        Log(detailLog, $"game_dir={gameDir}");

        Log(detailLog, $"tool_root={ResolveToolRoot()}");

        Log(detailLog, $"ringrandom_root={ResolveRingrandomRoot()}");

        if (!string.IsNullOrWhiteSpace(msbOverride))

        {

            Log(detailLog, $"--msb override={msbOverride}");

        }



        if (mode == "verify")
        {
            return VerifyParams(ResolveCsvDir(gameDir), detailLog);
        }

        if (mode == "restore")
        {
            return RestoreOverlay(gameDir, detailLog);
        }

        if (mode == "scan-donors")
        {
            return ScanDonors(gameDir, detailLog);
        }

        if (mode == "index-export")
        {
            return ExportEnemyIndex(gameDir, args, detailLog);
        }

        if (mode == "pickup-index-export")
        {
            return ExportPickupIndex(gameDir, args, detailLog);
        }

        if (mode == "apply-map")
        {
            return ApplySpawnMap(gameDir, args, detailLog);
        }

        string? loadPath = msbOverride;
        if (mode is "patch" or "boss-batch1" or "boss-batch2")
        {
            loadPath = ResolvePatchSource(gameDir, detailLog);
            if (loadPath == null)
            {
                Console.Error.WriteLine(
                    """
                    Cannot patch: read CNV mod MSB failed (repair Convergence if missing or already corrupted).
                    Output goes to mod/cnv_enemy/ — CNV mod/map/MapStudio is read-only.
                    Run: ENEMY_POC.bat restore   to remove overlay only
                    """);
                WriteDetailLog(detailLog, "patch_failed=no_cnv_source");
                return 1;
            }
        }

        var load = LoadMap(gameDir, MapRelPath, loadPath, detailLog);

        var msb = ReadMsbe(load.Bytes);

        var enemies = msb.Parts.Enemies;



        var wagonSoldiers = FilterSoldiers(enemies, wagonOnly: true);

        var allSoldiers = FilterSoldiers(enemies, wagonOnly: false);

        var treeSentinels = enemies

            .Where(e => e.ModelName.StartsWith(TargetModel, StringComparison.OrdinalIgnoreCase))

            .OrderBy(e => e.EntityID)

            .ToList();



        Log(detailLog, $"msb_source={load.SourcePath}");

        Log(detailLog, $"msb_source_bytes={load.Bytes.Length}");

        Log(detailLog, $"msb_source_sha256={load.Sha256}");

        Log(detailLog, $"map={MapId} total_enemies={enemies.Count}");

        Log(detailLog, $"wagon_group_{WagonGroupId}_{SourceModel}={wagonSoldiers.Count}");

        Log(detailLog, $"all_{SourceModel}={allSoldiers.Count}");

        Log(detailLog, $"reference_{TargetModel}={treeSentinels.Count}");



        Console.WriteLine($"Map {MapId}: {enemies.Count} enemies");

        Console.WriteLine($"  MSB source: {load.SourcePath} ({load.Bytes.Length} bytes)");

        Console.WriteLine($"  wagon-group {SourceModel} (group {WagonGroupId}): {wagonSoldiers.Count}");

        Console.WriteLine($"  all {SourceModel}: {allSoldiers.Count}");

        Console.WriteLine($"  reference {TargetModel}: {treeSentinels.Count}");



        if (treeSentinels.Count > 0)

        {

            var refEnemy = treeSentinels[0];

            var refLine =

                $"  ref entity={refEnemy.EntityID} npc={refEnemy.NPCParamID} think={refEnemy.ThinkParamID} chara={refEnemy.CharaInitID}";

            Console.WriteLine(refLine);

            Log(detailLog, refLine.Trim());

        }



        foreach (var e in wagonSoldiers)

        {

            var line = FormatEnemy("wagon", e);

            Console.WriteLine(line);

            Log(detailLog, line.Trim());

        }



        if (wagonSoldiers.Count == 0)

        {

            Console.WriteLine("  (no wagon-group soldiers — listing all Godrick soldiers on map)");

            Log(detailLog, "no_wagon_group_soldiers=true");

            foreach (var e in allSoldiers.Take(12))

            {

                var line = FormatEnemy("soldier", e, includePos: true);

                Console.WriteLine(line);

                Log(detailLog, line.Trim());

            }

        }



        if (mode == "list")
        {
            Console.WriteLine();
            Console.WriteLine("Run: patch   — replace ALL Gatefront Godrick soldiers with Tree Sentinel");
            Console.WriteLine("     boss-batch1 — 3 slots: random dragon + Godrick + Elden Beast (Gatefront test)");
            Console.WriteLine("     boss-batch2 — 5 slots: real dragon + Elden Beast c2200 + 3 rune compare");
            Console.WriteLine("     scan-donors — list boss/dragon templates in CNV mod/map");
            Console.WriteLine("     index-export — export ALL map MSB enemies to JSON (overworld+legacy; --out= path)");
            Console.WriteLine("     pickup-index-export — export MSB treasure placements (ItemLot) to JSON (--out= path)");
            Console.WriteLine("     apply-map — patch MSB overlay from cnv_enemy_spawn_map.txt (--spawn-map= path)");
            Console.WriteLine("     restore — delete mod/cnv_enemy overlay (CNV source untouched)");
            Console.WriteLine("     inspect — dump idle/patrol MSB fields for soldiers vs Tree Sentinel ref");
            Console.WriteLine("     verify — check NpcParam/NpcThinkParam in Game\\csv (no MSB needed)");
            WriteDetailLog(detailLog, "list");
            return 0;
        }

        if (mode == "inspect")
        {
            DumpEnemyStates(allSoldiers, gameDir, detailLog);
            WriteDetailLog(detailLog, "inspect");
            return 0;
        }

        if (mode == "area")
        {
            var areaId = args.FirstOrDefault(a => uint.TryParse(a, out _)) is { } s && uint.TryParse(s, out var id) ? id : 1042372808u;
            DumpArea(msb, areaId);
            return 0;
        }

        if (mode == "boss-batch1")
        {
            return RunBossBatch(
                gameDir, msb, enemies, detailLog, args,
                Batch1Plan, 42001, "boss_batch1", "boss_batch1_spoiler.txt",
                "Boss batch 1 — Gatefront (seed {0})",
                "Only 3 soldier slots change; all other enemies stay vanilla.",
                "Check: dragon terrain at forest patrol, Godrick phases, Elden Beast at camp sit spot");
        }

        if (mode == "boss-batch2")
        {
            return RunBossBatch(
                gameDir, msb, enemies, detailLog, args,
                Batch2Plan, 42002, "boss_batch2", "boss_batch2_spoiler.txt",
                "Boss batch 2 — Gatefront (seed {0})",
                "5 slots: real dragon + Elden Beast c2200 + 3 rune tier compares.",
                "Check: dragon visible at wagon field, Elden Beast model, rune amounts on 9004/9008/9012 kills");
        }



        if (mode != "patch")

        {

            Console.Error.WriteLine($"Unknown mode: {mode}");

            return 2;

        }



        var patchTargets = allSoldiers;

        if (patchTargets.Count == 0)

        {

            Console.Error.WriteLine("No soldiers found on this map.");

            Log(detailLog, "ERROR=no_soldiers_to_patch");

            WriteDetailLog(detailLog, "patch_failed");

            return 1;

        }



        Log(detailLog, $"patch_scope=all_{SourceModel}_on_{MapId}");

        Log(detailLog, $"patch_count={patchTargets.Count}");

        Log(detailLog, $"target_model={TargetModel} target_npc={TargetNpcParam} target_think={TargetThinkParam}");

        DumpArea(msb, 1042372808u);
        Log(detailLog, "vanguard_warp_area=1042372808 (Gatefront bridge — must come from CNV MSB, not vanilla cache)");

        EnsureEnemyModel(msb, TargetModel, gameDir, detailLog);

        Console.WriteLine();

        Console.WriteLine($"Patching {patchTargets.Count} {SourceModel} -> {TargetModel} ...");



        var patchRecords = new List<PatchRecord>();

        foreach (var enemy in patchTargets)

        {

            var record = new PatchRecord

            {

                Name = enemy.Name,

                EntityId = enemy.EntityID,

                PosX = enemy.Position.X,

                PosY = enemy.Position.Y,

                PosZ = enemy.Position.Z,

                Groups = string.Join(",", enemy.EntityGroupIDs),

                BeforeModel = enemy.ModelName,

                BeforeNpc = enemy.NPCParamID,

                BeforeThink = enemy.ThinkParamID,

                BeforeChara = enemy.CharaInitID,

            };



            enemy.ModelName = TargetModel;

            enemy.NPCParamID = TargetNpcParam;

            enemy.ThinkParamID = TargetThinkParam;

            ApplyTransplantBehavior(enemy, record);

            record.AfterModel = enemy.ModelName;

            record.AfterNpc = enemy.NPCParamID;

            record.AfterThink = enemy.ThinkParamID;

            record.AfterChara = enemy.CharaInitID;

            patchRecords.Add(record);



            var line =
                $"  PATCH #{patchRecords.Count:D2} name={record.Name} sit_clear={record.SitCleared} " +
                $"backup {record.BeforeBackupAnim}->{record.AfterBackupAnim} route='{record.BeforeWalkRoute}' (unchanged)";

            Console.WriteLine(line);

            Log(detailLog, line.Trim());

        }



        var outDir = OverlayMapStudioDir(gameDir);
        Directory.CreateDirectory(outDir);

        var outMsb = Path.Combine(outDir, $"{MapId}.msb.dcx");
        var outMsbe = Path.Combine(outDir, $"{MapId}.msbe.dcx");
        var existingOverlay = File.Exists(outMsb);



        Log(detailLog, $"overlay_mapstudio_dir={outDir}");
        Log(detailLog, $"cnv_source_readonly={ModMsbPath(gameDir)}");
        Log(detailLog, $"preexisting_overlay={existingOverlay}");

        var written = WriteMsbe(msb);

        File.WriteAllBytes(outMsb, written);

        File.WriteAllBytes(outMsbe, written);



        var verifyMsb = ReadMsbe(File.ReadAllBytes(outMsb));

        var verifySentinels = verifyMsb.Parts.Enemies

            .Where(e => e.ModelName.StartsWith(TargetModel, StringComparison.OrdinalIgnoreCase))

            .ToList();

        var verifySoldiers = FilterSoldiers(verifyMsb.Parts.Enemies, wagonOnly: false);



        Log(detailLog, $"wrote_msb={outMsb} bytes={written.Length} sha256={Sha256Hex(written)}");

        Log(detailLog, $"wrote_msbe={outMsbe} bytes={written.Length}");

        Log(detailLog, $"verify_sentinel_count={verifySentinels.Count}");

        Log(detailLog, $"verify_remaining_{SourceModel}={verifySoldiers.Count}");



        Console.WriteLine();

        Console.WriteLine($"Wrote overlay {outMsb} ({written.Length} bytes)");
        Console.WriteLine($"CNV source NOT modified: {ModMsbPath(gameDir)}");
        Console.WriteLine();
        WriteMe3OverlayInstructions(gameDir, detailLog);

        Console.WriteLine("In-game: fully quit game -> Start_Convergence.bat -> NG or new char -> Gatefront");



        var manifestPath = Path.Combine(outDir, "cnv_enemy_poc_manifest.txt");

        var manifest = BuildManifest(patchRecords, load, outMsb, outMsbe, verifySentinels.Count, verifySoldiers.Count);

        File.WriteAllText(manifestPath, manifest, Encoding.UTF8);

        Log(detailLog, $"manifest={manifestPath}");

        Console.WriteLine($"Manifest {manifestPath}");



        WriteDetailLog(detailLog, "patch");

        var gameLog = Path.Combine(outDir, "cnv_enemy_poc_last_run.txt");

        File.WriteAllText(gameLog, detailLog.ToString(), Encoding.UTF8);

        Console.WriteLine($"Detail log {ResolveToolRoot()}\\enemy_poc_detail.txt");

        Console.WriteLine($"Detail log (game) {gameLog}");



        return verifySentinels.Count == patchTargets.Count && verifySoldiers.Count == 0 ? 0 : 3;

    }

    static string CnvMapStudioDir(string gameDir)
    {
        foreach (var path in new[]
        {
            Path.Combine(gameDir, "mod", "map", "MapStudio"),
            Path.Combine(gameDir, "mod", "map", "mapstudio"),
        })
        {
            if (Directory.Exists(path))
            {
                return path;
            }
        }

        return Path.Combine(gameDir, "mod", "map", "MapStudio");
    }

    static string OverlayMapStudioDir(string gameDir) =>
        Path.Combine(gameDir, "mod", EnemyOverlayPackage, "map", "MapStudio");

    static string ModMsbPath(string gameDir) =>
        Path.Combine(CnvMapStudioDir(gameDir), $"{MapId}.msb.dcx");

    static string? LegacyBaselinePath(string gameDir)
    {
        var bak = ModMsbPath(gameDir) + ".cnv_bak";
        return File.Exists(bak) ? bak : null;
    }

    static int CountModel(MSBE msb, string model) =>
        msb.Parts.Enemies.Count(e => e.ModelName.StartsWith(model, StringComparison.OrdinalIgnoreCase));

    static int RestoreOverlay(string gameDir, StringBuilder detailLog)
    {
        var overlayRoot = Path.Combine(gameDir, "mod", EnemyOverlayPackage);
        if (Directory.Exists(overlayRoot))
        {
            Directory.Delete(overlayRoot, recursive: true);
            Log(detailLog, $"removed_overlay={overlayRoot}");
            Console.WriteLine($"Removed overlay: {overlayRoot}");
        }
        else
        {
            Console.WriteLine("No overlay to remove (mod/cnv_enemy missing).");
        }

        var legacyBak = LegacyBaselinePath(gameDir);
        if (legacyBak != null)
        {
            File.Copy(legacyBak, ModMsbPath(gameDir), overwrite: true);
            Console.WriteLine($"Restored CNV MSB from legacy backup: {legacyBak}");
            Log(detailLog, $"restored_cnv_from={legacyBak}");
        }

        WriteDetailLog(detailLog, "restore");
        Console.WriteLine("CNV mod/map/MapStudio left as-is unless legacy .cnv_bak existed.");
        return 0;
    }

    static void WriteMe3OverlayInstructions(string gameDir, StringBuilder detailLog)
    {
        var snippetPath = Path.Combine(ResolveToolRoot(), "cnv_enemy_me3_snippet.toml");
        var snippet = """
            # Add ONCE to Game/me3/convergence.me3 (after convergence-er package):
            [[package]]
            id = "cnv-enemy-poc"
            path = "./../mod/cnv_enemy"
            load_after = [{ id = "convergence-er", optional = false }]
            """;
        File.WriteAllText(snippetPath, snippet, Encoding.UTF8);
        Log(detailLog, $"me3_snippet={snippetPath}");

        var me3Path = Path.Combine(gameDir, "me3", "convergence.me3");
        Console.WriteLine("ME3 overlay (loads AFTER Convergence, does not edit CNV files):");
        Console.WriteLine($"  Append snippet from: {snippetPath}");
        Console.WriteLine($"  To: {me3Path}");
        Console.WriteLine("  Disable: ENEMY_POC.bat restore");
    }

    static void DumpArea(MSBE msb, uint entityId)
    {
        var hits = new List<MSBE.Region>();
        foreach (var region in msb.Regions.GetEntries())
        {
            if (region is MSBE.Region r && r.EntityID == entityId)
            {
                hits.Add(r);
            }
        }

        Console.WriteLine($"Map {MapId}: area entity {entityId} hits={hits.Count}");
        foreach (var r in hits)
        {
            Console.WriteLine($"  name={r.Name} pos=({r.Position.X:F1},{r.Position.Y:F1},{r.Position.Z:F1}) mapId={r.MapID}");
        }
    }

    static void DumpEnemyStates(List<MSBE.Part.Enemy> soldiers, string gameDir, StringBuilder detailLog)
    {
        var refEnemy = FindEnemyPartEntry(gameDir, TargetModel, detailLog);
        if (refEnemy != null)
        {
            var line = FormatEnemyState("REF_SENTINEL", refEnemy);
            Console.WriteLine(line);
            Log(detailLog, line.Trim());
        }
        else
        {
            Console.WriteLine("  (no Tree Sentinel reference part found in mod maps)");
        }

        foreach (var e in soldiers)
        {
            var line = FormatEnemyState("SOLDIER", e);
            Console.WriteLine(line);
            Log(detailLog, line.Trim());
        }
    }

    static string FormatEnemyState(string label, MSBE.Part.Enemy e) =>
        $"  {label} name={e.Name} npc={e.NPCParamID} think={e.ThinkParamID} " +
        $"backup_anim={e.BackupEventAnimID} walk_route='{e.WalkRouteName}' collision='{e.CollisionPartName}' " +
        $"chara={e.CharaInitID} platoon={e.PlatoonID} chr_activate={e.ChrActivateCondParamID} spfx={e.SpEffectSetParamID}";

    static readonly string[] SiegeWeaponModelPrefixes =
    {
        "c8100", // ballista / trebuchet body
        "c8101", // giant ballista
        "c8110", // dragon-flame / flamethrower siege
    };

    static bool IsSiegeWeaponPartName(string? partName)
    {
        if (string.IsNullOrWhiteSpace(partName))
        {
            return false;
        }

        var name = partName.ToLowerInvariant();
        return SiegeWeaponModelPrefixes.Any(p => name.StartsWith(p, StringComparison.Ordinal));
    }

    static Dictionary<string, string> IndexSiegeMountRiders(MSBE msb)
    {
        var riders = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var mountEvt in msb.Events.Mounts)
        {
            var mountPart = mountEvt.MountPartName ?? "";
            if (!IsSiegeWeaponPartName(mountPart))
            {
                continue;
            }

            var riderPart = mountEvt.RiderPartName ?? "";
            if (string.IsNullOrWhiteSpace(riderPart))
            {
                continue;
            }

            riders[riderPart] = mountPart;
        }

        return riders;
    }

    static HashSet<string> CollectWalkRouteNames(MSBE msb)
    {
        var names = new HashSet<string>(StringComparer.Ordinal);
        foreach (var route in msb.Routes.GetEntries())
        {
            if (!string.IsNullOrWhiteSpace(route.Name))
            {
                names.Add(route.Name);
            }
        }

        return names;
    }

    static int SanitizeDanglingWalkRoutes(MSBE msb, StringBuilder? detailLog = null)
    {
        var valid = CollectWalkRouteNames(msb);
        var cleared = 0;
        foreach (var enemy in msb.Parts.Enemies)
        {
            if (string.IsNullOrWhiteSpace(enemy.WalkRouteName))
            {
                continue;
            }

            if (valid.Contains(enemy.WalkRouteName))
            {
                continue;
            }

            detailLog?.AppendLine(
                $"sanitize_walk_route enemy={enemy.Name} route='{enemy.WalkRouteName}'");
            enemy.WalkRouteName = "";
            cleared++;
        }

        return cleared;
    }

    static HashSet<string> CollectCollisionPartNames(MSBE msb)
    {
        var names = new HashSet<string>(StringComparer.Ordinal);
        foreach (var part in msb.Parts.GetEntries())
        {
            if (!string.IsNullOrWhiteSpace(part.Name))
            {
                names.Add(part.Name);
            }
        }

        return names;
    }

    static int SanitizeDanglingCollisionParts(MSBE msb, StringBuilder? detailLog = null)
    {
        var valid = CollectCollisionPartNames(msb);
        var cleared = 0;
        foreach (var enemy in msb.Parts.Enemies)
        {
            if (string.IsNullOrWhiteSpace(enemy.CollisionPartName))
            {
                continue;
            }

            if (valid.Contains(enemy.CollisionPartName))
            {
                continue;
            }

            detailLog?.AppendLine(
                $"sanitize_collision enemy={enemy.Name} part='{enemy.CollisionPartName}'");
            enemy.CollisionPartName = "";
            cleared++;
        }

        return cleared;
    }

    static void TryDeleteFileIfExists(string? path)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            return;
        }

        try
        {
            File.Delete(path);
        }
        catch
        {
            // best-effort cleanup after failed MSB write
        }
    }

    static void WriteOverlayMsbPair(MSBE msb, string outMsb, string outMsbe, StringBuilder? detailLog = null)
    {
        // T-073 §2.1: target-slot WalkRoute must survive apply. Convergence MSBs often keep
        // Japanese / legacy route names on enemies while msb.Routes only lists runtime stubs —
        // SanitizeDanglingWalkRoutes would strip every patrol slot (真机：狗站桩不巡逻).
        // Collision sanitize stays (map-local part names).
        var clearedCollisions = SanitizeDanglingCollisionParts(msb, detailLog);
        if (clearedCollisions > 0 && detailLog != null)
        {
            detailLog.AppendLine($"sanitize_collision_total={clearedCollisions}");
        }

        var tempMsb = outMsb + ".tmp";
        TryDeleteFileIfExists(tempMsb);
        try
        {
            WriteMsbeToPath(msb, tempMsb);
            if (new FileInfo(tempMsb).Length == 0)
            {
                throw new IOException($"msb_write_empty {outMsb}");
            }

            if (File.Exists(outMsb))
            {
                File.Delete(outMsb);
            }

            File.Move(tempMsb, outMsb);
            TryWriteOutputMsbeCopy(outMsb, outMsbe);
        }
        catch
        {
            TryDeleteFileIfExists(tempMsb);
            TryDeleteFileIfExists(outMsb);
            TryDeleteFileIfExists(outMsbe);
            throw;
        }
    }

    static string? ResolveDonorMapId(string templateId, string fallbackMapId)
    {
        if (string.IsNullOrWhiteSpace(templateId))
        {
            return fallbackMapId;
        }

        if (templateId.StartsWith("synthetic:", StringComparison.OrdinalIgnoreCase))
        {
            return SyntheticTemplateSources.TryGetValue(templateId, out var src)
                ? src.MapId
                : fallbackMapId;
        }

        var colon = templateId.IndexOf(':');
        if (colon <= 0)
        {
            return fallbackMapId;
        }

        return templateId[..colon];
    }

    sealed record SyntheticTemplateSource(string MapId, string EntityName);

    static readonly Dictionary<string, SyntheticTemplateSource> SyntheticSourceOverrides =
        new(StringComparer.OrdinalIgnoreCase)
        {
            ["synthetic:godfrey_c5770"] = new("m29_00_00_00", "c5770_9000"),
            ["synthetic:radahn_c4730"] = new("m42_03_00_00", "c4730_9000"),
            ["synthetic:red_wolf_c4370"] = new("m14_02_00_00", "c4370_9000"),
        };

    static Dictionary<string, SyntheticTemplateSource> SyntheticTemplateSources =
        new(StringComparer.OrdinalIgnoreCase);

    static void LoadSyntheticTemplateSources()
    {
        SyntheticTemplateSources = new Dictionary<string, SyntheticTemplateSource>(StringComparer.OrdinalIgnoreCase);
        var categoriesPath = Path.Combine(
            ResolveRingrandomRoot(),
            "cnv_randomizer",
            "enemy_categories.json");
        var indexPath = Path.Combine(
            ResolveRingrandomRoot(),
            "cnv_randomizer",
            "cache",
            "enemy_index.json");
        if (!File.Exists(categoriesPath))
        {
            foreach (var kv in SyntheticSourceOverrides)
            {
                SyntheticTemplateSources[kv.Key] = kv.Value;
            }

            return;
        }

        using var categoriesDoc = JsonDocument.Parse(File.ReadAllText(categoriesPath, Encoding.UTF8));
        if (!categoriesDoc.RootElement.TryGetProperty("synthetic_boss_templates", out var templates)
            || templates.ValueKind != JsonValueKind.Array)
        {
            return;
        }

        Dictionary<string, List<(string MapId, string EntityName, int Rank)>> indexByModel = new(
            StringComparer.OrdinalIgnoreCase);
        if (File.Exists(indexPath))
        {
            using var indexDoc = JsonDocument.Parse(File.ReadAllText(indexPath, Encoding.UTF8));
            if (indexDoc.RootElement.TryGetProperty("templates", out var indexTemplates)
                && indexTemplates.ValueKind == JsonValueKind.Array)
            {
                foreach (var row in indexTemplates.EnumerateArray())
                {
                    var donorMap = row.TryGetProperty("donor_map", out var mapEl)
                        ? mapEl.GetString() ?? ""
                        : "";
                    var donorEntity = row.TryGetProperty("donor_entity", out var entityEl)
                        ? entityEl.GetString() ?? ""
                        : "";
                    var model = row.TryGetProperty("model", out var modelEl)
                        ? modelEl.GetString() ?? ""
                        : "";
                    if (string.IsNullOrWhiteSpace(model)
                        || string.IsNullOrWhiteSpace(donorMap)
                        || string.Equals(donorMap, "synthetic", StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }

                    var mapId = donorMap
                        .Replace(".msb.dcx", "", StringComparison.OrdinalIgnoreCase)
                        .Replace(".msbe.dcx", "", StringComparison.OrdinalIgnoreCase);
                    if (!IsValidDonorMapId(mapId) || string.IsNullOrWhiteSpace(donorEntity))
                    {
                        continue;
                    }

                    var rank = ScoreSyntheticIndexSource(mapId, donorEntity);
                    if (!indexByModel.TryGetValue(model, out var hits))
                    {
                        hits = new List<(string, string, int)>();
                        indexByModel[model] = hits;
                    }

                    hits.Add((mapId, donorEntity, rank));
                }
            }
        }

        foreach (var raw in templates.EnumerateArray())
        {
            var templateId = raw.TryGetProperty("template_id", out var idEl)
                ? idEl.GetString() ?? ""
                : "";
            if (string.IsNullOrWhiteSpace(templateId))
            {
                continue;
            }

            if (SyntheticSourceOverrides.TryGetValue(templateId, out var overrideSrc))
            {
                SyntheticTemplateSources[templateId] = overrideSrc;
                continue;
            }

            var configuredMap = raw.TryGetProperty("source_map", out var srcMapEl)
                ? srcMapEl.GetString() ?? ""
                : "";
            var configuredEntity = raw.TryGetProperty("source_entity", out var srcEntityEl)
                ? srcEntityEl.GetString() ?? ""
                : "";
            if (IsValidDonorMapId(configuredMap) && !string.IsNullOrWhiteSpace(configuredEntity))
            {
                SyntheticTemplateSources[templateId] = new SyntheticTemplateSource(
                    configuredMap,
                    configuredEntity);
                continue;
            }

            var model = raw.TryGetProperty("model", out var modelEl)
                ? modelEl.GetString() ?? ""
                : "";
            if (string.IsNullOrWhiteSpace(model)
                || !indexByModel.TryGetValue(model, out var hits)
                || hits.Count == 0)
            {
                continue;
            }

            var best = hits
                .OrderByDescending(hit => hit.Rank)
                .ThenBy(hit => hit.MapId, StringComparer.OrdinalIgnoreCase)
                .ThenBy(hit => hit.EntityName, StringComparer.OrdinalIgnoreCase)
                .First();
            SyntheticTemplateSources[templateId] = new SyntheticTemplateSource(
                best.MapId,
                best.EntityName);
        }

        foreach (var kv in SyntheticSourceOverrides)
        {
            SyntheticTemplateSources.TryAdd(kv.Key, kv.Value);
        }

        Console.WriteLine($"apply-map: synthetic_sources={SyntheticTemplateSources.Count}");
        Console.Out.Flush();
    }

    static int ScoreSyntheticIndexSource(string mapId, string entityName)
    {
        var score = 0;
        if (entityName.Contains("_9000", StringComparison.OrdinalIgnoreCase))
        {
            score += 100;
        }

        if (mapId.StartsWith("m30_", StringComparison.OrdinalIgnoreCase)
            || mapId.StartsWith("m31_", StringComparison.OrdinalIgnoreCase)
            || mapId.StartsWith("m32_", StringComparison.OrdinalIgnoreCase)
            || mapId.StartsWith("m11_", StringComparison.OrdinalIgnoreCase)
            || mapId.StartsWith("m12_", StringComparison.OrdinalIgnoreCase)
            || mapId.StartsWith("m13_", StringComparison.OrdinalIgnoreCase)
            || mapId.StartsWith("m14_", StringComparison.OrdinalIgnoreCase)
            || mapId.StartsWith("m20_", StringComparison.OrdinalIgnoreCase)
            || mapId.StartsWith("m21_", StringComparison.OrdinalIgnoreCase)
            || mapId.StartsWith("m28_", StringComparison.OrdinalIgnoreCase)
            || mapId.StartsWith("m29_", StringComparison.OrdinalIgnoreCase)
            || mapId.StartsWith("m41_", StringComparison.OrdinalIgnoreCase)
            || mapId.StartsWith("m42_", StringComparison.OrdinalIgnoreCase)
            || mapId.StartsWith("m61_", StringComparison.OrdinalIgnoreCase))
        {
            score += 50;
        }

        if (mapId.StartsWith("m60_", StringComparison.OrdinalIgnoreCase))
        {
            score += 10;
        }

        return score;
    }

    static bool IsEnemyModelStub(MSBE.Model.Enemy model) =>
        GetEnemyModelInstanceCount(model) <= 0;

    static int GetEnemyModelInstanceCount(MSBE.Model.Enemy model)
    {
        var prop = model.GetType().GetProperty(
            "InstanceCount",
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)
            ?? typeof(MSBE.Model).GetProperty(
                "InstanceCount",
                BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
        if (prop?.GetValue(model) is int count)
        {
            return count;
        }

        return 0;
    }

    static bool TryReplaceEnemyModelOnMsb(MSBE msb, string modelName, MSBE.Model.Enemy replacement)
    {
        for (var i = 0; i < msb.Models.Enemies.Count; i++)
        {
            if (!string.Equals(msb.Models.Enemies[i].Name, modelName, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            msb.Models.Enemies[i] = (MSBE.Model.Enemy)replacement.DeepCopy();
            return true;
        }

        return false;
    }

    static void AddEnemyModelToMsb(
        MSBE msb,
        MSBE.Model.Enemy model,
        ISet<string>? mapModelNames)
    {
        msb.Models.Enemies.Add((MSBE.Model.Enemy)model.DeepCopy());
        if (mapModelNames?.Add(model.Name) == true)
        {
            MarkCnvMapModelIndexDirty();
        }
    }

    static string EnemyModelSibPath(string modelName) =>
        $@"N:\GR\data\Model\chr\{modelName}\sib\{modelName}.sib";

    static bool IsValidDonorMapId(string? mapId) =>
        !string.IsNullOrWhiteSpace(mapId)
        && !string.Equals(mapId, "synthetic", StringComparison.OrdinalIgnoreCase)
        && mapId.StartsWith("m", StringComparison.OrdinalIgnoreCase);

    static List<MSBE.Part.Enemy> FilterSoldiers(IList<MSBE.Part.Enemy> enemies, bool wagonOnly) =>

        enemies

            .Where(e => e.ModelName.StartsWith(SourceModel, StringComparison.OrdinalIgnoreCase))

            .Where(e => !wagonOnly || e.EntityGroupIDs.Contains(WagonGroupId))

            .OrderBy(e => e.Name, StringComparer.OrdinalIgnoreCase)

            .ThenBy(e => e.EntityID)

            .ToList();

    static string FormatEnemy(string label, MSBE.Part.Enemy e, bool includePos = false)

    {

        var pos = includePos ? $" pos=({e.Position.X:F0},{e.Position.Y:F0},{e.Position.Z:F0})" : "";

        return

            $"  {label} entity={e.EntityID} name={e.Name} model={e.ModelName} npc={e.NPCParamID} think={e.ThinkParamID} chara={e.CharaInitID}{pos} groups=[{string.Join(",", e.EntityGroupIDs)}]";

    }

    static string BuildManifest(

        List<PatchRecord> records,

        MsbLoadResult load,

        string outMsb,

        string outMsbe,

        int verifySentinelCount,

        int verifySoldierCount)

    {

        var sb = new StringBuilder();

        sb.AppendLine("# CNV enemy swap POC — offline MSB override (ME3 loads mod/ at runtime)");

        sb.AppendLine($"map={MapId}");

        sb.AppendLine($"patched_count={records.Count}");

        sb.AppendLine($"msb_source={load.SourcePath}");

        sb.AppendLine($"msb_source_sha256={load.Sha256}");

        sb.AppendLine($"output_msb={outMsb}");

        sb.AppendLine($"output_msbe={outMsbe}");

        sb.AppendLine($"verify_sentinel={verifySentinelCount} verify_remaining_soldier={verifySoldierCount}");

        sb.AppendLine("test=Gatefront — ALL Godrick soldiers should be Tree Sentinel");

        sb.AppendLine("launch=Use Start_Convergence.bat (ME3 + convergence.me3), not raw eldenring.exe");

        sb.AppendLine("rollback=Delete mod/map/MapStudio/m60_42_37_00.msb.dcx and .msbe.dcx");

        sb.AppendLine();

        foreach (var r in records)

        {

            sb.AppendLine(

                $"entity={r.EntityId} name={r.Name} pos=({r.PosX:F0},{r.PosY:F0},{r.PosZ:F0}) " +

                $"before={r.BeforeModel}/{r.BeforeNpc}/{r.BeforeThink} after={r.AfterModel}/{r.AfterNpc}/{r.AfterThink}");

        }



        return sb.ToString();

    }

    static void WriteDetailLog(StringBuilder detailLog, string phase)

    {

        var path = Path.Combine(ResolveToolRoot(), "enemy_poc_detail.txt");

        var header = $"=== enemy_poc_detail {phase} {DateTime.Now:u} ==={Environment.NewLine}";

        File.WriteAllText(path, header + detailLog, Encoding.UTF8);

    }

    static void Log(StringBuilder detailLog, string line) => detailLog.AppendLine(line);

    static MSBE ReadMsbe(byte[] fileBytes) => MSBE.Read(fileBytes);

    static byte[] WriteMsbe(MSBE msb) => msb.Write(MsbeWriteCompression(msb));

    static readonly (string SlotName, string DonorKey, string Note)[] Batch2Plan =
    {
        ("c4311_9006", "real_dragon", "马车旁空地 — 真龙（飞龙/桂雷尔）"),
        ("c4311_9022", "elden_beast", "林边 — 艾尔登之兽 c2200"),
        ("c4311_9004", "rune_trash", "卢恩对照 A — 矛兵级小怪"),
        ("c4311_9008", "rune_medium", "卢恩对照 B — 野狗级中怪"),
        ("c4311_9012", "rune_heavy", "卢恩对照 C — 大树守卫级"),
    };

    static int ExportEnemyIndex(string gameDir, string[] args, StringBuilder detailLog)
    {
        var outPath = ResolveIndexOutPath(args);
        var maxMaps = ResolveMaxMaps(args);
        var includeZeroNpc = ResolveIndexIncludeZeroNpc(args);
        var mapStudio = CnvMapStudioDir(gameDir);
        if (!Directory.Exists(mapStudio))
        {
            Console.Error.WriteLine($"Missing {mapStudio}");
            return 1;
        }

        var slots = new List<Dictionary<string, object?>>();
        var templates = new Dictionary<string, Dictionary<string, object?>>();
        var routesByMap = new Dictionary<string, List<string>>();
        var scanned = 0;
        var skipped = 0;
        var overworld = 0;
        var legacy = 0;
        var zeroNpcSkipped = 0;

        // 全图：野外 m60/m61 + 副本/神授塔等（上次只扫 m60_ 会漏神皮女组长等）
        foreach (var path in Directory.EnumerateFiles(mapStudio, "*.msb.dcx").OrderBy(p => p))
        {
            if (maxMaps > 0 && scanned >= maxMaps)
            {
                break;
            }

            MSBE msb;
            try
            {
                msb = ReadMsbe(File.ReadAllBytes(path));
            }
            catch (Exception ex)
            {
                skipped++;
                Log(detailLog, $"index_skip {Path.GetFileName(path)} {ex.Message}");
                continue;
            }

            scanned++;
            var mapId = Path.GetFileName(path).Replace(".msb.dcx", "", StringComparison.OrdinalIgnoreCase);
            if (mapId.StartsWith("m60_", StringComparison.OrdinalIgnoreCase)
                || mapId.StartsWith("m61_", StringComparison.OrdinalIgnoreCase))
            {
                overworld++;
            }
            else
            {
                legacy++;
            }

            var siegeMountRiders = IndexSiegeMountRiders(msb);
            var routeNames = new List<string>();
            foreach (var route in msb.Routes.GetEntries())
            {
                if (!string.IsNullOrWhiteSpace(route.Name))
                {
                    routeNames.Add(route.Name);
                }
            }
            routesByMap[mapId] = routeNames.OrderBy(n => n, StringComparer.OrdinalIgnoreCase).ToList();

            foreach (var enemy in msb.Parts.Enemies)
            {
                var model = enemy.ModelName ?? "";
                if (string.IsNullOrWhiteSpace(model))
                {
                    continue;
                }

                if (enemy.NPCParamID <= 0)
                {
                    if (!includeZeroNpc)
                    {
                        zeroNpcSkipped++;
                        continue;
                    }
                }

                var walkRoute = enemy.WalkRouteName ?? "";
                var slotRow = new Dictionary<string, object?>
                {
                    ["map_id"] = mapId,
                    ["name"] = enemy.Name,
                    ["model"] = model,
                    ["npc"] = enemy.NPCParamID,
                    ["think"] = enemy.ThinkParamID,
                    ["chara"] = enemy.CharaInitID,
                    ["entity_id"] = enemy.EntityID,
                    ["walk_route"] = walkRoute,
                    ["backup_anim"] = enemy.BackupEventAnimID,
                    ["talk_id"] = enemy.TalkID,
                    ["chr_activate"] = enemy.ChrActivateCondParamID,
                    ["collision_part"] = enemy.CollisionPartName ?? "",
                    ["platoon_id"] = enemy.PlatoonID,
                    ["unk_t15"] = enemy.UnkT15,
                    ["rot_x"] = enemy.Rotation.X,
                    ["rot_y"] = enemy.Rotation.Y,
                    ["rot_z"] = enemy.Rotation.Z,
                    ["entity_groups"] = enemy.EntityGroupIDs?.ToArray() ?? Array.Empty<uint>(),
                    ["sp_effect_set"] = enemy.SpEffectSetParamID?.ToArray() ?? Array.Empty<int>(),
                    ["pos_x"] = enemy.Position.X,
                    ["pos_y"] = enemy.Position.Y,
                    ["pos_z"] = enemy.Position.Z,
                };
                if (enemy.NPCParamID <= 0)
                {
                    slotRow["is_zero_npc"] = true;
                }
                if (siegeMountRiders.TryGetValue(enemy.Name, out var siegeWeapon))
                {
                    slotRow["siege_mount_rider"] = true;
                    slotRow["siege_mount_weapon"] = siegeWeapon;
                }

                slots.Add(slotRow);

                var templateId = $"{mapId}:{enemy.Name}";
                if (templates.ContainsKey(templateId))
                {
                    continue;
                }

                templates[templateId] = new Dictionary<string, object?>
                {
                    ["template_id"] = templateId,
                    ["donor_map"] = $"{mapId}.msb.dcx",
                    ["donor_entity"] = enemy.Name,
                    ["model"] = model,
                    ["npc"] = enemy.NPCParamID,
                    ["think"] = enemy.ThinkParamID,
                    ["chara"] = enemy.CharaInitID,
                    ["walk_route"] = walkRoute,
                    ["backup_anim"] = enemy.BackupEventAnimID,
                    ["talk_id"] = enemy.TalkID,
                    ["chr_activate"] = enemy.ChrActivateCondParamID,
                    ["collision_part"] = enemy.CollisionPartName ?? "",
                    ["platoon_id"] = enemy.PlatoonID,
                    ["unk_t15"] = enemy.UnkT15,
                    ["rot_x"] = enemy.Rotation.X,
                    ["rot_y"] = enemy.Rotation.Y,
                    ["rot_z"] = enemy.Rotation.Z,
                    ["entity_groups"] = enemy.EntityGroupIDs?.ToArray() ?? Array.Empty<uint>(),
                    ["sp_effect_set"] = enemy.SpEffectSetParamID?.ToArray() ?? Array.Empty<int>(),
                    ["pos_x"] = enemy.Position.X,
                    ["pos_y"] = enemy.Position.Y,
                    ["pos_z"] = enemy.Position.Z,
                };
            }
        }

        var payload = new Dictionary<string, object?>
        {
            ["schema"] = "enemy_index_v2",
            ["maps_scanned"] = scanned,
            ["maps_skipped"] = skipped,
            ["maps_overworld"] = overworld,
            ["maps_legacy"] = legacy,
            ["zero_npc_slots_skipped"] = zeroNpcSkipped,
            ["routes_by_map"] = routesByMap,
            ["slots"] = slots,
            ["templates"] = templates.Values.ToList(),
        };

        Directory.CreateDirectory(Path.GetDirectoryName(outPath)!);
        File.WriteAllText(
            outPath,
            JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }),
            Encoding.UTF8);
        Console.WriteLine(
            $"index-export maps={scanned} overworld={overworld} legacy={legacy} skip={skipped} "
            + $"slots={slots.Count} templates={templates.Count}");
        Console.WriteLine($"Wrote {outPath}");
        Log(
            detailLog,
            $"index_export={outPath} maps={scanned} overworld={overworld} legacy={legacy} slots={slots.Count}");
        WriteDetailLog(detailLog, "index-export");
        return 0;
    }

    static bool ResolveIndexIncludeZeroNpc(string[] args) =>
        args.Any(arg => string.Equals(arg, "--include-zero-npc", StringComparison.OrdinalIgnoreCase));

    static int ExportPickupIndex(string gameDir, string[] args, StringBuilder detailLog)
    {
        var outPath = ResolvePickupIndexOutPath(args);
        var maxMaps = ResolveMaxMaps(args);
        var mapStudio = CnvMapStudioDir(gameDir);
        if (!Directory.Exists(mapStudio))
        {
            Console.Error.WriteLine($"Missing {mapStudio}");
            return 1;
        }

        var placements = new List<Dictionary<string, object?>>();
        var scanned = 0;
        var skipped = 0;
        var treasureEvents = 0;

        foreach (var path in Directory.EnumerateFiles(mapStudio, "*.msb.dcx").OrderBy(p => p))
        {
            if (maxMaps > 0 && scanned >= maxMaps)
            {
                break;
            }

            MSBE msb;
            try
            {
                msb = ReadMsbe(File.ReadAllBytes(path));
            }
            catch (Exception ex)
            {
                skipped++;
                Log(detailLog, $"pickup_index_skip {Path.GetFileName(path)} {ex.Message}");
                continue;
            }

            scanned++;
            var mapId = Path.GetFileName(path).Replace(".msb.dcx", "", StringComparison.OrdinalIgnoreCase);

            foreach (var treasure in msb.Events.Treasures)
            {
                var lotId = treasure.ItemLotID;
                if (lotId <= 0)
                {
                    continue;
                }

                treasureEvents++;
                var treasurePart = treasure.TreasurePartName ?? "";
                var entityKey = !string.IsNullOrWhiteSpace(treasurePart)
                    ? treasurePart
                    : (treasure.Name ?? $"lot_{lotId}");
                placements.Add(new Dictionary<string, object?>
                {
                    ["map_id"] = mapId,
                    ["entity"] = entityKey,
                    ["name"] = treasure.Name ?? "",
                    ["entity_id"] = treasure.EntityID,
                    ["event_id"] = treasure.EventID,
                    ["lot_id"] = lotId,
                    ["treasure_part"] = treasurePart,
                    ["in_chest"] = treasure.InChest,
                    ["placement_kind"] = "treasure",
                });
            }
        }

        var payload = new Dictionary<string, object?>
        {
            ["version"] = 1,
            ["generated_at"] = DateTime.UtcNow.ToString("o"),
            ["maps_scanned"] = scanned,
            ["maps_skipped"] = skipped,
            ["treasure_events"] = treasureEvents,
            ["placements"] = placements,
        };

        Directory.CreateDirectory(Path.GetDirectoryName(outPath)!);
        File.WriteAllText(
            outPath,
            JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }),
            Encoding.UTF8);
        Console.WriteLine(
            $"pickup-index-export maps={scanned} skip={skipped} treasures={treasureEvents} "
            + $"placements={placements.Count}");
        Console.WriteLine($"Wrote {outPath}");
        Log(
            detailLog,
            $"pickup_index_export={outPath} maps={scanned} skip={skipped} treasures={treasureEvents}");
        WriteDetailLog(detailLog, "pickup-index-export");
        return 0;
    }

    static Dictionary<string, (string MapFile, MSBE.Model.Enemy Model)> BuildEnemyModelRegistry(
        string gameDir,
        int parallel,
        ConcurrentBag<string> logLines,
        IReadOnlyList<string>? mapFilesFilter = null)
    {
        var mapStudio = CnvMapStudioDir(gameDir);
        if (!Directory.Exists(mapStudio))
        {
            ModelRegistryScopedToSpawn = false;
            return new Dictionary<string, (string, MSBE.Model.Enemy)>(StringComparer.OrdinalIgnoreCase);
        }

        var fingerprint = ComputeMapStudioFingerprint(mapStudio);
        var cachePath = ModelRegistryCachePath();
        if (TryLoadModelRegistryCache(cachePath, fingerprint, gameDir, out var cached))
        {
            ModelRegistryScopedToSpawn = mapFilesFilter is { Count: > 0 };
            Console.WriteLine($"apply-map: model registry cache hit ({cached.Count} entries)");
            Console.Out.Flush();
            return cached;
        }

        var registry = new ConcurrentDictionary<string, (string, MSBE.Model.Enemy)>(
            StringComparer.OrdinalIgnoreCase);
        List<string> files;
        if (mapFilesFilter is { Count: > 0 })
        {
            files = mapFilesFilter
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .OrderBy(f => f, StringComparer.OrdinalIgnoreCase)
                .ToList();
            ModelRegistryScopedToSpawn = true;
        }
        else
        {
            files = Directory.EnumerateFiles(mapStudio, "*.msb.dcx").ToList();
            ModelRegistryScopedToSpawn = false;
        }

        var totalFiles = files.Count;
        var scanned = 0;
        Parallel.ForEach(
            files,
            new ParallelOptions { MaxDegreeOfParallelism = parallel },
            path =>
            {
                var fileName = Path.GetFileName(path);
                var msb = TryReadMsbSafe(gameDir, fileName, new StringBuilder());
                if (msb != null)
                {
                    foreach (var model in msb.Models.Enemies)
                    {
                        if (model is MSBE.Model.Enemy enemyModel)
                        {
                            registry.TryAdd(enemyModel.Name, (fileName, enemyModel));
                        }
                    }
                }

                var n = Interlocked.Increment(ref scanned);
                if (n == 1 || n == totalFiles || n % 25 == 0)
                {
                    Console.WriteLine($"apply-map: registry_progress {n}/{totalFiles}");
                    Console.Out.Flush();
                }
            });

        var dict = registry.ToDictionary(kv => kv.Key, kv => kv.Value, StringComparer.OrdinalIgnoreCase);
        TrySaveModelRegistryCache(cachePath, fingerprint, dict);
        return dict;
    }

    static Dictionary<string, MSBE.Part.Enemy> BuildEnemyLookupByName(
        IList<MSBE.Part.Enemy> enemies,
        string mapId,
        StringBuilder detailLog,
        MapApplyResult result)
    {
        var lookup = new Dictionary<string, MSBE.Part.Enemy>(StringComparer.OrdinalIgnoreCase);
        foreach (var enemy in enemies)
        {
            if (lookup.ContainsKey(enemy.Name))
            {
                result.LogLines.Add($"apply_duplicate_enemy_name={mapId}:{enemy.Name}");
                Log(detailLog, $"duplicate_enemy_name={enemy.Name} map={mapId}");
                continue;
            }

            lookup[enemy.Name] = enemy;
        }

        return lookup;
    }

    const string RadahnHelperDonorMap = "m60_52_38_00.msb.dcx";
    const uint RadahnHelperDonorEntityId = 1052380899u;

    static MSBE.Part.Enemy? RadahnHelperTemplate;

    static bool IsRadahnDonorModel(string? model) =>
        !string.IsNullOrWhiteSpace(model)
        && model.StartsWith("c4730", StringComparison.OrdinalIgnoreCase);

    static MSBE.Part.Enemy? ResolveRadahnHelperTemplate(string gameDir, StringBuilder detailLog)
    {
        if (RadahnHelperTemplate != null)
        {
            return RadahnHelperTemplate;
        }

        var donorMsb = TryReadMsbSafe(gameDir, RadahnHelperDonorMap, detailLog);
        if (donorMsb == null)
        {
            Log(detailLog, "radahn_helper_template=missing_msb");
            return null;
        }

        var helper = donorMsb.Parts.Enemies.FirstOrDefault(e => e.EntityID == RadahnHelperDonorEntityId)
            ?? donorMsb.Parts.Enemies.FirstOrDefault(
                e => e.Name.Contains("9009", StringComparison.OrdinalIgnoreCase)
                    && string.Equals(e.ModelName, "c0000", StringComparison.OrdinalIgnoreCase))
            ?? donorMsb.Parts.Enemies.FirstOrDefault(
                e => string.Equals(e.ModelName, "c0000", StringComparison.OrdinalIgnoreCase)
                    && e.NPCParamID == 0
                    && e.ThinkParamID == 0);
        if (helper == null)
        {
            Log(detailLog, "radahn_helper_template=stub_c0000");
            RadahnHelperTemplate = new MSBE.Part.Enemy
            {
                Name = "cnv_radahn_helper_stub",
                ModelName = "c0000",
                NPCParamID = 0,
                ThinkParamID = 0,
                CharaInitID = -1,
            };
            return RadahnHelperTemplate;
        }

        RadahnHelperTemplate = helper;
        Log(detailLog, $"radahn_helper_template=ok entity={helper.EntityID} name={helper.Name}");
        return helper;
    }

    static uint PickRadahnHelperEntityId(MSBE msb, uint bossEntityId)
    {
        var used = new HashSet<uint>(msb.Parts.Enemies.Select(e => e.EntityID));
        for (uint off = 99; off < 600; off++)
        {
            var candidate = bossEntityId + off;
            if (!used.Contains(candidate))
            {
                return candidate;
            }
        }

        return bossEntityId + 9000u;
    }

    static Dictionary<(string MapId, string Name), uint>? RadahnEntityIndex;

    static uint ResolveBossEntityIdFromIndex(string mapId, string slotName, StringBuilder detailLog)
    {
        try
        {
            RadahnEntityIndex ??= LoadEnemySlotEntityIndex();
            if (RadahnEntityIndex.TryGetValue((mapId, slotName), out var entityId) && entityId > 0)
            {
                Log(detailLog, $"radahn_entity_index map={mapId} slot={slotName} entity={entityId}");
                return entityId;
            }
        }
        catch (Exception ex)
        {
            Log(detailLog, $"radahn_entity_index_error map={mapId} slot={slotName} {ex.Message}");
        }

        return 0;
    }

    static Dictionary<(string MapId, string Name), uint> LoadEnemySlotEntityIndex()
    {
        var lookup = new Dictionary<(string, string), uint>();
        var path = Path.Combine(ResolveRingrandomRoot(), "cnv_randomizer", "cache", "enemy_index.json");
        if (!File.Exists(path))
        {
            return lookup;
        }

        using var doc = JsonDocument.Parse(File.ReadAllText(path, Encoding.UTF8));
        if (!doc.RootElement.TryGetProperty("slots", out var slots)
            || slots.ValueKind != JsonValueKind.Array)
        {
            return lookup;
        }

        foreach (var slot in slots.EnumerateArray())
        {
            var mapId = slot.TryGetProperty("map_id", out var mapEl) ? mapEl.GetString() ?? "" : "";
            var name = slot.TryGetProperty("name", out var nameEl) ? nameEl.GetString() ?? "" : "";
            if (string.IsNullOrWhiteSpace(mapId) || string.IsNullOrWhiteSpace(name))
            {
                continue;
            }

            if (!slot.TryGetProperty("entity_id", out var entityEl))
            {
                continue;
            }

            uint entityId = entityEl.ValueKind switch
            {
                JsonValueKind.Number when entityEl.TryGetUInt32(out var u) => u,
                JsonValueKind.Number => (uint)entityEl.GetInt64(),
                _ => 0u,
            };
            if (entityId > 0)
            {
                lookup[(mapId, name)] = entityId;
            }
        }

        return lookup;
    }

    static List<MSBE.Part.Enemy>? TryReadMapEnemies(string gameDir, string mapFileName, StringBuilder detailLog)
    {
        var bytes = TryReadMapBytes(gameDir, mapFileName, detailLog);
        if (bytes == null)
        {
            return null;
        }

        try
        {
            return ReadMsbe(bytes).Parts.Enemies.ToList();
        }
        catch (Exception ex)
        {
            Log(detailLog, $"map_parse_fail {mapFileName}: {ex.Message}");
            return null;
        }
    }

    static Dictionary<string, MSBE.Part.Enemy> GetDonorEnemyIndex(
        string gameDir,
        string mapFile,
        StringBuilder detailLog)
    {
        return DonorEnemyByMapCache.GetOrAdd(
            mapFile,
            _ =>
            {
                var index = new Dictionary<string, MSBE.Part.Enemy>(StringComparer.OrdinalIgnoreCase);
                var enemies = TryReadMapEnemies(gameDir, mapFile, detailLog);
                if (enemies == null)
                {
                    return index;
                }

                foreach (var enemy in enemies)
                {
                    var name = enemy.Name ?? "";
                    if (!string.IsNullOrWhiteSpace(name) && !index.ContainsKey(name))
                    {
                        index[name] = enemy;
                    }
                }

                return index;
            });
    }

    static string Sha256Hex(byte[] data)

    {

        var hash = SHA256.HashData(data);

        return Convert.ToHexString(hash).ToLowerInvariant();

    }

    static int VerifyParams(string csvDir, StringBuilder detailLog)

    {

        Console.WriteLine($"CSV dir: {csvDir}");

        Log(detailLog, $"csv_dir={csvDir}");

        if (!Directory.Exists(csvDir))

        {

            Console.Error.WriteLine("Missing csv dir — export regulation.bin to Game\\csv first.");

            return 1;

        }



        var npc = Path.Combine(csvDir, "NpcParam.csv");

        var think = Path.Combine(csvDir, "NpcThinkParam.csv");

        foreach (var path in new[] { npc, think })

        {

            if (!File.Exists(path))

            {

                Console.Error.WriteLine($"Missing {path}");

                return 1;

            }

        }



        PrintParamRow(npc, SourceNpcParam, "source soldier");

        PrintParamRow(npc, TargetNpcParam, "target Tree Sentinel");

        PrintParamRow(think, TargetThinkParam, "target think");

        PrintParamRow(think, SourceNpcParam, "source think (if present)");



        Console.WriteLine();

        Console.WriteLine("Param IDs look good for transplant (model/npc/think on MSB entity).");

        Console.WriteLine("CSV/regulation does NOT list map entity slots — still need MSB for list/patch:");

        Console.WriteLine("  tools\\cnv_enemy_poc\\cache\\m60_42_37_00.msbe.dcx  (Smithbox export once)");

        WriteDetailLog(detailLog, "verify");

        return 0;

    }

    static void PrintParamRow(string csvPath, int id, string label)

    {

        foreach (var line in File.ReadLines(csvPath))

        {

            if (!line.StartsWith($"{id},", StringComparison.Ordinal))

            {

                continue;

            }



            var parts = line.Split(',');

            var name = parts.Length > 1 ? parts[1] : line;

            Console.WriteLine($"  [{label}] {id} = {name}");

            return;

        }



        Console.WriteLine($"  [{label}] {id} = (not found in {Path.GetFileName(csvPath)})");

    }

    static MsbLoadResult LoadMap(string gameDir, string relPath, string? msbOverride, StringBuilder detailLog)

    {

        if (!string.IsNullOrWhiteSpace(msbOverride) && File.Exists(msbOverride))

        {

            var bytes = File.ReadAllBytes(msbOverride);

            Console.WriteLine($"Loading cached MSB {msbOverride}");

            Log(detailLog, $"load_pick=--msb override");

            return new MsbLoadResult(bytes, msbOverride, Sha256Hex(bytes));

        }



        var cached = FindCachedMsb();
        if (cached != null && File.Exists(cached))
        {
            if (!cached.Contains(MapId, StringComparison.OrdinalIgnoreCase))
            {
                Console.Error.WriteLine($"WARNING: cached MSB map id mismatch (need {MapId}): {cached}");
                Log(detailLog, $"WARNING=cache_map_id_mismatch path={cached}");
            }

            var bytes = File.ReadAllBytes(cached);
            Console.WriteLine($"Loading cached MSB {cached}");
            Log(detailLog, $"load_pick=tool cache (list/verify only — patch uses CNV mod MSB)");
            return new MsbLoadResult(bytes, cached, Sha256Hex(bytes));
        }



        try

        {

            var hash = HashHelper.FromPathHash(relPath);

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



                        var bytes = header.ReadFile(bdt);

                        var source = $"{relPath} from {bhdName}";

                        Console.WriteLine($"Loading {source}");

                        Log(detailLog, $"load_pick=bhd {bhdName}");

                        return new MsbLoadResult(bytes, source, Sha256Hex(bytes));

                    }

                }

            }

        }

        catch (Exception ex)

        {

            Console.Error.WriteLine($"BHD read failed ({ex.Message}).");

            Log(detailLog, $"bhd_error={ex.Message}");

        }



        throw new FileNotFoundException(

            $"""

            Could not load {relPath}.

            Smithbox File Browser:

              mapstudio -> select m60_42_37_00.msbe.dcx  (42 not 43!)

              Extract Main File -> cnv_enemy_poc/cache/

            Common mistakes:

              - wrong map: m60_43_37_00 is NOT Gatefront (need m60_42_37_00)

              - nested path cache/map/mapstudio/... is OK after tool fix

            Or pass: --msb="full\\path\\to\\m60_42_37_00.msbe.dcx"

            """);

    }

    sealed class PatchRecord

    {

        public string Name { get; set; } = "";

        public uint EntityId { get; set; }

        public float PosX { get; set; }

        public float PosY { get; set; }

        public float PosZ { get; set; }

        public string Groups { get; set; } = "";

        public string BeforeModel { get; set; } = "";

        public int BeforeNpc { get; set; }

        public int BeforeThink { get; set; }

        public int BeforeChara { get; set; }

        public int BeforeBackupAnim { get; set; }

        public string BeforeWalkRoute { get; set; } = "";

        public string BeforeCollision { get; set; } = "";

        public string AfterModel { get; set; } = "";

        public int AfterNpc { get; set; }

        public int AfterThink { get; set; }

        public int AfterChara { get; set; }

        public int AfterBackupAnim { get; set; }

        public string AfterWalkRoute { get; set; } = "";

        public string AfterCollision { get; set; } = "";

        public bool SitCleared { get; set; }

        public bool RouteCleared { get; set; }

        public bool SpeffectCleared { get; set; }

        public bool SlotStateCleared { get; set; }

        public bool ForceDonorMsb { get; set; }

        public bool WalkRouteKept { get; set; }

    }

    sealed class MsbLoadResult

    {

        public MsbLoadResult(byte[] bytes, string sourcePath, string sha256)

        {

            Bytes = bytes;

            SourcePath = sourcePath;

            Sha256 = sha256;

        }



        public byte[] Bytes { get; }

        public string SourcePath { get; }

        public string Sha256 { get; }

    }

    static MSBE.Part.Enemy? FindEnemyPartEntry(string gameDir, string modelName, StringBuilder detailLog)
    {
        var mapStudio = CnvMapStudioDir(gameDir);
        foreach (var fileName in new[] { "m60_42_36_00.msb.dcx", "m60_41_51_00.msb.dcx" })
        {
            var path = Path.Combine(mapStudio, fileName);
            if (!File.Exists(path))
            {
                continue;
            }

            var donor = ReadMsbe(File.ReadAllBytes(path));
            var part = donor.Parts.Enemies.FirstOrDefault(e => e.ModelName.StartsWith(modelName, StringComparison.OrdinalIgnoreCase));
            if (part != null)
            {
                Log(detailLog, $"state_ref_map={path} state_ref_name={part.Name}");
                return part;
            }
        }

        return null;
    }

}

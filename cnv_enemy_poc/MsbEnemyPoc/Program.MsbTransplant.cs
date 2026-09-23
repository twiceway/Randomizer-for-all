using System.Text;
using System.Text.Json;
using SoulsFormats;

static partial class Program
{
    sealed class Slot428TagEntry
    {
        public bool ClearSpeffectSet { get; set; }
        public bool ClearWalkRoute { get; set; }
        public string? SetCollision { get; set; }
    }

    static string? NormalizeTemplateId(string? templateId)
    {
        if (string.IsNullOrWhiteSpace(templateId))
        {
            return null;
        }

        var demountIdx = templateId.IndexOf("|demount", StringComparison.OrdinalIgnoreCase);
        return demountIdx >= 0 ? templateId[..demountIdx] : templateId;
    }

    static readonly string[] ScriptedFlyerSlotPrefixes =
    {
        "c4980", // Death Rite Bird
        "c6260", // DLC Death Rite Bird
    };

    static readonly string[] ScriptPatrolFlyerSlotPrefixes =
    {
        "c4200", // Man-Bat ledge script patrol (Gatefront)
    };

    static Dictionary<string, bool> DonorForceMsbByTemplate =
        new(StringComparer.OrdinalIgnoreCase);

    sealed class DonorSlotCompatEntry
    {
        public bool ForceDonorMsb { get; set; }
        public bool CompatPatrolKeep { get; set; } = true;
        public string DonorPoseLabel { get; set; } = "";
        public string DonorWalkRoute { get; set; } = "";
        public string VanillaScanModel { get; set; } = "";
    }

    static Dictionary<string, DonorSlotCompatEntry> DonorSlotCompatByTemplate =
        new(StringComparer.OrdinalIgnoreCase);

    static Dictionary<string, string> TestMapApplyModesByMapId =
        new(StringComparer.OrdinalIgnoreCase);

    static bool IsScriptedFlyerSlotModel(string? modelName)
    {
        if (string.IsNullOrWhiteSpace(modelName))
        {
            return false;
        }

        var model = modelName.ToLowerInvariant();
        return ScriptedFlyerSlotPrefixes.Any(p => model.StartsWith(p, StringComparison.Ordinal));
    }


    static Dictionary<string, Slot428TagEntry> Slot428TagsByKey =
        new(StringComparer.OrdinalIgnoreCase);

    static HashSet<string> DonorHiddenByTemplate =
        new(StringComparer.OrdinalIgnoreCase);

    static void LoadApplySlot428Tags()
    {
        Slot428TagsByKey = new Dictionary<string, Slot428TagEntry>(StringComparer.OrdinalIgnoreCase);
        DonorHiddenByTemplate = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var path = Path.Combine(
            ResolveRingrandomRoot(),
            "cnv_randomizer",
            "apply_slot_428_tags.json");
        if (!File.Exists(path))
        {
            return;
        }

        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(path, Encoding.UTF8));
            if (doc.RootElement.TryGetProperty("slot_tags", out var slotTags))
            {
                foreach (var prop in slotTags.EnumerateObject())
                {
                    var entry = new Slot428TagEntry();
                    if (prop.Value.TryGetProperty("clear_speffect_set", out var spEl)
                        && spEl.ValueKind == JsonValueKind.True)
                    {
                        entry.ClearSpeffectSet = true;
                    }

                    if (prop.Value.TryGetProperty("clear_walk_route", out var routeEl)
                        && routeEl.ValueKind == JsonValueKind.True)
                    {
                        entry.ClearWalkRoute = true;
                    }

                    if (prop.Value.TryGetProperty("set_collision", out var colEl)
                        && colEl.ValueKind == JsonValueKind.String)
                    {
                        entry.SetCollision = colEl.GetString();
                    }

                    Slot428TagsByKey[prop.Name] = entry;
                }
            }

            if (doc.RootElement.TryGetProperty("donor_tags", out var donorTags))
            {
                foreach (var prop in donorTags.EnumerateObject())
                {
                    if (prop.Value.TryGetProperty("hidden", out var hiddenEl)
                        && hiddenEl.ValueKind == JsonValueKind.True)
                    {
                        DonorHiddenByTemplate.Add(prop.Name);
                    }
                }
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"apply-map: apply_slot_428_tags load failed ({ex.Message})");
        }
    }

    static bool ResolveDonorHidden(string? templateId)
    {
        var tid = NormalizeTemplateId(templateId);
        return tid != null && DonorHiddenByTemplate.Contains(tid);
    }

    static void ApplySlot428Tags(
        MSBE.Part.Enemy target,
        PatchRecord record,
        string? mapId,
        string? entityName,
        IReadOnlySet<string>? validCollisionParts = null)
    {
        if (string.IsNullOrWhiteSpace(mapId) || string.IsNullOrWhiteSpace(entityName))
        {
            return;
        }

        var key = $"{mapId}:{entityName}";
        if (!Slot428TagsByKey.TryGetValue(key, out var tags))
        {
            return;
        }

        if (tags.ClearSpeffectSet
            && target.SpEffectSetParamID != null
            && target.SpEffectSetParamID.Length > 0
            && target.SpEffectSetParamID[0] != 0)
        {
            target.SpEffectSetParamID[0] = 0;
            record.SpeffectCleared = true;
            record.SlotStateCleared = true;
        }

        if (tags.ClearWalkRoute && !string.IsNullOrWhiteSpace(target.WalkRouteName))
        {
            target.WalkRouteName = "";
            record.RouteCleared = true;
            record.SlotStateCleared = true;
        }

        if (!string.IsNullOrWhiteSpace(tags.SetCollision))
        {
            if (validCollisionParts != null
                && !validCollisionParts.Contains(tags.SetCollision))
            {
                return;
            }

            record.BeforeCollision = target.CollisionPartName ?? "";
            target.CollisionPartName = tags.SetCollision;
            record.SlotStateCleared = true;
        }
    }

    static void LoadDonorSlotCompatCache()
    {
        DonorForceMsbByTemplate = new Dictionary<string, bool>(StringComparer.OrdinalIgnoreCase);
        DonorSlotCompatByTemplate = new Dictionary<string, DonorSlotCompatEntry>(StringComparer.OrdinalIgnoreCase);
        var path = Path.Combine(
            ResolveRingrandomRoot(),
            "cnv_randomizer",
            "cache",
            "donor_slot_compat.json");
        if (!File.Exists(path))
        {
            return;
        }

        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(path, Encoding.UTF8));
            if (!doc.RootElement.TryGetProperty("templates", out var templates))
            {
                return;
            }

            foreach (var prop in templates.EnumerateObject())
            {
                var entry = new DonorSlotCompatEntry();
                if (prop.Value.TryGetProperty("force_donor_msb", out var forceEl)
                    && forceEl.ValueKind == JsonValueKind.True)
                {
                    entry.ForceDonorMsb = true;
                    DonorForceMsbByTemplate[prop.Name] = true;
                }

                if (prop.Value.TryGetProperty("compat_patrol_keep", out var patrolEl)
                    && patrolEl.ValueKind == JsonValueKind.False)
                {
                    entry.CompatPatrolKeep = false;
                }

                if (prop.Value.TryGetProperty("donor_pose_label", out var poseEl)
                    && poseEl.ValueKind == JsonValueKind.String)
                {
                    entry.DonorPoseLabel = poseEl.GetString() ?? "";
                }

                if (prop.Value.TryGetProperty("donor_walk_route", out var walkEl)
                    && walkEl.ValueKind == JsonValueKind.String)
                {
                    entry.DonorWalkRoute = walkEl.GetString() ?? "";
                }

                if (prop.Value.TryGetProperty("vanilla_scan_model", out var modelEl)
                    && modelEl.ValueKind == JsonValueKind.String)
                {
                    entry.VanillaScanModel = modelEl.GetString() ?? "";
                }

                DonorSlotCompatByTemplate[prop.Name] = entry;
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"apply-map: donor_slot_compat load failed ({ex.Message})");
        }
    }

    static bool TryGetDonorSlotCompatEntry(
        string? templateId,
        out DonorSlotCompatEntry entry)
    {
        entry = new DonorSlotCompatEntry();
        var tid = NormalizeTemplateId(templateId);
        if (tid == null)
        {
            return false;
        }

        if (DonorSlotCompatByTemplate.TryGetValue(tid, out var found))
        {
            entry = found;
            return true;
        }

        return false;
    }

    static string ResolveSlotApplyClass(MSBE.Part.Enemy enemy)
    {
        if (!string.IsNullOrWhiteSpace(enemy.WalkRouteName))
        {
            return "patrol_keep_initial";
        }

        if (IsStandingSlot(enemy))
        {
            return "standing_keep_initial";
        }

        return "other_use_donor_behavior";
    }

    static bool IsStandingSlot(MSBE.Part.Enemy enemy)
    {
        if (!string.IsNullOrWhiteSpace(enemy.WalkRouteName))
        {
            return false;
        }

        if (IsScriptedFlyerSlotModel(enemy.ModelName) || IsAerialSlotModel(enemy.ModelName))
        {
            return false;
        }

        if (enemy.BackupEventAnimID > 0)
        {
            return false;
        }

        if (enemy.ChrActivateCondParamID != 0)
        {
            return false;
        }

        var collision = enemy.CollisionPartName ?? "";
        if (!string.IsNullOrWhiteSpace(collision)
            && !IsPerchSlotModel(enemy.ModelName)
            && !IsDecorativeCorpseSlotModel(enemy.ModelName))
        {
            return false;
        }

        return true;
    }

    // T-086: pairing no longer rejects on force_donor (historical gate is pick-side).
    // Apply auto-opens force for script-class slots via ResolveForceDonorMsbOrAuto.
    static bool TryGetSlotCompatRejectReason(
        MSBE.Part.Enemy target,
        string? templateId,
        out string reason)
    {
        reason = "";
        _ = target;
        _ = templateId;
        return false;
    }

    static bool ResolveForceDonorMsbOrAuto(MSBE.Part.Enemy target, string? templateId)
    {
        if (ResolveForceDonorMsb(templateId))
        {
            return true;
        }

        // T-086：脚本/碰撞激活类槽写出自动开 force（配对阶段已不再因缺 force 拒皮）
        var slotClass = ResolveSlotApplyClass(target);
        return string.Equals(slotClass, "other_use_donor_behavior", StringComparison.Ordinal);
    }

    static bool IsScriptPatrolFlyerSlotModel(string? modelName) =>
        !string.IsNullOrWhiteSpace(modelName)
        && ScriptPatrolFlyerSlotPrefixes.Any(
            p => modelName.StartsWith(p, StringComparison.OrdinalIgnoreCase));

    static bool IsFlyingDonorModel(string? modelName)
    {
        if (string.IsNullOrWhiteSpace(modelName))
        {
            return false;
        }

        var model = modelName.ToLowerInvariant();
        if (ScriptPatrolFlyerSlotPrefixes.Any(p => model.StartsWith(p, StringComparison.Ordinal)))
        {
            return true;
        }

        return IsAerialSlotModel(modelName) || IsScriptedFlyerSlotModel(modelName);
    }

    static bool CollisionScriptSlotAllowsStandingSwap(
        MSBE.Part.Enemy target,
        DonorSlotCompatEntry entry)
    {
        if (target.ChrActivateCondParamID == 0)
        {
            return false;
        }

        if (!string.IsNullOrWhiteSpace(target.WalkRouteName))
        {
            return false;
        }

        if (string.IsNullOrWhiteSpace(target.CollisionPartName))
        {
            return false;
        }

        var slotModel = (target.ModelName ?? "").ToLowerInvariant();
        var donorModel = (entry.VanillaScanModel ?? "").ToLowerInvariant();
        if (string.IsNullOrWhiteSpace(slotModel) || string.IsNullOrWhiteSpace(donorModel))
        {
            return false;
        }

        if (string.Equals(slotModel, donorModel, StringComparison.Ordinal))
        {
            return true;
        }

        if (IsScriptPatrolFlyerSlotModel(target.ModelName))
        {
            return IsFlyingDonorModel(entry.VanillaScanModel);
        }

        return false;
    }

    static bool ResolveForceDonorMsb(string? templateId)
    {
        var tid = NormalizeTemplateId(templateId);
        return tid != null && DonorForceMsbByTemplate.TryGetValue(tid, out var force) && force;
    }

    static void LoadTestMapApplyModes()
    {
        TestMapApplyModesByMapId = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var path = Path.Combine(
            ResolveRingrandomRoot(),
            "cnv_randomizer",
            "test_map_apply_modes.json");
        if (!File.Exists(path))
        {
            return;
        }

        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(path, Encoding.UTF8));
            if (!doc.RootElement.TryGetProperty("maps", out var maps)
                || maps.ValueKind != JsonValueKind.Object)
            {
                return;
            }

            foreach (var prop in maps.EnumerateObject())
            {
                if (prop.Value.ValueKind == JsonValueKind.String)
                {
                    TestMapApplyModesByMapId[prop.Name] = prop.Value.GetString() ?? "";
                }
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"apply-map: test_map_apply_modes load failed ({ex.Message})");
        }
    }

    static bool IsDonorFullMsbTestMap(string? mapId) =>
        !string.IsNullOrWhiteSpace(mapId)
        && TestMapApplyModesByMapId.TryGetValue(mapId, out var mode)
        && string.Equals(mode, "donor_full_msb", StringComparison.OrdinalIgnoreCase);

    /// <summary>
    /// T-075 真机探针：清原槽 MSB 脚本，出场行为跟捐皮出处；巡逻槽仍留本图 WalkRoute。
    /// </summary>
    static void ApplyDonorFullMsbTestBehavior(
        MSBE.Part.Enemy target,
        MSBE.Part.Enemy? donorBehaviorRef,
        PatchRecord record)
    {
        var savedWalkRoute = target.WalkRouteName ?? "";
        ApplyNeutralDonorDefaults(target, record);
        if (!string.IsNullOrWhiteSpace(savedWalkRoute))
        {
            target.WalkRouteName = savedWalkRoute;
            record.RouteCleared = false;
            record.AfterWalkRoute = savedWalkRoute;
        }

        record.ForceDonorMsb = true;
        if (donorBehaviorRef != null)
        {
            ApplyForceDonorMsbBehavior(target, donorBehaviorRef, record);
        }
    }

    static void ApplyNeutralDonorDefaults(MSBE.Part.Enemy target, PatchRecord record)
    {
        target.ChrActivateCondParamID = 0;
        target.BackupEventAnimID = -1;
        target.PlatoonID = 0;
        target.TalkID = 0;
        target.WalkRouteName = "";
        target.CollisionPartName = "";
        target.UnkT15 = false;
        record.RouteCleared = true;
        record.SlotStateCleared = true;
        record.AfterBackupAnim = target.BackupEventAnimID;
        record.AfterWalkRoute = target.WalkRouteName ?? "";
        record.AfterCollision = target.CollisionPartName ?? "";
    }

    static readonly string[] AerialSlotModelPrefixes =
    {
        "c6001", // Stormveil hawks / eagles
        "c4560",
        "c4561",
        "c4562",
        "c4563",
        // 飞龙/古龙 c450x/c451x/c4520 = 龙类超大，不算飞行体态（T-076 2026-08-19）
    };

    static bool IsAerialSlotModel(string? modelName)
    {
        if (string.IsNullOrWhiteSpace(modelName))
        {
            return false;
        }

        var model = modelName.ToLowerInvariant();
        return AerialSlotModelPrefixes.Any(p => model.StartsWith(p, StringComparison.Ordinal));
    }

    static readonly string[] DecorativeCorpseModelPrefixes =
    {
        "c3661",
        "c3662",
        "c4711",
    };

    /// <summary>
    /// Stormveil / tower ledges: keep CollisionPartName when transplanting (see ShouldClearSlotCollision).
    /// </summary>
    static readonly string[] PerchSlotModelPrefixes =
    {
        "c4210",
        "c3000",
        "c4160",
        "c4161",
        "c4162",
        "c4163",
        "c4164",
        "c4165",
        "c4166",
        "c4167",
    };

    static bool IsDecorativeCorpseSlotModel(string? modelName)
    {
        if (string.IsNullOrWhiteSpace(modelName))
        {
            return false;
        }

        var model = modelName.ToLowerInvariant();
        return DecorativeCorpseModelPrefixes.Any(p => model.StartsWith(p, StringComparison.Ordinal));
    }

    static bool IsPerchSlotModel(string? modelName)
    {
        if (string.IsNullOrWhiteSpace(modelName))
        {
            return false;
        }

        var model = modelName.ToLowerInvariant();
        return PerchSlotModelPrefixes.Any(p => model.StartsWith(p, StringComparison.Ordinal));
    }

    /// <summary>
    /// Only true aerial models (hawks/dragons). Do NOT use "collision + no walk route" —
    /// that clears Stormveil perch collision (c4210) and tower ledges (c3000), leaving empty slots.
    /// </summary>
    static bool ShouldClearPerchCollision(MSBE.Part.Enemy enemy) =>
        IsAerialSlotModel(enemy.ModelName);

    /// <summary>
    /// Clear lying/perch collision residue from the source slot. Keeps c4210/c3000 ledge collision.
    /// </summary>
    static bool ShouldClearSlotCollision(MSBE.Part.Enemy enemy) =>
        ShouldClearPerchCollision(enemy)
        || IsDecorativeCorpseSlotModel(enemy.ModelName)
        || (IsSittingSoldier(enemy) && !IsPerchSlotModel(enemy.ModelName));

    /// <summary>
    /// Slot keeps placement (xyz, entity id, groups, walk route when appropriate).
    /// Strip aerial / corpse / sit-pose residue so donor npc/think can run.
    /// </summary>
    static void StripInheritedSlotState(
        MSBE.Part.Enemy target,
        PatchRecord record,
        bool clearWalkRoute)
    {
        if (ShouldClearSlotCollision(target)
            && !string.IsNullOrWhiteSpace(target.CollisionPartName))
        {
            record.BeforeCollision = target.CollisionPartName;
            target.CollisionPartName = "";
            record.SlotStateCleared = true;
        }

        if (clearWalkRoute && !string.IsNullOrWhiteSpace(target.WalkRouteName))
        {
            target.WalkRouteName = "";
            record.RouteCleared = true;
            record.SlotStateCleared = true;
        }
    }

    static bool ShouldPreservePerchBackup(int backupAnim, string? collisionPart) =>
        backupAnim > 0 && !string.IsNullOrWhiteSpace(collisionPart);

    static void ApplyTransplantBehavior(MSBE.Part.Enemy enemy, PatchRecord record)
    {
        if (record.BeforeWalkRoute == "" && record.BeforeBackupAnim == 0)
        {
            record.BeforeBackupAnim = enemy.BackupEventAnimID;
            record.BeforeWalkRoute = enemy.WalkRouteName ?? "";
        }

        var preservePerchBackup = ShouldPreservePerchBackup(
            record.BeforeBackupAnim,
            record.BeforeCollision);

        // Backup poses for seated soldiers; keep perch backup when slot uses collision anchor.
        if (enemy.BackupEventAnimID != -1 && !preservePerchBackup)
        {
            record.SitCleared = true;
            enemy.BackupEventAnimID = -1;
        }

        record.AfterBackupAnim = enemy.BackupEventAnimID;
        record.AfterWalkRoute = enemy.WalkRouteName ?? "";
    }

    static bool IsSittingSoldier(MSBE.Part.Enemy enemy) =>
        enemy.BackupEventAnimID > 0 && string.IsNullOrWhiteSpace(enemy.WalkRouteName);

    static string? ResolveDonorEntityName(string? templateId)
    {
        if (string.IsNullOrWhiteSpace(templateId))
        {
            return null;
        }

        if (templateId.StartsWith("synthetic:", StringComparison.OrdinalIgnoreCase))
        {
            return SyntheticTemplateSources.TryGetValue(templateId, out var src)
                ? src.EntityName
                : null;
        }

        var colon = templateId.IndexOf(':');
        if (colon <= 0 || colon >= templateId.Length - 1)
        {
            return null;
        }

        return templateId[(colon + 1)..];
    }

    static MSBE.Part.Enemy? ResolveDonorMsbPart(
        string gameDir,
        string templateId,
        string slotMapId,
        string model,
        StringBuilder detailLog)
    {
        var donorMapId = ResolveDonorMapId(templateId, slotMapId);
        if (string.IsNullOrWhiteSpace(donorMapId))
        {
            return null;
        }

        var mapFile = $"{donorMapId}.msb.dcx";
        var entityName = ResolveDonorEntityName(templateId);
        if (!string.IsNullOrWhiteSpace(entityName))
        {
            var hit = FindEnemyPartEntryByName(gameDir, mapFile, entityName, detailLog);
            if (hit != null)
            {
                return hit;
            }
        }

        if (string.IsNullOrWhiteSpace(model))
        {
            return null;
        }

        var index = GetDonorEnemyIndex(gameDir, mapFile, detailLog);
        foreach (var enemy in index.Values)
        {
            if (string.Equals(enemy.ModelName, model, StringComparison.OrdinalIgnoreCase))
            {
                return enemy;
            }
        }

        return null;
    }

    /// <summary>
    /// T-073 §2.2：仅 force 捐皮从出处复制行为 MSB（禁止 WalkRoute/Collision/EntityID）。
    /// </summary>
    static void ApplyForceDonorMsbBehavior(
        MSBE.Part.Enemy target,
        MSBE.Part.Enemy behaviorSource,
        PatchRecord record)
    {
        target.ChrActivateCondParamID = behaviorSource.ChrActivateCondParamID;
        target.PlatoonID = behaviorSource.PlatoonID;
        target.TalkID = behaviorSource.TalkID;
        target.BackupEventAnimID = behaviorSource.BackupEventAnimID;
        target.UnkT15 = behaviorSource.UnkT15;
        record.AfterBackupAnim = target.BackupEventAnimID;
        record.AfterCollision = target.CollisionPartName ?? "";
        record.AfterWalkRoute = target.WalkRouteName ?? "";
    }

    /// <summary>
    /// T-073 §2.1 默认路径（T-076 恢复）：428 Anim=-1 + 保留目标槽巡逻/脚本字段。
    /// spawn 四元组由 <see cref="ApplySpawnMapParamIds"/> 覆盖。
    /// </summary>
    static void ApplyDonorTransplant(
        MSBE.Part.Enemy target,
        MSBE.Part.Enemy donor,
        PatchRecord record,
        bool demount = false,
        MSBE.Part.Enemy? donorBehaviorRef = null,
        bool forceDonorMsb = false,
        string? slotMapId = null,
        string? slotEntityName = null,
        string? donorTemplateId = null,
        IReadOnlySet<string>? validCollisionParts = null)
    {
        record.BeforeModel = target.ModelName;
        record.BeforeNpc = target.NPCParamID;
        record.BeforeThink = target.ThinkParamID;
        record.BeforeChara = target.CharaInitID;
        record.BeforeBackupAnim = target.BackupEventAnimID;
        record.BeforeWalkRoute = target.WalkRouteName ?? "";
        record.BeforeCollision = target.CollisionPartName ?? "";

        var donorFullMsbTest = IsDonorFullMsbTestMap(slotMapId);
        StripInheritedSlotState(target, record, clearWalkRoute: false);
        record.ForceDonorMsb = forceDonorMsb || donorFullMsbTest;

        target.ModelName = donor.ModelName;
        target.NPCParamID = donor.NPCParamID;
        target.ThinkParamID = donor.ThinkParamID;
        target.CharaInitID = donor.CharaInitID;

        if (donorFullMsbTest)
        {
            ApplyDonorFullMsbTestBehavior(target, donorBehaviorRef, record);
        }
        else
        {
            ApplyTransplantBehavior(target, record);
            target.UnkT15 = false;

            if (forceDonorMsb && donorBehaviorRef != null)
            {
                ApplyForceDonorMsbBehavior(target, donorBehaviorRef, record);
            }
        }

        ApplySlot428Tags(target, record, slotMapId, slotEntityName, validCollisionParts);

        if (ResolveDonorHidden(donorTemplateId)
            && !string.IsNullOrWhiteSpace(target.WalkRouteName))
        {
            target.WalkRouteName = "";
            record.RouteCleared = true;
        }

        if (demount && !string.IsNullOrWhiteSpace(target.WalkRouteName))
        {
            target.WalkRouteName = "";
            record.RouteCleared = true;
        }

        record.AfterModel = target.ModelName;
        record.AfterNpc = target.NPCParamID;
        record.AfterThink = target.ThinkParamID;
        record.AfterChara = target.CharaInitID;
        record.AfterBackupAnim = target.BackupEventAnimID;
        record.AfterWalkRoute = target.WalkRouteName ?? "";
        record.AfterCollision = target.CollisionPartName ?? "";
        record.WalkRouteKept = !record.RouteCleared
            && !string.IsNullOrWhiteSpace(record.AfterWalkRoute);
    }

    static void ApplySpawnMapParamIds(
        MSBE.Part.Enemy target,
        SpawnMapEntry entry,
        PatchRecord record)
    {
        target.NPCParamID = entry.Npc;
        target.ThinkParamID = entry.Think;
        if (entry.Chara >= 0)
        {
            target.CharaInitID = entry.Chara;
        }

        record.AfterNpc = target.NPCParamID;
        record.AfterThink = target.ThinkParamID;
        record.AfterChara = target.CharaInitID;
    }
}

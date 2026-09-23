using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using SoulsFormats;
using SoulsFormats.Cryptography;

/// <summary>
/// T-052 NpcParam soul copies + Radahn roadside phase-1 AI helper.
/// </summary>
static class Program
{
    const int IdBase = 880_000_000;
    const int IdLimit = 881_000_000;
    const int ThinkIdBase = 890_000_000;
    const int ThinkIdLimit = 891_000_000;
    const int RadahnPhase1ThinkId = 47_309_000;
    const int RadahnPhase1BattleGoalId = 473_090;
    const int RadahnBaseThinkId = 47_300_000;
    const int RadahnBaseNpcId = 47_300_040;
    const int RadahnLandedNpcId = 47_300_041;
    // Landed phase-2 donor: spawn with weapons swap + phase2 + meteor cooldown elapsed.
    const int RadahnLandedFxWeapons = 13_902;
    const int RadahnLandedFxPhase2 = 13_904;
    const int RadahnLandedFxMeteorDone = 13_928;

    static int Main(string[] args)
    {
        try
        {
            if (args.Any(a => a == "--ensure-radahn-phase1"))
                return EnsureRadahnPhase1(args);
            return RunSoulCopies(args);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex);
            return 1;
        }
    }

    const string RadahnCanaryMarker = "CNV_RADAHN_CANARY_v8911";

    static int EnsureRadahnPhase1(string[] args)
    {
        // In-place patch 473000_battle (disable meteor Act13) + neuter TAE 3035/3029.
        // Do NOT invent battleGoal 473090: a prior copy crashed at end-of-load.
        string? regulation = null;
        string? gameDir = null;
        for (int i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--ensure-radahn-phase1":
                    break;
                case "--regulation":
                    regulation = args[++i];
                    break;
                case "--game-dir":
                    gameDir = args[++i];
                    break;
                default:
                    Console.Error.WriteLine($"Unknown arg: {args[i]}");
                    return 2;
            }
        }

        gameDir ??= Environment.GetEnvironmentVariable("CNV_GAME_DIR");
        if (string.IsNullOrWhiteSpace(gameDir))
            gameDir = @"V:\games\Elden Ring\Game";
        regulation ??= Path.Combine(gameDir, "mod", "regulation.bin");

        var aiPath = Path.Combine(gameDir, "mod", "script", "473000_battle.luabnd.dcx");
        var legacyAi = Path.Combine(gameDir, "mod", "script", "473090_battle.luabnd.dcx");
        if (!File.Exists(aiPath))
        {
            Console.Error.WriteLine($"missing source AI: {aiPath}");
            return 3;
        }

        var aiBak = aiPath + ".pre_phase1.bak";
        if (!File.Exists(aiBak))
            File.Copy(aiPath, aiBak);
        else
            File.Copy(aiBak, aiPath, overwrite: true); // always re-patch from original

        Console.WriteLine($"Patch AI in-place {aiPath} (from bak)");
        var aiBnd = BND4.Read(aiPath);
        int patchedFiles = 0;
        bool canaryOk = false;
        foreach (var f in aiBnd.Files)
        {
            var name = f.Name.Replace('\\', '/');
            if (!name.EndsWith(".lua", StringComparison.OrdinalIgnoreCase))
                continue;
            var text = Encoding.UTF8.GetString(f.Bytes);
            var patched = PatchRadahnBattleLua(text);
            canaryOk = patched.Contains(RadahnCanaryMarker, StringComparison.Ordinal);
            if (!ReferenceEquals(patched, text) && patched != text)
            {
                f.Bytes = Encoding.UTF8.GetBytes(patched);
                patchedFiles++;
            }
        }
        aiBnd.Write(aiPath);
        Console.WriteLine($"wrote {aiPath} lua_patched={patchedFiles} canary={canaryOk} marker={RadahnCanaryMarker}");

        var mirrorDir = Path.Combine(gameDir, "mod", "script", "ai", "out", "each");
        Directory.CreateDirectory(mirrorDir);
        var mirrorPath = Path.Combine(mirrorDir, "473000_battle.luabnd.dcx");
        File.Copy(aiPath, mirrorPath, overwrite: true);
        Console.WriteLine($"mirrored {mirrorPath}");

        if (File.Exists(legacyAi))
        {
            File.Delete(legacyAi);
            Console.WriteLine($"deleted legacy {legacyAi}");
        }

        var taeReport = PatchRadahnAnibnd(gameDir);

        if (!File.Exists(regulation))
        {
            Console.Error.WriteLine($"missing regulation: {regulation}");
            return 3;
        }

        var thinkDef = DefaultThinkParamdef();
        if (!File.Exists(thinkDef))
        {
            Console.Error.WriteLine($"missing NpcThinkParam.xml: {thinkDef}");
            return 3;
        }

        var npcDef = DefaultParamdef();
        if (!File.Exists(npcDef))
        {
            Console.Error.WriteLine($"missing NpcParam.xml paramdef: {npcDef}");
            return 3;
        }

        Console.WriteLine($"Remove legacy ThinkParam {RadahnPhase1ThinkId} if present");
        var reg = RegulationDecryptor.DecryptERRegulation(regulation);
        var thinkFile = reg.Files.FirstOrDefault(f =>
            f.Name.Replace('\\', '/').EndsWith("/NpcThinkParam.param", StringComparison.OrdinalIgnoreCase)
            || f.Name.EndsWith("NpcThinkParam.param", StringComparison.OrdinalIgnoreCase));
        if (thinkFile is null)
        {
            Console.Error.WriteLine("NpcThinkParam.param not found");
            return 3;
        }

        var thinkParam = PARAM.Read(thinkFile.Bytes);
        var thinkParamdef = PARAMDEF.XmlDeserialize(thinkDef);
        if (!thinkParam.ApplyParamdefCarefully(thinkParamdef))
            thinkParam.ApplyParamdef(thinkParamdef);

        int removed = thinkParam.Rows.RemoveAll(r => r.ID == RadahnPhase1ThinkId);
        if (removed > 0)
            thinkFile.Bytes = thinkParam.Write();

        int landed = EnsureRadahnLandedNpcRow(reg, npcDef);

        RegulationDecryptor.EncryptERRegulation(regulation, reg);

        WriteRadahnPhase1Stamp(gameDir, canaryOk, taeReport, removed, landed);
        Console.WriteLine(
            $"ok radahn_phase1 battleGoal=473000 removed_legacy_think={removed} landed_npc={RadahnLandedNpcId} fx={landed} {taeReport}");
        return 0;
    }

    static string PatchRadahnAnibnd(string gameDir)
    {
        Console.WriteLine("skip anibnd TAE neuter (DLL landing shim; no extra chr install)");
        return "tae=skip_dll_landing_shim";
    }

    static int EnsureRadahnLandedNpcRow(BND4 reg, string npcParamdefPath)
    {
        var npcFile = reg.Files.FirstOrDefault(f =>
            f.Name.Replace('\\', '/').EndsWith("/NpcParam.param", StringComparison.OrdinalIgnoreCase)
            || f.Name.EndsWith("NpcParam.param", StringComparison.OrdinalIgnoreCase));
        if (npcFile is null)
        {
            Console.Error.WriteLine("NpcParam.param not found");
            return 0;
        }

        var param = PARAM.Read(npcFile.Bytes);
        var def = PARAMDEF.XmlDeserialize(npcParamdefPath);
        if (!param.ApplyParamdefCarefully(def))
            param.ApplyParamdef(def);

        var byId = param.Rows.ToDictionary(r => r.ID);
        if (!byId.TryGetValue(RadahnBaseNpcId, out var src))
        {
            Console.Error.WriteLine($"missing base Radahn NpcParam {RadahnBaseNpcId}");
            return 0;
        }

        PARAM.Row row;
        if (byId.TryGetValue(RadahnLandedNpcId, out var existing))
        {
            row = existing;
        }
        else
        {
            row = new PARAM.Row(src)
            {
                ID = RadahnLandedNpcId,
                Name = string.IsNullOrWhiteSpace(src.Name)
                    ? "Radahn landed [cnv]"
                    : $"{src.Name}（已落地）[cnv]",
            };
            param.Rows.Add(row);
        }

        SetCell(row, "spEffectID14", RadahnLandedFxWeapons);
        SetCell(row, "spEffectID15", RadahnLandedFxPhase2);
        SetCell(row, "spEffectID17", RadahnLandedFxMeteorDone);

        param.Rows.Sort((a, b) => a.ID.CompareTo(b.ID));
        npcFile.Bytes = param.Write();
        Console.WriteLine(
            $"ensured landed Radahn NpcParam {RadahnLandedNpcId} sp=({RadahnLandedFxWeapons},{RadahnLandedFxPhase2},{RadahnLandedFxMeteorDone})");
        return 1;
    }

    static void WriteRadahnPhase1Stamp(
        string gameDir,
        bool canaryOk,
        string taeReport,
        int removedThink,
        int landedNpc)
    {
        var stampDir = Path.Combine(gameDir, "mod", "dll");
        Directory.CreateDirectory(stampDir);
        var stampPath = Path.Combine(stampDir, "cnv_radahn_phase1_stamp.txt");
        var sb = new StringBuilder();
        sb.AppendLine("CNV_RADAHN_PHASE1");
        sb.AppendLine($"canary={RadahnCanaryMarker}");
        sb.AppendLine($"canary_ok={(canaryOk ? 1 : 0)}");
        sb.AppendLine(taeReport);
        sb.AppendLine($"removed_legacy_think={removedThink}");
        sb.AppendLine($"landed_npc={RadahnLandedNpcId}");
        sb.AppendLine($"landed_npc_ok={landedNpc}");
        sb.AppendLine($"utc={DateTime.UtcNow:yyyy-MM-ddTHH:mm:ssZ}");
        File.WriteAllText(stampPath, sb.ToString(), Encoding.UTF8);
        Console.WriteLine($"stamp {stampPath}");
    }

    static string PatchRadahnBattleLua(string text)
    {
        // Phase ladder: Act10 (anim 3029) → SpEffect 13903 → Act13 (anim 3035 meteor flyaway).
        text = Regex.Replace(
            text,
            @"probabilities\[10\]\s*=\s*100",
            "probabilities[10] = 0 -- cnv: disable phase sword-leap (3029)");
        text = Regex.Replace(
            text,
            @"probabilities\[13\]\s*=\s*100",
            "probabilities[13] = 0 -- cnv: disable meteor / phase2 flyaway");

        if (!text.Contains("cnv: force no phase/meteor", StringComparison.Ordinal))
        {
            text = Regex.Replace(
                text,
                @"(probabilities\[13\]\s*=\s*SetCoolTime\(ai,\s*goal,\s*3035,\s*1,\s*probabilities\[13\],\s*1\))",
                """
                $1
                    -- cnv: force no phase/meteor after cooltime
                    probabilities[10] = 0
                    probabilities[13] = 0
                """);
        }

        // Act10 empty; Act13 canary plays ground anim 3000 (if this fires, script loaded).
        text = Regex.Replace(
            text,
            @"function\s+RadarnAndLeonard473000_Act10\s*\(ai,\s*goal,\s*paramTbl\)\s*.*?end",
            """
            function RadarnAndLeonard473000_Act10(ai, goal, paramTbl)
                -- cnv: phase sword-leap disabled
                GetWellSpace_Odds = 0
                return GetWellSpace_Odds
            end
            """,
            RegexOptions.Singleline);
        text = Regex.Replace(
            text,
            @"function\s+RadarnAndLeonard473000_Act13\s*\(ai,\s*goal,\s*paramTbl\)\s*.*?end",
            """
            function RadarnAndLeonard473000_Act13(ai, goal, paramTbl)
                -- cnv: meteor jump disabled; canary plays ground anim 3000 instead of 3035
                local animationId = 3000
                local successDist = 5 - ai:GetMapHitRadius(TARGET_SELF) + 999
                goal:AddSubGoal(GOAL_COMMON_ComboTunable_SuccessAngle180, 15, animationId, TARGET_ENE_0, successDist, 0, 0, 0, 0)
                GetWellSpace_Odds = 0
                return GetWellSpace_Odds
            end
            """,
            RegexOptions.Singleline);

        // Header canary — DLL binary-scans binders for this marker.
        if (!text.Contains(RadahnCanaryMarker, StringComparison.Ordinal))
        {
            text = "-- " + RadahnCanaryMarker + " radahn phase1: no Act10/13 meteor; Act13->3000\n" + text;
        }

        return text;
    }

    static int RunSoulCopies(string[] args)
    {
        string? regulation = null;
        string? copiesPath = null;
        string? paramdefPath = null;
        bool clearOnly = false;
        bool clearBand = true;

        for (int i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--regulation":
                    regulation = args[++i];
                    break;
                case "--copies":
                    copiesPath = args[++i];
                    break;
                case "--paramdef":
                    paramdefPath = args[++i];
                    break;
                case "--clear-only":
                    clearOnly = true;
                    break;
                case "--no-clear":
                    clearBand = false;
                    break;
                default:
                    Console.Error.WriteLine($"Unknown arg: {args[i]}");
                    return 2;
            }
        }

        if (string.IsNullOrWhiteSpace(regulation) || !File.Exists(regulation))
        {
            Console.Error.WriteLine("Missing --regulation path");
            return 2;
        }

        paramdefPath ??= DefaultParamdef();
        if (!File.Exists(paramdefPath))
        {
            Console.Error.WriteLine($"Missing NpcParam.xml paramdef: {paramdefPath}");
            return 2;
        }

        var bak = regulation + ".pre_t052.bak";
        if (!File.Exists(bak))
            File.Copy(regulation, bak);

        Console.WriteLine($"Decrypt {regulation}");
        var bnd = RegulationDecryptor.DecryptERRegulation(regulation);
        var file = bnd.Files.FirstOrDefault(f =>
            f.Name.Replace('\\', '/').EndsWith("/NpcParam.param", StringComparison.OrdinalIgnoreCase)
            || f.Name.EndsWith("NpcParam.param", StringComparison.OrdinalIgnoreCase));
        if (file is null)
        {
            Console.Error.WriteLine("NpcParam.param not found in regulation");
            return 3;
        }

        var param = PARAM.Read(file.Bytes);
        var def = PARAMDEF.XmlDeserialize(paramdefPath);
        if (!param.ApplyParamdefCarefully(def))
        {
            Console.WriteLine("WARN ApplyParamdefCarefully failed; trying ApplyParamdef");
            param.ApplyParamdef(def);
        }

        int removed = 0;
        if (clearBand || clearOnly)
        {
            removed = param.Rows.RemoveAll(r => r.ID >= IdBase && r.ID < IdLimit);
            Console.WriteLine($"cleared_band={removed}");
        }

        int added = 0;
        int thinkAdded = 0;
        int thinkRemoved = 0;
        JsonDocument? doc = null;
        if (!clearOnly)
        {
            if (string.IsNullOrWhiteSpace(copiesPath) || !File.Exists(copiesPath))
            {
                Console.Error.WriteLine("Missing --copies json (or use --clear-only)");
                return 2;
            }

            doc = JsonDocument.Parse(File.ReadAllText(copiesPath));
            if (!doc.RootElement.TryGetProperty("copies", out var copiesEl)
                || copiesEl.ValueKind != JsonValueKind.Array)
            {
                Console.Error.WriteLine("copies[] missing in json");
                return 2;
            }

            var byId = param.Rows.ToDictionary(r => r.ID);
            foreach (var spec in copiesEl.EnumerateArray())
            {
                int copyId = spec.GetProperty("copy_id").GetInt32();
                int baseNpc = spec.GetProperty("base_npc").GetInt32();
                int getSoul = spec.GetProperty("get_soul").GetInt32();
                if (!byId.TryGetValue(baseNpc, out var src))
                {
                    Console.Error.WriteLine($"missing base row {baseNpc}");
                    return 4;
                }

                var row = new PARAM.Row(src)
                {
                    ID = copyId,
                    Name = string.IsNullOrWhiteSpace(src.Name)
                        ? $"cnv_soul_{copyId}"
                        : $"{src.Name} [cnv soul {getSoul}]",
                };
                SetCell(row, "getSoul", getSoul);
                if (spec.TryGetProperty("hp", out var hpEl)
                    && TryReadJsonInt32(hpEl, out var hpVal))
                    SetCell(row, "hp", hpVal);
                if (spec.TryGetProperty("defFlickPower", out var poiseEl)
                    && TryReadJsonInt32(poiseEl, out var poiseVal))
                    SetCell(row, "defFlickPower", poiseVal);
                // T-053: overrides may be JSON numbers or numeric strings (Python
                // historically wrote "7070"); GetInt32-only silently dropped region sp.
                if (spec.TryGetProperty("sp_effect_overrides", out var spEl)
                    && spEl.ValueKind == JsonValueKind.Object)
                {
                    foreach (var prop in spEl.EnumerateObject())
                    {
                        if (!TryReadJsonInt32(prop.Value, out var spId))
                            continue;
                        TrySetCell(row, prop.Name, spId);
                    }
                }
                TrySetCell(row, "isSoulGetByBoss", (byte)0);
                TrySetCell(row, "disableRespawn", (byte)0);
                TrySetCell(row, "disableInitializeDead", (byte)0);
                if (spec.TryGetProperty("team_type", out var teamEl)
                    && TryReadJsonInt32(teamEl, out var teamVal))
                    TrySetCell(row, "teamType", (ushort)teamVal);
                param.Rows.Add(row);
                byId[copyId] = row;
                added++;
            }
        }

        param.Rows.Sort((a, b) => a.ID.CompareTo(b.ID));
        file.Bytes = param.Write();

        if (clearOnly)
        {
            (thinkRemoved, thinkAdded) = ApplyThinkCopies(bnd, null, clearThinkOnly: true);
        }
        else if (doc is not null)
        {
            (thinkRemoved, thinkAdded) = ApplyThinkCopies(bnd, doc.RootElement, clearThinkOnly: false);
        }

        RegulationDecryptor.EncryptERRegulation(regulation, bnd);
        Console.WriteLine(
            $"ok added={added} removed={removed} think_added={thinkAdded} think_removed={thinkRemoved} regulation={regulation}");
        doc?.Dispose();
        return 0;
    }

    static (int removed, int added) ApplyThinkCopies(BND4 bnd, JsonElement? root, bool clearThinkOnly)
    {
        var thinkDef = DefaultThinkParamdef();
        if (!File.Exists(thinkDef))
        {
            Console.Error.WriteLine($"missing NpcThinkParam.xml: {thinkDef}");
            return (0, 0);
        }

        var thinkFile = bnd.Files.FirstOrDefault(f =>
            f.Name.Replace('\\', '/').EndsWith("/NpcThinkParam.param", StringComparison.OrdinalIgnoreCase)
            || f.Name.EndsWith("NpcThinkParam.param", StringComparison.OrdinalIgnoreCase));
        if (thinkFile is null)
        {
            Console.Error.WriteLine("NpcThinkParam.param not found in regulation");
            return (0, 0);
        }

        var thinkParam = PARAM.Read(thinkFile.Bytes);
        var thinkDefObj = PARAMDEF.XmlDeserialize(thinkDef);
        if (!thinkParam.ApplyParamdefCarefully(thinkDefObj))
            thinkParam.ApplyParamdef(thinkDefObj);

        int removed = thinkParam.Rows.RemoveAll(r => r.ID >= ThinkIdBase && r.ID < ThinkIdLimit);
        int added = 0;

        if (!clearThinkOnly && root is not null && root.Value.TryGetProperty("think_copies", out var thinkEl)
            && thinkEl.ValueKind == JsonValueKind.Array)
        {
            var byId = thinkParam.Rows.ToDictionary(r => r.ID);
            foreach (var spec in thinkEl.EnumerateArray())
            {
                int copyId = spec.GetProperty("copy_id").GetInt32();
                int baseThink = spec.GetProperty("base_think").GetInt32();
                if (!byId.TryGetValue(baseThink, out var src))
                {
                    Console.Error.WriteLine($"missing base think row {baseThink}");
                    throw new InvalidOperationException($"missing base think row {baseThink}");
                }

                var row = new PARAM.Row(src)
                {
                    ID = copyId,
                    Name = string.IsNullOrWhiteSpace(src.Name)
                        ? $"cnv_think_{copyId}"
                        : $"{src.Name} [cnv think]",
                };
                if (spec.TryGetProperty("field_overrides", out var ovEl)
                    && ovEl.ValueKind == JsonValueKind.Object)
                {
                    foreach (var prop in ovEl.EnumerateObject())
                    {
                        var raw = prop.Value.GetString() ?? prop.Value.ToString();
                        if (string.IsNullOrWhiteSpace(raw))
                            continue;
                        if (raw.Contains('.', StringComparison.Ordinal))
                        {
                            if (double.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out var dv))
                                SetCell(row, prop.Name, dv);
                        }
                        else if (int.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out var iv))
                        {
                            SetCell(row, prop.Name, iv);
                        }
                    }
                }
                thinkParam.Rows.Add(row);
                byId[copyId] = row;
                added++;
            }
        }

        thinkParam.Rows.Sort((a, b) => a.ID.CompareTo(b.ID));
        thinkFile.Bytes = thinkParam.Write();
        return (removed, added);
    }

    static void SetCell(PARAM.Row row, string name, object value)
    {
        row[name].Value = Coerce(row[name].Value, value);
    }

    static void TrySetCell(PARAM.Row row, string name, object value)
    {
        try { SetCell(row, name, value); }
        catch (InvalidOperationException) { /* field absent */ }
    }

    /// <summary>Accept JSON number or numeric string (e.g. "7070").</summary>
    static bool TryReadJsonInt32(JsonElement el, out int value)
    {
        value = 0;
        switch (el.ValueKind)
        {
            case JsonValueKind.Number:
                return el.TryGetInt32(out value);
            case JsonValueKind.String:
                return int.TryParse(
                    el.GetString(),
                    NumberStyles.Integer,
                    CultureInfo.InvariantCulture,
                    out value);
            default:
                return false;
        }
    }

    static object Coerce(object current, object wanted)
    {
        if (current is null) return wanted;
        var t = current.GetType();
        if (t == wanted.GetType()) return wanted;
        try
        {
            return Convert.ChangeType(wanted, t, CultureInfo.InvariantCulture);
        }
        catch (OverflowException)
        {
            // Think/Npc overrides must fit PARAM cell types (e.g. u16 nonBattleActLife).
            double d = Convert.ToDouble(wanted, CultureInfo.InvariantCulture);
            if (t == typeof(byte))
                return (byte)Math.Clamp(d, byte.MinValue, byte.MaxValue);
            if (t == typeof(sbyte))
                return (sbyte)Math.Clamp(d, sbyte.MinValue, sbyte.MaxValue);
            if (t == typeof(ushort))
                return (ushort)Math.Clamp(d, ushort.MinValue, ushort.MaxValue);
            if (t == typeof(short))
                return (short)Math.Clamp(d, short.MinValue, short.MaxValue);
            if (t == typeof(uint))
                return (uint)Math.Clamp(d, uint.MinValue, uint.MaxValue);
            if (t == typeof(int))
                return (int)Math.Clamp(d, int.MinValue, int.MaxValue);
            throw;
        }
    }

    static string DefaultParamdef()
    {
        var game = Environment.GetEnvironmentVariable("CNV_GAME_DIR");
        var candidates = new List<string>();
        if (!string.IsNullOrWhiteSpace(game))
        {
            candidates.Add(Path.Combine(game, "tools", "DSMSPortable", "app", "Assets", "Paramdex", "ER", "Defs", "NpcParam.xml"));
            candidates.Add(Path.Combine(game, "tools", "DSMSPortable", "Assets", "Paramdex", "ER", "Defs", "NpcParam.xml"));
        }
        candidates.Add(@"V:\games\Elden Ring\Game\tools\DSMSPortable\app\Assets\Paramdex\ER\Defs\NpcParam.xml");
        return candidates.FirstOrDefault(File.Exists) ?? candidates[0];
    }

    static string DefaultThinkParamdef()
    {
        var game = Environment.GetEnvironmentVariable("CNV_GAME_DIR");
        var candidates = new List<string>();
        if (!string.IsNullOrWhiteSpace(game))
        {
            candidates.Add(Path.Combine(game, "tools", "DSMSPortable", "app", "Assets", "Paramdex", "ER", "Defs", "NpcThinkParam.xml"));
            candidates.Add(Path.Combine(game, "tools", "DSMSPortable", "Assets", "Paramdex", "ER", "Defs", "NpcThinkParam.xml"));
        }
        candidates.Add(@"V:\games\Elden Ring\Game\tools\DSMSPortable\app\Assets\Paramdex\ER\Defs\NpcThinkParam.xml");
        return candidates.FirstOrDefault(File.Exists) ?? candidates[0];
    }
}

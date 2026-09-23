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

// apply-map pipeline (T-073 R3)

static partial class Program
{
    static void SupplementModelRegistryFromSpawnEntries(
        Dictionary<string, (string MapFile, MSBE.Model.Enemy Model)> registry,
        IReadOnlyList<SpawnMapEntry> entries)
    {
        _ = registry;
        _ = entries;
    }

    static List<string> CollectWarmMapFiles(
        IReadOnlyList<IGrouping<string, SpawnMapEntry>> mapGroups,
        IReadOnlyList<SpawnMapEntry> entries)
    {
        var files = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var group in mapGroups)
        {
            files.Add($"{group.Key}.msb.dcx");
        }

        foreach (var entry in entries)
        {
            var donorMapId = ResolveDonorMapId(entry.TemplateId, entry.MapId);
            if (!string.IsNullOrWhiteSpace(donorMapId))
            {
                files.Add($"{donorMapId}.msb.dcx");
            }
        }

        foreach (var src in SyntheticTemplateSources.Values)
        {
            if (IsValidDonorMapId(src.MapId))
            {
                files.Add($"{src.MapId}.msb.dcx");
            }
        }

        files.Add("m60_42_36_00.msb.dcx");
        files.Add("m60_41_51_00.msb.dcx");

        return files.OrderBy(f => f, StringComparer.OrdinalIgnoreCase).ToList();
    }

    static void EnsureEnemyModel(
        MSBE msb,
        string modelName,
        string gameDir,
        StringBuilder detailLog,
        bool quiet = false,
        string? preferDonorMapId = null,
        IReadOnlyDictionary<string, (string MapFile, MSBE.Model.Enemy Model)>? modelRegistry = null,
        ISet<string>? mapModelNames = null)
    {
        var existingOnMap = FindEnemyModelOnMsb(msb, modelName);
        var hasCompleteOnMap = existingOnMap != null
            && (mapModelNames == null || mapModelNames.Contains(modelName))
            && !IsEnemyModelStub(existingOnMap);
        if (hasCompleteOnMap)
        {
            return;
        }

        MSBE.Model.Enemy? replacement = null;
        string replacementSource = "";

        if (modelRegistry != null
            && modelRegistry.TryGetValue(modelName, out var cached)
            && !IsEnemyModelStub(cached.Model))
        {
            replacement = cached.Model;
            replacementSource = $"from_cache={cached.MapFile}";
        }

        if (replacement == null && !ModelRegistryMissCache.Contains(modelName))
        {
            var modelEntry = FindEnemyModelEntry(gameDir, modelName, detailLog, preferDonorMapId);
            if (modelEntry != null && !IsEnemyModelStub(modelEntry.Value.Model))
            {
                replacement = modelEntry.Value.Model;
                replacementSource = $"from_map={modelEntry.Value.MapPath}";
            }
            else if (ModelRegistryScopedToSpawn)
            {
                ModelRegistryMissCache.Add(modelName);
            }
        }

        if (replacement != null)
        {
            if (existingOnMap != null)
            {
                TryReplaceEnemyModelOnMsb(msb, modelName, replacement);
                Interlocked.Increment(ref ModelEnsureUpgradeCount);
                Log(detailLog, $"model_registry={modelName} status=upgraded {replacementSource}");
                if (!quiet)
                {
                    Console.WriteLine($"Model registry: upgraded {modelName} {replacementSource}");
                }
            }
            else
            {
                AddEnemyModelToMsb(msb, replacement, mapModelNames);
                Log(detailLog, $"model_registry={modelName} status=added {replacementSource}");
                if (!quiet)
                {
                    Console.WriteLine($"Model registry: added {modelName} {replacementSource}");
                }
            }

            return;
        }

        if (existingOnMap != null)
        {
            return;
        }

        var stub = CreateEnemyModelStub(modelName);
        AddEnemyModelToMsb(msb, stub, mapModelNames);
        Interlocked.Increment(ref ModelEnsureStubCount);
        Log(detailLog, $"model_registry={modelName} status=stub_sib_only");
        if (!quiet)
        {
            Console.WriteLine($"Model registry: stub {modelName} (SIB path only — no donor MSB model entry)");
        }
    }

    static bool MsbSourceCacheEnabled = true;
    static long MsbSourceCacheHits;
    static long MsbSourceCacheMisses;
    static bool ApplyProfileEnabled;
    static readonly ApplyProfileStats ApplyProfile = new();
    static ConcurrentDictionary<string, HashSet<string>> CnvMapModelIndex = new(StringComparer.OrdinalIgnoreCase);
    static bool CnvMapModelIndexDirty;
    static string CnvMapModelIndexFingerprint = "";
    static long ModelEnsureStubCount;
    static long ModelEnsureUpgradeCount;
    static bool ModelRegistryScopedToSpawn;
    static readonly HashSet<string> ModelRegistryMissCache = new(StringComparer.OrdinalIgnoreCase);
    static SemaphoreSlim? MapApplyInflight;
    static readonly ConcurrentDictionary<string, object> MsbSourceCacheFileLocks = new();

    /// <summary>apply-map: one MSB parse per donor map, not per slot.</summary>
    static readonly ConcurrentDictionary<string, Dictionary<string, MSBE.Part.Enemy>> DonorEnemyByMapCache =
        new(StringComparer.OrdinalIgnoreCase);
    static Dictionary<ulong, (string BdtPath, BHD5.FileHeader Header)>? BhdFileIndex;
    static readonly object BhdFileIndexLock = new();

    static MSBE? TryReadMsbFromPath(string path, StringBuilder detailLog, string mapFileName)
    {
        try
        {
            return MSBE.Read(path);
        }
        catch (Exception ex)
        {
            Log(detailLog, $"msb_stream_skip {mapFileName} path={path}: {ex.Message}");
            return null;
        }
    }

    static void WriteMsbeToPath(MSBE msb, string path) => msb.Write(path, MsbeWriteCompression(msb));

    static MSBE? TryReadMsbSafe(string gameDir, string mapFileName, StringBuilder detailLog)
    {
        if (MsbSourceCacheEnabled)
        {
            var cachePath = MsbSourceCacheFilePath(gameDir, mapFileName);
            if (File.Exists(cachePath))
            {
                var cached = TryReadMsbFromPath(cachePath, detailLog, mapFileName);
                if (cached != null)
                {
                    Interlocked.Increment(ref MsbSourceCacheHits);
                    return cached;
                }
            }
        }

        var modPath = Path.Combine(CnvMapStudioDir(gameDir), mapFileName);
        if (File.Exists(modPath))
        {
            var fromMod = TryReadMsbFromPath(modPath, detailLog, mapFileName);
            if (fromMod != null)
            {
                if (MsbSourceCacheEnabled)
                {
                    TryWriteMsbSourceCacheFromMod(gameDir, mapFileName, modPath);
                    Interlocked.Increment(ref MsbSourceCacheMisses);
                }

                return fromMod;
            }
        }

        var bytes = TryReadMapBytes(gameDir, mapFileName, detailLog);
        if (bytes == null)
        {
            return null;
        }

        try
        {
            if (MsbSourceCacheEnabled)
            {
                TryWriteMsbSourceCache(gameDir, mapFileName, bytes);
                Interlocked.Increment(ref MsbSourceCacheMisses);
                var cachePath = MsbSourceCacheFilePath(gameDir, mapFileName);
                if (File.Exists(cachePath))
                {
                    return TryReadMsbFromPath(cachePath, detailLog, mapFileName);
                }
            }

            var decomp = DCX.Is(bytes) ? DCX.Decompress(bytes) : bytes;
            return ReadMsbe(decomp);
        }
        catch (Exception ex)
        {
            Log(detailLog, $"msb_safe_skip {mapFileName}: {ex.Message}");
            return null;
        }
    }

    static int ApplySpawnMap(string gameDir, string[] args, StringBuilder detailLog)
    {
        var spawnMapPath = ResolveSpawnMapPath(args);
        var mapFilter = ResolveMapFilter(args);
        if (!File.Exists(spawnMapPath))
        {
            Console.Error.WriteLine($"Missing spawn map: {spawnMapPath}");
            WriteDetailLog(detailLog, "apply-map_failed=no_spawn_map");
            return 1;
        }

        var entries = ParseSpawnMap(spawnMapPath);
        if (entries.Count == 0)
        {
            Console.Error.WriteLine($"No slot lines in spawn map: {spawnMapPath}");
            WriteDetailLog(detailLog, "apply-map_failed=empty_spawn_map");
            return 1;
        }

        if (!string.IsNullOrWhiteSpace(mapFilter))
        {
            entries = entries
                .Where(e => string.Equals(e.MapId, mapFilter, StringComparison.OrdinalIgnoreCase))
                .ToList();
            Log(detailLog, $"apply_map_filter={mapFilter} entries={entries.Count}");
        }

        Console.WriteLine($"apply-map: {entries.Count} slots from {spawnMapPath}");
        Log(detailLog, $"spawn_map={spawnMapPath} slots={entries.Count}");

        var byMap = entries.GroupBy(e => e.MapId).OrderBy(g => g.Key, StringComparer.Ordinal);
        var outDir = OverlayMapStudioDir(gameDir);
        Directory.CreateDirectory(outDir);

        var parallel = ResolveParallelDegree(args);
        var maxParallel = ResolveMaxParallelDegree(args);
        var mapInflight = ResolveMapInflightLimit(args);
        var dynamicParallel = ResolveDynamicParallel(args);
        MapApplyInflight?.Dispose();
        MapApplyInflight = new SemaphoreSlim(mapInflight, mapInflight);
        var quiet = ResolveQuietApply(args);
        ApplyProfileEnabled = ResolveProfileApply(args);
        ApplyProfile.Reset();
        LastMapHeartbeatMs = 0;
        ModelEnsureStubCount = 0;
        ModelEnsureUpgradeCount = 0;
        ModelRegistryScopedToSpawn = false;
        ModelRegistryMissCache.Clear();
        LoadSyntheticTemplateSources();
        LoadDonorSlotCompatCache();
        LoadTestMapApplyModes();
        LoadApplySlot428Tags();
        MsbSourceCacheEnabled = !ResolveNoMsbSourceCache(args);
        MsbSourceCacheHits = 0;
        MsbSourceCacheMisses = 0;
        DonorEnemyByMapCache.Clear();
        Console.WriteLine(
            $"apply-map: parallel={parallel} max={maxParallel} inflight={mapInflight} "
            + $"dynamic={dynamicParallel} quiet={quiet} msb_source_cache={MsbSourceCacheEnabled} stream_io=True");

        var mapsWritten = 0;
        var slotsPatched = 0;
        var slotsMissing = 0;
        var mapsMissing = 0;
        var mapsWriteFailed = 0;

        var mapStudio = CnvMapStudioDir(gameDir);
        var mapStudioFingerprint = Directory.Exists(mapStudio)
            ? ComputeMapStudioFingerprint(mapStudio)
            : "";
        LoadCnvMapModelIndex(mapStudioFingerprint);

        var mapGroups = byMap.ToList();
        var totalMaps = mapGroups.Count;
        var warmMapFiles = CollectWarmMapFiles(mapGroups, entries);

        var registryLogs = new ConcurrentBag<string>();
        Console.WriteLine($"apply-map: building model registry ({warmMapFiles.Count} spawn-scope maps)…");
        Console.Out.Flush();
        var registrySw = ApplyProfileEnabled ? Stopwatch.StartNew() : null;
        var modelRegistry = BuildEnemyModelRegistry(gameDir, parallel, registryLogs, warmMapFiles);
        registrySw?.Stop();
        if (registrySw != null)
        {
            ApplyProfile.RegistryMs = registrySw.ElapsedMilliseconds;
        }
        foreach (var line in registryLogs)
        {
            Log(detailLog, line.Trim());
        }
        SupplementModelRegistryFromSpawnEntries(modelRegistry, entries);
        Console.WriteLine($"apply-map: model registry={modelRegistry.Count} entries");
        Console.Out.Flush();

        ThreadPool.GetMinThreads(out var minWorker, out var minIo);
        ThreadPool.SetMinThreads(
            Math.Max(minWorker, parallel),
            Math.Max(minIo, parallel));
        EnsureBhdFileIndex(gameDir);
        var warmSw = ApplyProfileEnabled ? Stopwatch.StartNew() : null;
        WarmSourceMapDiskCache(gameDir, warmMapFiles, parallel);
        warmSw?.Stop();
        if (warmSw != null)
        {
            ApplyProfile.CacheWarmMs = warmSw.ElapsedMilliseconds;
        }
        var mapWallSw = ApplyProfileEnabled ? Stopwatch.StartNew() : null;
        var mapResults = new ConcurrentBag<MapApplyResult>();
        if (dynamicParallel)
        {
            ApplyMapGroupsDynamic(
                mapGroups,
                parallel,
                maxParallel,
                totalMaps,
                gameDir,
                outDir,
                modelRegistry,
                quiet,
                mapResults);
        }
        else
        {
            var progress = new MapApplyProgress();
            Parallel.ForEach(
                mapGroups,
                new ParallelOptions { MaxDegreeOfParallelism = Math.Min(parallel, maxParallel) },
                group => ProcessMapGroupWork(
                    group,
                    gameDir,
                    outDir,
                    modelRegistry,
                    quiet,
                    mapResults,
                    progress,
                    totalMaps));
        }
        mapWallSw?.Stop();
        if (mapWallSw != null)
        {
            ApplyProfile.MapWallMs = mapWallSw.ElapsedMilliseconds;
        }

        foreach (var result in mapResults.OrderBy(r => r.MapId, StringComparer.Ordinal))
        {
            mapsWritten += result.MapsWritten;
            slotsPatched += result.SlotsPatched;
            slotsMissing += result.SlotsMissing;
            mapsMissing += result.MapsMissing;
            mapsWriteFailed += result.MapsWriteFailed;
            if (quiet)
            {
                continue;
            }

            foreach (var line in result.LogLines)
            {
                foreach (var sub in line.Split('\n'))
                {
                    var trimmed = sub.Trim();
                    if (!string.IsNullOrEmpty(trimmed))
                    {
                        Log(detailLog, trimmed);
                    }
                }
            }
        }

        var radahnLandings = mapResults.SelectMany(r => r.RadahnLandings).ToList();
        WriteRadahnLandingManifest(outDir, radahnLandings);
        if (radahnLandings.Count > 0)
        {
            Console.WriteLine($"apply-map: radahn_landing_slots={radahnLandings.Count}");
            Log(detailLog, $"radahn_landing_slots={radahnLandings.Count}");
        }

        if (MsbSourceCacheEnabled)
        {
            Console.WriteLine(
                $"apply-map: msb_source_cache hits={MsbSourceCacheHits} misses={MsbSourceCacheMisses}");
            Console.Out.Flush();
        }

        if (DonorEnemyByMapCache.Count > 0)
        {
            Console.WriteLine($"apply-map: donor_enemy_index maps={DonorEnemyByMapCache.Count}");
            Console.Out.Flush();
        }

        Console.WriteLine();
        Console.WriteLine(
            $"apply-map done: maps_written={mapsWritten} slots_patched={slotsPatched} "
            + $"missing_slots={slotsMissing} missing_maps={mapsMissing} write_failed={mapsWriteFailed} "
            + $"model_stubs={ModelEnsureStubCount} model_upgrades={ModelEnsureUpgradeCount}");
        Log(
            detailLog,
            $"apply_summary maps={mapsWritten} slots={slotsPatched} missing_slots={slotsMissing} "
            + $"missing_maps={mapsMissing} write_failed={mapsWriteFailed} model_stubs={ModelEnsureStubCount} "
            + $"model_upgrades={ModelEnsureUpgradeCount}");

        if (ModelEnsureStubCount > 0)
        {
            Console.Error.WriteLine(
                $"apply-map: WARNING model_stubs={ModelEnsureStubCount} (stub_sib_only — missing textures/AI risk)");
            Console.Error.Flush();
        }

        if (mapsWriteFailed > 0)
        {
            Console.Error.WriteLine(
                $"apply-map: WARNING write_failed={mapsWriteFailed} (see FAIL lines above)");
            Console.Error.Flush();
        }

        if (ApplyProfileEnabled)
        {
            ApplyProfile.PrintSummary(totalMaps, mapsWritten);
        }

        if (CnvMapModelIndexDirty)
        {
            TrySaveCnvMapModelIndexCache(CnvMapModelIndexFingerprint);
        }

        if (mapsWritten == 0)
        {
            WriteDetailLog(detailLog, "apply-map_failed=no_maps_written");
            return 1;
        }

        WriteMe3OverlayInstructions(gameDir, detailLog);
        Console.WriteLine("In-game: fully quit game -> Start_Convergence.bat -> test changed areas");

        var manifestPath = Path.Combine(outDir, "cnv_enemy_apply_manifest.txt");
        File.WriteAllText(manifestPath, detailLog.ToString(), Encoding.UTF8);
        Console.WriteLine($"Manifest: {manifestPath}");
        WriteDetailLog(detailLog, "apply-map_ok");
        return 0;
    }

    static List<SpawnMapEntry> ParseSpawnMap(string path)
    {
        var entries = new List<SpawnMapEntry>();
        foreach (var line in File.ReadAllLines(path, Encoding.UTF8))
        {
            var trimmed = line.Trim();
            if (string.IsNullOrEmpty(trimmed) || trimmed.StartsWith('#'))
            {
                continue;
            }

            if (trimmed.Contains('=') && !trimmed.StartsWith("#"))
            {
                continue;
            }

            string[] parts;
            if (trimmed.Contains('\t'))
            {
                parts = trimmed.Split('\t');
            }
            else
            {
                parts = trimmed.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
            }
            if (parts.Length < 10)
            {
                continue;
            }

            SpawnMapEntry entry;
            if (trimmed.Contains('\t'))
            {
                if (!int.TryParse(parts[9], out var runeTab)
                    || !int.TryParse(parts[8], out var charaTab)
                    || !int.TryParse(parts[7], out var thinkTab)
                    || !int.TryParse(parts[6], out var npcTab))
                {
                    continue;
                }

                entry = new SpawnMapEntry
                {
                    MapId = parts[0],
                    EntityName = parts[1],
                    SrcCat = parts[2],
                    TgtCat = parts[3],
                    TemplateId = parts[4],
                    Model = parts[5],
                    Npc = npcTab,
                    Think = thinkTab,
                    Chara = charaTab,
                    RuneAmount = runeTab,
                };
                if (parts.Length >= 19
                    && float.TryParse(parts[16], System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var posX)
                    && float.TryParse(parts[17], System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var posY)
                    && float.TryParse(parts[18], System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var posZ))
                {
                    entry.HasPosition = true;
                    entry.PosX = posX;
                    entry.PosY = posY;
                    entry.PosZ = posZ;
                }
            }
            else if (!int.TryParse(parts[^1], out var rune)
                || !int.TryParse(parts[^2], out var chara)
                || !int.TryParse(parts[^3], out var think)
                || !int.TryParse(parts[^4], out var npc))
            {
                continue;
            }
            else
            {
                entry = new SpawnMapEntry
                {
                    MapId = parts[0],
                    EntityName = string.Join(" ", parts[1..^8]),
                    SrcCat = parts[^8],
                    TgtCat = parts[^7],
                    TemplateId = parts[^6],
                    Model = parts[^5],
                    Npc = npc,
                    Think = think,
                    Chara = chara,
                    RuneAmount = rune,
                };
            }

            entries.Add(entry);
        }

        return entries;
    }

    sealed class MapApplyProgress
    {
        public int Done;
    }

    static void MaybeLogMapHeartbeat(int done, int totalMaps)
    {
        var now = Environment.TickCount64;
        if (now - Volatile.Read(ref LastMapHeartbeatMs) < 10000)
        {
            return;
        }

        lock (typeof(Program))
        {
            if (now - LastMapHeartbeatMs < 10000)
            {
                return;
            }

            LastMapHeartbeatMs = now;
        }

        Console.WriteLine($"apply-map: map_heartbeat done={done}/{totalMaps}");
        Console.Out.Flush();
    }

    static void ProcessMapGroupWork(
        IGrouping<string, SpawnMapEntry> group,
        string gameDir,
        string outDir,
        IReadOnlyDictionary<string, (string MapFile, MSBE.Model.Enemy Model)> modelRegistry,
        bool quiet,
        ConcurrentBag<MapApplyResult> mapResults,
        MapApplyProgress progress,
        int totalMaps)
    {
        MapApplyResult result;
        MapApplyInflight?.Wait();
        try
        {
            try
            {
                result = ApplySpawnMapGroup(group, gameDir, outDir, modelRegistry, quiet);
            }
            catch (Exception ex)
            {
                result = new MapApplyResult
                {
                    MapId = group.Key,
                    MapsWriteFailed = 1,
                    ConsoleLine = $"  FAIL {group.Key}: {ex.GetType().Name} — {ex.Message}",
                };
                result.LogLines.Add($"apply_exception={group.Key} {ex}");
                Console.Error.WriteLine(result.ConsoleLine);
            }
        }
        finally
        {
            MapApplyInflight?.Release();
        }

        mapResults.Add(result);
        if (!string.IsNullOrEmpty(result.ConsoleLine))
        {
            if (result.ConsoleLine.Contains("FAIL", StringComparison.Ordinal)
                || result.ConsoleLine.Contains("SKIP", StringComparison.Ordinal))
            {
                Console.Error.WriteLine(result.ConsoleLine);
            }
            else if (!quiet)
            {
                Console.WriteLine(result.ConsoleLine);
            }
        }

        var n = Interlocked.Increment(ref progress.Done);
        MaybeLogMapHeartbeat(progress.Done, totalMaps);
        var progressStep = totalMaps <= 80 ? 1 : totalMaps <= 200 ? 5 : 10;
        if (n == 1 || n == totalMaps || n % progressStep == 0)
        {
            Console.WriteLine($"apply-map: map_progress {n}/{totalMaps}");
            Console.Out.Flush();
        }
    }

    static void ApplyMapGroupsDynamic(
        IReadOnlyList<IGrouping<string, SpawnMapEntry>> mapGroups,
        int initialWorkers,
        int maxWorkers,
        int totalMaps,
        string gameDir,
        string outDir,
        IReadOnlyDictionary<string, (string MapFile, MSBE.Model.Enemy Model)> modelRegistry,
        bool quiet,
        ConcurrentBag<MapApplyResult> mapResults)
    {
        var queue = new ConcurrentQueue<IGrouping<string, SpawnMapEntry>>(mapGroups);
        var progress = new MapApplyProgress();
        var running = 0;
        var workers = 0;
        var cores = Math.Max(1, Environment.ProcessorCount);
        initialWorkers = Math.Clamp(initialWorkers, 1, maxWorkers);

        void StartWorker()
        {
            Interlocked.Increment(ref workers);
            Interlocked.Increment(ref running);
            Task.Run(() =>
            {
                try
                {
                    while (queue.TryDequeue(out var group))
                    {
                        ProcessMapGroupWork(
                            group,
                            gameDir,
                            outDir,
                            modelRegistry,
                            quiet,
                            mapResults,
                            progress,
                            totalMaps);
                    }
                }
                catch (Exception ex)
                {
                    Console.Error.WriteLine($"apply-map: worker_error {ex.GetType().Name} — {ex.Message}");
                    Console.Error.Flush();
                }
                finally
                {
                    Interlocked.Decrement(ref running);
                }
            });
        }

        for (var i = 0; i < initialWorkers; i++)
        {
            StartWorker();
        }

        var cpuMark = Process.GetCurrentProcess().TotalProcessorTime;
        var wallMark = Stopwatch.StartNew();
        var heartbeatMark = Stopwatch.StartNew();
        while (progress.Done < totalMaps)
        {
            Thread.Sleep(400);
            if (heartbeatMark.ElapsedMilliseconds >= 10000)
            {
                Console.WriteLine(
                    $"apply-map: map_heartbeat done={progress.Done}/{totalMaps} "
                    + $"queue={queue.Count} running={running}");
                Console.Out.Flush();
                heartbeatMark.Restart();
            }

            if (progress.Done >= totalMaps && running == 0)
            {
                break;
            }

            if (running == 0 && !queue.IsEmpty)
            {
                StartWorker();
                continue;
            }

            if (queue.IsEmpty && running == 0)
            {
                break;
            }

            var cpuNow = Process.GetCurrentProcess().TotalProcessorTime;
            var wallMs = Math.Max(1, wallMark.ElapsedMilliseconds);
            var util = (cpuNow - cpuMark).TotalMilliseconds / (wallMs * cores);
            var currentWorkers = Volatile.Read(ref workers);
            if (util < 0.60 && currentWorkers < maxWorkers && !queue.IsEmpty)
            {
                var add = Math.Min(Math.Max(cores * 2, 8), maxWorkers - currentWorkers);
                Console.WriteLine(
                    $"apply-map: dynamic_scale workers={currentWorkers}->{currentWorkers + add} "
                    + $"cpu_util={util:P0} queue={queue.Count}");
                Console.Out.Flush();
                for (var i = 0; i < add; i++)
                {
                    StartWorker();
                }

                cpuMark = cpuNow;
                wallMark.Restart();
            }
            else if (util > 0.95 && currentWorkers > cores * 2)
            {
                // saturated — avoid runaway thread count on next scale check only
                cpuMark = cpuNow;
                wallMark.Restart();
            }
        }

        while (running > 0)
        {
            Thread.Sleep(50);
        }

        Console.WriteLine($"apply-map: dynamic_done workers_peak={workers}");
        Console.Out.Flush();
    }

    sealed class ApplyProfileStats
    {
        public long RegistryMs;
        public long CacheWarmMs;
        public long MapWallMs;
        public long ReadMs;
        public long PatchMs;
        public long EnsureModelMs;
        public long TransplantMs;
        public long SlotLogMs;
        public long WriteKrakMs;
        public long CopyMs;
        public int MapsProfiled;
        readonly ConcurrentBag<(string MapId, int Slots, long TotalMs, long WriteMs)> _slowest = new();

        public void Reset()
        {
            RegistryMs = 0;
            CacheWarmMs = 0;
            MapWallMs = 0;
            ReadMs = 0;
            PatchMs = 0;
            EnsureModelMs = 0;
            TransplantMs = 0;
            SlotLogMs = 0;
            WriteKrakMs = 0;
            CopyMs = 0;
            MapsProfiled = 0;
            while (_slowest.TryTake(out _))
            {
            }
        }

        public void AddMap(
            string mapId,
            int slots,
            long readMs,
            long patchMs,
            long ensureModelMs,
            long transplantMs,
            long slotLogMs,
            long writeKrakMs,
            long copyMs)
        {
            Interlocked.Add(ref ReadMs, readMs);
            Interlocked.Add(ref PatchMs, patchMs);
            Interlocked.Add(ref EnsureModelMs, ensureModelMs);
            Interlocked.Add(ref TransplantMs, transplantMs);
            Interlocked.Add(ref SlotLogMs, slotLogMs);
            Interlocked.Add(ref WriteKrakMs, writeKrakMs);
            Interlocked.Add(ref CopyMs, copyMs);
            Interlocked.Increment(ref MapsProfiled);
            var total = readMs + patchMs + slotLogMs + writeKrakMs + copyMs;
            _slowest.Add((mapId, slots, total, writeKrakMs + copyMs));
        }

        public void PrintSummary(int totalMaps, int mapsWritten)
        {
            var cpuSum = ReadMs + PatchMs + SlotLogMs + WriteKrakMs + CopyMs;
            var denom = Math.Max(1, cpuSum);
            Console.WriteLine(
                $"apply-map: profile setup registry_ms={RegistryMs} cache_warm_ms={CacheWarmMs}");
            Console.WriteLine(
                $"apply-map: profile maps wall_ms={MapWallMs} maps={MapsProfiled} written={mapsWritten}");
            Console.WriteLine(
                $"apply-map: profile phase_ms read={ReadMs} patch={PatchMs} "
                + $"ensure_model={EnsureModelMs} transplant={TransplantMs} "
                + $"slotlog={SlotLogMs} write_krak={WriteKrakMs} copy_msbe={CopyMs} cpu_sum={cpuSum}");
            Console.WriteLine(
                $"apply-map: profile pct read={ReadMs * 100.0 / denom:F1}% "
                + $"patch={PatchMs * 100.0 / denom:F1}% "
                + $"slotlog={SlotLogMs * 100.0 / denom:F1}% "
                + $"write_krak={WriteKrakMs * 100.0 / denom:F1}% "
                + $"copy={CopyMs * 100.0 / denom:F1}%");
            if (MapWallMs > 0)
            {
                Console.WriteLine(
                    $"apply-map: profile parallel_efficiency cpu_sum/wall={cpuSum * 100.0 / MapWallMs:F0}% "
                    + $"(>{100}% = threads overlap; low = I/O wait)");
            }

            foreach (var row in _slowest.OrderByDescending(r => r.TotalMs).Take(8))
            {
                Console.WriteLine(
                    $"apply-map: profile slow map={row.MapId} slots={row.Slots} "
                    + $"total_ms={row.TotalMs} write_ms={row.WriteMs}");
            }

            Console.Out.Flush();
        }
    }

    static string MapModelIndexCachePath(string source) =>
        Path.Combine(
            ResolveRingrandomRoot(),
            "cnv_randomizer",
            "cache",
            "msb_map_model_index",
            source,
            "map_model_names.json");

    sealed class MapModelIndexCacheFile
    {
        public string Schema { get; set; } = "msb_map_model_index_v1";
        public string Source { get; set; } = MsbMapModelIndexSource.Cnv;
        public string Fingerprint { get; set; } = "";
        public Dictionary<string, List<string>> Maps { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    }

    static void LoadCnvMapModelIndex(string fingerprint)
    {
        CnvMapModelIndexFingerprint = fingerprint;
        CnvMapModelIndexDirty = false;
        CnvMapModelIndex = TryLoadMapModelIndexCache(MsbMapModelIndexSource.Cnv, fingerprint)
            ?? new ConcurrentDictionary<string, HashSet<string>>(StringComparer.OrdinalIgnoreCase);
        Console.WriteLine(
            $"apply-map: map_model_index source={MsbMapModelIndexSource.Cnv} maps={CnvMapModelIndex.Count}");
        Console.Out.Flush();
    }

    static ConcurrentDictionary<string, HashSet<string>>? TryLoadMapModelIndexCache(
        string source,
        string fingerprint)
    {
        var cachePath = MapModelIndexCachePath(source);
        if (!File.Exists(cachePath) || string.IsNullOrWhiteSpace(fingerprint))
        {
            return null;
        }

        try
        {
            var data = JsonSerializer.Deserialize<MapModelIndexCacheFile>(File.ReadAllText(cachePath, Encoding.UTF8));
            if (data == null
                || !string.Equals(data.Schema, "msb_map_model_index_v1", StringComparison.Ordinal)
                || !string.Equals(data.Source, source, StringComparison.OrdinalIgnoreCase)
                || !string.Equals(data.Fingerprint, fingerprint, StringComparison.Ordinal))
            {
                return null;
            }

            var loaded = new ConcurrentDictionary<string, HashSet<string>>(StringComparer.OrdinalIgnoreCase);
            foreach (var (mapId, names) in data.Maps)
            {
                if (string.IsNullOrWhiteSpace(mapId) || names == null || names.Count == 0)
                {
                    continue;
                }

                loaded[mapId] = new HashSet<string>(names, StringComparer.OrdinalIgnoreCase);
            }

            return loaded.Count > 0 ? loaded : null;
        }
        catch
        {
            return null;
        }
    }

    static void TrySaveCnvMapModelIndexCache(string fingerprint)
    {
        if (string.IsNullOrWhiteSpace(fingerprint) || CnvMapModelIndex.IsEmpty)
        {
            return;
        }

        try
        {
            var cachePath = MapModelIndexCachePath(MsbMapModelIndexSource.Cnv);
            var payload = new MapModelIndexCacheFile
            {
                Source = MsbMapModelIndexSource.Cnv,
                Fingerprint = fingerprint,
                Maps = CnvMapModelIndex.ToDictionary(
                    kv => kv.Key,
                    kv => kv.Value.OrderBy(n => n, StringComparer.OrdinalIgnoreCase).ToList(),
                    StringComparer.OrdinalIgnoreCase),
            };
            Directory.CreateDirectory(Path.GetDirectoryName(cachePath)!);
            File.WriteAllText(
                cachePath,
                JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = false }),
                Encoding.UTF8);
            CnvMapModelIndexDirty = false;
            Console.WriteLine(
                $"apply-map: map_model_index saved source={MsbMapModelIndexSource.Cnv} maps={payload.Maps.Count}");
            Console.Out.Flush();
        }
        catch
        {
            // cache write is optional
        }
    }

    static HashSet<string> BuildMapModelNameSet(MSBE msb)
    {
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var model in msb.Models.Enemies)
        {
            if (model is MSBE.Model.Enemy enemyModel && !string.IsNullOrWhiteSpace(enemyModel.Name))
            {
                names.Add(enemyModel.Name);
            }
        }

        return names;
    }

    static HashSet<string> GetMapModelNameSetForApply(string mapId, MSBE msb)
    {
        // Apply hot path: only names actually on this MSB (never trust stale JSON alone).
        var liveNames = BuildMapModelNameSet(msb);
        RecordMapModelNames(mapId, liveNames);
        return liveNames;
    }

    static void MarkCnvMapModelIndexDirty()
    {
        CnvMapModelIndexDirty = true;
    }

    static void RecordMapModelNamesFromMsb(string mapId, MSBE msb)
    {
        var names = BuildMapModelNameSet(msb);
        RecordMapModelNames(mapId, names);
    }

    static void RecordMapModelNames(string mapId, IEnumerable<string> names)
    {
        var changed = false;
        CnvMapModelIndex.AddOrUpdate(
            mapId,
            _ =>
            {
                changed = true;
                return new HashSet<string>(names, StringComparer.OrdinalIgnoreCase);
            },
            (_, existing) =>
            {
                foreach (var name in names)
                {
                    if (existing.Add(name))
                    {
                        changed = true;
                    }
                }

                return existing;
            });
        if (changed)
        {
            CnvMapModelIndexDirty = true;
        }
    }

    static string ModelRegistryCachePath() =>
        Path.Combine(
            ResolveRingrandomRoot(),
            "cnv_randomizer",
            "cache",
            "enemy_model_registry.json");

    static string ComputeMapStudioFingerprint(string mapStudio)
    {
        long maxTicks = 0;
        var count = 0;
        foreach (var path in Directory.EnumerateFiles(mapStudio, "*.msb.dcx"))
        {
            count++;
            var ticks = File.GetLastWriteTimeUtc(path).Ticks;
            if (ticks > maxTicks)
            {
                maxTicks = ticks;
            }
        }

        return $"{count}:{maxTicks}";
    }

    static string MsbSourceCacheRoot() =>
        Path.Combine(
            ResolveRingrandomRoot(),
            "cnv_randomizer",
            "cache",
            "msb_source");

    static string MsbSourceCacheFingerprint(string gameDir) =>
        ComputeMapStudioFingerprint(CnvMapStudioDir(gameDir)).Replace(':', '_');

    static string MsbSourceCacheFilePath(string gameDir, string mapFileName)
    {
        var safeName = mapFileName.Replace(Path.DirectorySeparatorChar, '_');
        return Path.Combine(
            MsbSourceCacheRoot(),
            MsbSourceCacheFingerprint(gameDir),
            safeName + ".decomp");
    }

    static void TryWriteMsbSourceCache(string gameDir, string mapFileName, byte[] sourceBytes)
    {
        try
        {
            var decomp = DCX.Is(sourceBytes) ? DCX.Decompress(sourceBytes) : sourceBytes;
            var cachePath = MsbSourceCacheFilePath(gameDir, mapFileName);
            if (File.Exists(cachePath))
            {
                return;
            }

            var lockObj = MsbSourceCacheFileLocks.GetOrAdd(cachePath, _ => new object());
            lock (lockObj)
            {
                if (File.Exists(cachePath))
                {
                    return;
                }

                Directory.CreateDirectory(Path.GetDirectoryName(cachePath)!);
                File.WriteAllBytes(cachePath, decomp);
            }
        }
        catch
        {
            // optional cache
        }
    }

    static void EnsureBhdFileIndex(string gameDir)
    {
        if (BhdFileIndex != null)
        {
            return;
        }

        lock (BhdFileIndexLock)
        {
            if (BhdFileIndex != null)
            {
                return;
            }

            var index = new Dictionary<ulong, (string, BHD5.FileHeader)>();
            foreach (var bhdName in new[] { "Data0.bhd", "Data1.bhd", "Data2.bhd", "Data3.bhd", "DLC.bhd" })
            {
                var bhdPath = Path.Combine(gameDir, bhdName);
                if (!File.Exists(bhdPath))
                {
                    continue;
                }

                try
                {
                    using var bhdStream = File.OpenRead(bhdPath);
                    var bhd = BHD5.Read(bhdStream, BHD5.Game.EldenRing);
                    var bdtPath = Path.ChangeExtension(bhdPath, ".bdt");
                    foreach (var bucket in bhd.Buckets)
                    {
                        for (var i = 0; i < bucket.Count; i++)
                        {
                            var header = bucket[i];
                            index[header.FileNameHash] = (bdtPath, header);
                        }
                    }
                }
                catch
                {
                    // skip broken archive
                }
            }

            BhdFileIndex = index;
            Console.WriteLine($"apply-map: bhd_index entries={index.Count}");
            Console.Out.Flush();
        }
    }

    static void TryWriteMsbSourceCacheFromMod(string gameDir, string mapFileName, string modPath)
    {
        if (File.Exists(MsbSourceCacheFilePath(gameDir, mapFileName)))
        {
            return;
        }

        try
        {
            var bytes = File.ReadAllBytes(modPath);
            TryWriteMsbSourceCache(gameDir, mapFileName, bytes);
        }
        catch
        {
            // optional cache
        }
    }

    static void WarmSourceMapDiskCache(string gameDir, IReadOnlyList<string> mapFiles, int parallel)
    {
        var total = mapFiles.Count;
        if (total == 0)
        {
            return;
        }

        Console.WriteLine($"apply-map: cache_warm {total} source maps (stream/disk)…");
        Console.Out.Flush();
        var warmed = 0;
        Parallel.ForEach(
            mapFiles,
            new ParallelOptions { MaxDegreeOfParallelism = parallel },
            mapFile =>
            {
                var mapId = mapFile.Replace(".msb.dcx", "", StringComparison.OrdinalIgnoreCase);
                var cachePath = MsbSourceCacheFilePath(gameDir, mapFile);
                MSBE? msb = null;
                if (!File.Exists(cachePath))
                {
                    msb = TryReadMsbSafe(gameDir, mapFile, new StringBuilder());
                }
                else if (!CnvMapModelIndex.ContainsKey(mapId))
                {
                    msb = TryReadMsbFromPath(cachePath, new StringBuilder(), mapFile);
                }

                if (msb != null)
                {
                    RecordMapModelNamesFromMsb(mapId, msb);
                }

                var n = Interlocked.Increment(ref warmed);
                if (n == 1 || n == total || n % 25 == 0)
                {
                    Console.WriteLine($"apply-map: prefetch_progress {n}/{total}");
                    Console.Out.Flush();
                }
            });
        Console.WriteLine($"apply-map: cache_warm done maps={total}");
        Console.Out.Flush();
    }

    static void TryWriteOutputMsbeCopy(string outMsb, string outMsbe)
    {
        try
        {
            File.Copy(outMsb, outMsbe, overwrite: true);
        }
        catch (Exception ex)
        {
            throw new IOException($"msbe_copy_failed {outMsbe}: {ex.Message}", ex);
        }
    }

    sealed class RegistryCacheEntry
    {
        public string Name { get; set; } = "";
        public string MapFile { get; set; } = "";
        public string SibPath { get; set; } = "";
    }

    sealed class RegistryCacheFile
    {
        public int Version { get; set; } = 2;
        public string Fingerprint { get; set; } = "";
        public List<RegistryCacheEntry> Entries { get; set; } = new();
    }

    static bool TryLoadModelRegistryCache(
        string cachePath,
        string fingerprint,
        string gameDir,
        out Dictionary<string, (string MapFile, MSBE.Model.Enemy Model)> registry)
    {
        registry = new Dictionary<string, (string, MSBE.Model.Enemy)>(StringComparer.OrdinalIgnoreCase);
        if (!File.Exists(cachePath))
        {
            return false;
        }

        try
        {
            var data = JsonSerializer.Deserialize<RegistryCacheFile>(
                File.ReadAllText(cachePath, Encoding.UTF8));
            if (data == null || data.Version < 2)
            {
                return false;
            }
            if (!string.Equals(data.Fingerprint, fingerprint, StringComparison.Ordinal))
            {
                return false;
            }
            if (data.Entries == null || data.Entries.Count == 0)
            {
                return false;
            }

            var byMap = data.Entries
                .Where(e =>
                    !string.IsNullOrWhiteSpace(e.Name)
                    && !string.IsNullOrWhiteSpace(e.MapFile))
                .GroupBy(e => e.MapFile, StringComparer.OrdinalIgnoreCase)
                .ToList();

            var loaded = new ConcurrentDictionary<string, (string, MSBE.Model.Enemy)>(
                StringComparer.OrdinalIgnoreCase);
            Parallel.ForEach(
                byMap,
                new ParallelOptions { MaxDegreeOfParallelism = Environment.ProcessorCount },
                group =>
                {
                    var msb = TryReadMsbSafe(gameDir, group.Key, new StringBuilder());
                    if (msb == null)
                    {
                        return;
                    }

                    var modelByName = new Dictionary<string, MSBE.Model.Enemy>(
                        StringComparer.OrdinalIgnoreCase);
                    foreach (var model in msb.Models.Enemies)
                    {
                        if (model is MSBE.Model.Enemy enemyModel
                            && !string.IsNullOrWhiteSpace(enemyModel.Name))
                        {
                            modelByName.TryAdd(enemyModel.Name, enemyModel);
                        }
                    }

                    foreach (var entry in group)
                    {
                        if (modelByName.TryGetValue(entry.Name, out var enemyModel))
                        {
                            loaded.TryAdd(entry.Name, (group.Key, enemyModel));
                        }
                    }
                });

            foreach (var kv in loaded)
            {
                registry[kv.Key] = kv.Value;
            }

            return registry.Count > 0;
        }
        catch
        {
            registry = new Dictionary<string, (string, MSBE.Model.Enemy)>(
                StringComparer.OrdinalIgnoreCase);
            return false;
        }
    }

    static void TrySaveModelRegistryCache(
        string cachePath,
        string fingerprint,
        Dictionary<string, (string MapFile, MSBE.Model.Enemy Model)> registry)
    {
        if (registry.Count == 0)
        {
            return;
        }

        try
        {
            var dir = Path.GetDirectoryName(cachePath);
            if (!string.IsNullOrEmpty(dir))
            {
                Directory.CreateDirectory(dir);
            }

            var payload = new RegistryCacheFile
            {
                Version = 2,
                Fingerprint = fingerprint,
                Entries = registry
                    .Select(kv => new RegistryCacheEntry
                    {
                        Name = kv.Key,
                        MapFile = kv.Value.MapFile,
                    })
                    .OrderBy(e => e.MapFile, StringComparer.OrdinalIgnoreCase)
                    .ThenBy(e => e.Name, StringComparer.OrdinalIgnoreCase)
                    .ToList(),
            };
            File.WriteAllText(
                cachePath,
                JsonSerializer.Serialize(
                    payload,
                    new JsonSerializerOptions { WriteIndented = false }),
                Encoding.UTF8);
        }
        catch
        {
            // best-effort cache
        }
    }

    static void EnsureModelsReferencedByEnemyParts(
        MSBE msb,
        string gameDir,
        StringBuilder detailLog,
        IReadOnlyDictionary<string, (string MapFile, MSBE.Model.Enemy Model)>? modelRegistry,
        ISet<string>? mapModelNames)
    {
        var needed = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var part in msb.Parts.Enemies)
        {
            if (!string.IsNullOrWhiteSpace(part.ModelName))
            {
                needed.Add(part.ModelName);
            }
        }

        foreach (var modelName in needed)
        {
            if (mapModelNames != null && mapModelNames.Contains(modelName))
            {
                continue;
            }

            EnsureEnemyModel(
                msb,
                modelName,
                gameDir,
                detailLog,
                quiet: true,
                modelRegistry: modelRegistry,
                mapModelNames: mapModelNames);
        }
    }

    sealed class MapApplyResult
    {
        public int MapsWritten;
        public int SlotsPatched;
        public int SlotsMissing;
        public int SlotCompatRejects;
        public int MapsMissing;
        public int MapsWriteFailed;
        public string MapId = "";
        public string ConsoleLine = "";
        public List<string> LogLines = new();
        public List<RadahnLandingRecord> RadahnLandings { get; } = new();
    }

    sealed class RadahnLandingRecord
    {
        public string MapId { get; set; } = "";
        public string EntityName { get; set; } = "";
        public uint BossEntityId { get; set; }
        public uint HelperEntityId { get; set; }
        public float PosX { get; set; }
        public float PosY { get; set; }
        public float PosZ { get; set; }
    }

    static bool TryInjectRadahnLandingHelper(
        MSBE msb,
        MSBE.Part.Enemy boss,
        string mapId,
        string slotName,
        string gameDir,
        StringBuilder detailLog,
        out RadahnLandingRecord record)
    {
        record = new RadahnLandingRecord();
        var bossEntityId = boss.EntityID;
        if (bossEntityId == 0)
        {
            bossEntityId = ResolveBossEntityIdFromIndex(mapId, slotName, detailLog);
            if (bossEntityId == 0)
            {
                Log(detailLog, $"radahn_landing_skip map={mapId} slot={slotName} reason=missing_entity_id");
                return false;
            }
        }

        var existing = msb.Parts.Enemies.FirstOrDefault(
            e => e.Name.StartsWith("cnv_radahn_helper_", StringComparison.OrdinalIgnoreCase)
                && bossEntityId > 0
                && e.EntityID > bossEntityId
                && e.EntityID < bossEntityId + 600);
        if (existing != null)
        {
            record = new RadahnLandingRecord
            {
                MapId = mapId,
                EntityName = slotName,
                BossEntityId = bossEntityId,
                HelperEntityId = existing.EntityID,
                PosX = boss.Position.X,
                PosY = boss.Position.Y,
                PosZ = boss.Position.Z,
            };
            Log(
                detailLog,
                $"radahn_landing_reuse map={mapId} slot={slotName} boss={bossEntityId} helper={existing.EntityID}");
            return true;
        }

        var template = ResolveRadahnHelperTemplate(gameDir, detailLog);
        if (template == null)
        {
            return false;
        }

        var helperEntityId = PickRadahnHelperEntityId(msb, bossEntityId);
        EnsureEnemyModel(
            msb,
            template.ModelName,
            gameDir,
            detailLog,
            quiet: true,
            modelRegistry: null,
            mapModelNames: null);
        var helper = BuildRadahnLandingHelper(template, boss, slotName, helperEntityId);
        msb.Parts.Enemies.Add(helper);
        record = new RadahnLandingRecord
        {
            MapId = mapId,
            EntityName = slotName,
            BossEntityId = bossEntityId,
            HelperEntityId = helperEntityId,
            PosX = boss.Position.X,
            PosY = boss.Position.Y,
            PosZ = boss.Position.Z,
        };
        Log(
            detailLog,
            $"radahn_landing_helper map={mapId} slot={slotName} boss={bossEntityId} helper={helperEntityId}");
        return true;
    }

    static void WriteRadahnLandingManifest(string outDir, IReadOnlyList<RadahnLandingRecord> records)
    {
        var path = Path.Combine(outDir, "cnv_radahn_landing.json");
        if (records.Count == 0)
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }

            return;
        }

        var json = JsonSerializer.Serialize(
            records,
            new JsonSerializerOptions { WriteIndented = true });
        File.WriteAllText(path, json, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
    }

    static MapApplyResult ApplySpawnMapGroup(
        IGrouping<string, SpawnMapEntry> group,
        string gameDir,
        string outDir,
        IReadOnlyDictionary<string, (string MapFile, MSBE.Model.Enemy Model)> modelRegistry,
        bool quiet)
    {
        var result = new MapApplyResult { MapId = group.Key };
        var mapId = group.Key;
        var mapFile = $"{mapId}.msb.dcx";
        var localLog = new StringBuilder();
        long readMs = 0, patchMs = 0, ensureModelMs = 0, transplantMs = 0, slotLogMs = 0, writeKrakMs = 0, copyMs = 0;
        var readSw = ApplyProfileEnabled ? Stopwatch.StartNew() : null;
        var msb = TryReadMsbSafe(gameDir, mapFile, localLog);
        if (readSw != null)
        {
            readSw.Stop();
            readMs = readSw.ElapsedMilliseconds;
        }
        if (msb == null)
        {
            result.MapsMissing = 1;
            result.ConsoleLine = $"  SKIP {mapId}: cannot read CNV MSB {mapFile}";
            result.LogLines.Add($"apply_skip_map={mapId} reason=missing_msb");
            return result;
        }

        var enemies = msb.Parts.Enemies;
        var enemyByName = BuildEnemyLookupByName(enemies, mapId, localLog, result);
        var mapModelNames = GetMapModelNameSetForApply(mapId, msb);
        var mapPatched = 0;
        var modelsEnsuredOnMap = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var validCollisionParts = CollectCollisionPartNames(msb);
        StringBuilder? mapSlotLog = quiet ? null : new StringBuilder();

        if (mapSlotLog != null)
        {
            mapSlotLog.AppendLine($"# apply-map slots map={mapId}");
        }

        var patchSw = ApplyProfileEnabled ? Stopwatch.StartNew() : null;
        foreach (var entry in group)
        {
            if (!enemyByName.TryGetValue(entry.EntityName, out var target))
            {
                result.SlotsMissing++;
                result.LogLines.Add($"apply_missing_slot={mapId}:{entry.EntityName}");
                mapSlotLog?.AppendLine($"missing {entry.EntityName}");
                continue;
            }

            if (string.Equals(entry.TemplateId, "cnv:suppress_mount", StringComparison.OrdinalIgnoreCase)
                || string.Equals(entry.TemplateId, "cnv:suppress_decorative", StringComparison.OrdinalIgnoreCase))
            {
                var suppressRecord = new PatchRecord
                {
                    Name = target.Name,
                    EntityId = target.EntityID,
                };
                ApplyMountSuppress(target, suppressRecord);
                mapPatched++;
                var suppressKind = string.Equals(entry.TemplateId, "cnv:suppress_decorative", StringComparison.OrdinalIgnoreCase)
                    ? "suppress_decorative"
                    : "suppress_mount";
                mapSlotLog?.AppendLine(
                    $"{suppressKind} {entry.EntityName} before={suppressRecord.BeforeModel} after={suppressRecord.AfterModel}");
                if (!quiet)
                {
                    result.LogLines.Add(
                        $"apply_{suppressKind}={mapId}:{entry.EntityName} model={suppressRecord.BeforeModel}");
                }
                continue;
            }

            var demount = entry.TemplateId.EndsWith("|demount", StringComparison.OrdinalIgnoreCase);
            var donorMapId = ResolveDonorMapId(entry.TemplateId, entry.MapId);
            if (modelsEnsuredOnMap.Add(entry.Model))
            {
                var ensureSw = ApplyProfileEnabled ? Stopwatch.StartNew() : null;
                EnsureEnemyModel(
                    msb,
                    entry.Model,
                    gameDir,
                    localLog,
                    quiet: true,
                    preferDonorMapId: donorMapId,
                    modelRegistry: modelRegistry,
                    mapModelNames: mapModelNames);
                if (ensureSw != null)
                {
                    ensureSw.Stop();
                    ensureModelMs += ensureSw.ElapsedMilliseconds;
                }
            }

            var donorPart = ResolveDonorMsbPart(
                gameDir,
                entry.TemplateId,
                entry.MapId,
                entry.Model,
                localLog);

            MSBE.Part.Enemy donor;
            if (donorPart != null)
            {
                donor = donorPart;
            }
            else
            {
                donor = new MSBE.Part.Enemy
                {
                    Name = entry.EntityName,
                    ModelName = entry.Model,
                    NPCParamID = entry.Npc,
                    ThinkParamID = entry.Think,
                    CharaInitID = entry.Chara,
                };
            }

            var record = new PatchRecord
            {
                Name = target.Name,
                EntityId = target.EntityID,
            };

            if (TryGetSlotCompatRejectReason(target, entry.TemplateId, out var slotCompatReject))
            {
                result.SlotCompatRejects++;
                var rejectLine =
                    $"slot_compat_reject map={mapId} entity={entry.EntityName} "
                    + $"slot_class={ResolveSlotApplyClass(target)} template={entry.TemplateId} reason={slotCompatReject}";
                result.LogLines.Add(rejectLine);
                mapSlotLog?.AppendLine(rejectLine);
                if (!quiet)
                {
                    result.LogLines.Add($"apply_slot_compat_reject {mapId}:{entry.EntityName} reason={slotCompatReject}");
                }
                continue;
            }

            var transplantSw = ApplyProfileEnabled ? Stopwatch.StartNew() : null;
            var forceDonorMsb = ResolveForceDonorMsbOrAuto(target, entry.TemplateId);
            ApplyDonorTransplant(
                target,
                donor,
                record,
                demount,
                donorBehaviorRef: donorPart,
                forceDonorMsb: forceDonorMsb,
                slotMapId: mapId,
                slotEntityName: entry.EntityName,
                donorTemplateId: entry.TemplateId,
                validCollisionParts: validCollisionParts);
            ApplySpawnMapParamIds(target, entry, record);
            if (entry.HasPosition)
            {
                target.Position = new System.Numerics.Vector3(entry.PosX, entry.PosY, entry.PosZ);
                target.WalkRouteName = "";
                target.BackupEventAnimID = -1;
                record.RouteCleared = true;
                record.WalkRouteKept = false;
            }
            if (transplantSw != null)
            {
                transplantSw.Stop();
                transplantMs += transplantSw.ElapsedMilliseconds;
            }
            if (IsRadahnDonorModel(entry.Model)
                && TryInjectRadahnLandingHelper(
                    msb,
                    target,
                    mapId,
                    entry.EntityName,
                    gameDir,
                    localLog,
                    out var landingRecord))
            {
                result.RadahnLandings.Add(landingRecord);
            }
            mapPatched++;

            if (!quiet)
            {
                var patchLine =
                    $"patch {entry.EntityName} before={record.BeforeModel} npc={record.BeforeNpc} think={record.BeforeThink} "
                    + $"after={record.AfterModel} npc={record.AfterNpc} think={record.AfterThink} "
                    + $"template={entry.TemplateId} chara={entry.Chara} rune={entry.RuneAmount} "
                    + $"force_donor={record.ForceDonorMsb} speffect_cleared={record.SpeffectCleared} "
                    + $"walk_route_kept={record.WalkRouteKept} route_cleared={record.RouteCleared} "
                    + $"slot_state_cleared={record.SlotStateCleared}";
                result.LogLines.Add($"apply_patch {mapId} {patchLine}");
                mapSlotLog?.AppendLine(patchLine);
            }
        }
        if (patchSw != null)
        {
            patchSw.Stop();
            patchMs = patchSw.ElapsedMilliseconds;
        }

        if (mapPatched == 0)
        {
            if (localLog.Length > 0)
            {
                result.LogLines.Add(localLog.ToString());
            }
            return result;
        }

        if (mapSlotLog != null)
        {
            var mapSlotLogPath = Path.Combine(outDir, $"cnv_enemy_apply_slots_{mapId}.txt");
            var slotLogSw = ApplyProfileEnabled ? Stopwatch.StartNew() : null;
            File.WriteAllText(mapSlotLogPath, mapSlotLog.ToString(), Encoding.UTF8);
            if (slotLogSw != null)
            {
                slotLogSw.Stop();
                slotLogMs = slotLogSw.ElapsedMilliseconds;
            }
            result.LogLines.Add($"apply_slot_log={mapSlotLogPath} lines={mapPatched}");
        }

        EnsureModelsReferencedByEnemyParts(
            msb,
            gameDir,
            localLog,
            modelRegistry,
            mapModelNames);

        var outMsb = Path.Combine(outDir, mapFile);
        var outMsbe = Path.Combine(outDir, mapFile.Replace(".msb.dcx", ".msbe.dcx", StringComparison.OrdinalIgnoreCase));
        try
        {
            var writeSw = ApplyProfileEnabled ? Stopwatch.StartNew() : null;
            WriteOverlayMsbPair(msb, outMsb, outMsbe, localLog);
            if (writeSw != null)
            {
                writeSw.Stop();
                writeKrakMs = writeSw.ElapsedMilliseconds;
                copyMs = writeKrakMs;
            }

            result.MapsWritten = 1;
            result.SlotsPatched = mapPatched;
            result.ConsoleLine = $"  {mapId}: patched {mapPatched} -> {outMsb}";
            result.LogLines.Add($"apply_wrote={outMsb} patched={mapPatched}");
        }
        catch (Exception ex)
        {
            TryDeleteFileIfExists(outMsb);
            TryDeleteFileIfExists(outMsbe);
            var slotLogPath = Path.Combine(outDir, $"cnv_enemy_apply_slots_{mapId}.txt");
            TryDeleteFileIfExists(slotLogPath);
            result.MapsWriteFailed = 1;
            result.ConsoleLine = $"  FAIL {mapId}: write MSB — {ex.Message}";
            result.LogLines.Add($"apply_write_fail={mapId} error={ex.Message}");
        }

        if (localLog.Length > 0)
        {
            result.LogLines.Add(localLog.ToString());
        }

        if (ApplyProfileEnabled && mapPatched > 0)
        {
            ApplyProfile.AddMap(
                mapId,
                mapPatched,
                readMs,
                patchMs,
                ensureModelMs,
                transplantMs,
                slotLogMs,
                writeKrakMs,
                copyMs);
        }

        return result;
    }

    sealed class SpawnMapEntry
    {
        public string MapId { get; init; } = "";
        public string EntityName { get; init; } = "";
        public string SrcCat { get; init; } = "";
        public string TgtCat { get; init; } = "";
        public string TemplateId { get; init; } = "";
        public string Model { get; init; } = "";
        public int Npc { get; init; }
        public int Think { get; init; }
        public int Chara { get; init; }
        public int RuneAmount { get; init; }
        public bool HasPosition { get; set; }
        public float PosX { get; set; }
        public float PosY { get; set; }
        public float PosZ { get; set; }
    }

    static MSBE.Model.Enemy? FindEnemyModelOnMsb(MSBE msb, string modelName) =>
        msb.Models.Enemies.FirstOrDefault(
            m => string.Equals(m.Name, modelName, StringComparison.OrdinalIgnoreCase))
        as MSBE.Model.Enemy;
    static MSBE.Model.Enemy CreateEnemyModelStub(string modelName) =>
        new()
        {
            Name = modelName,
            SibPath = EnemyModelSibPath(modelName),
        };
    static DCX.CompressionInfo MsbeWriteCompression(MSBE msb) =>
        msb.Compression.Type is not (DCX.Type.Unknown or DCX.Type.None)
            ? msb.Compression
            : new DCX.DcxKrakCompressionInfo(DCX.KrakCompressionPreset.EldenRing);
    static (string MapPath, MSBE.Model.Enemy Model)? FindEnemyModelEntry(
        string gameDir,
        string modelName,
        StringBuilder detailLog,
        string? preferDonorMapId = null)
    {
        if (ModelRegistryMissCache.Contains(modelName))
        {
            return null;
        }

        var mapStudio = CnvMapStudioDir(gameDir);
        var preferredMaps = new List<string>();
        if (IsValidDonorMapId(preferDonorMapId))
        {
            preferredMaps.Add($"{preferDonorMapId}.msb.dcx");
            preferredMaps.Add($"{preferDonorMapId}.msbe.dcx");
        }

        var tried = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var fileName in preferredMaps)
        {
            if (!tried.Add(fileName))
            {
                continue;
            }

            var donor = TryReadMsbSafe(gameDir, fileName, detailLog);
            var model = donor?.Models.Enemies.FirstOrDefault(m => m.Name == modelName);
            if (model is MSBE.Model.Enemy enemyModel)
            {
                Log(detailLog, $"model_donor={fileName}");
                return (fileName, enemyModel);
            }
        }

        if (ModelRegistryScopedToSpawn)
        {
            ModelRegistryMissCache.Add(modelName);
            Log(detailLog, $"model_donor=NOT_FOUND scoped=true tried={tried.Count}");
            return null;
        }

        preferredMaps.AddRange(
        [
            "m60_42_36_00.msb.dcx",
            "m60_41_51_00.msb.dcx",
            $"{MapId}.msb.dcx",
            $"{MapId}.msbe.dcx",
        ]);

        foreach (var fileName in preferredMaps)
        {
            if (!tried.Add(fileName))
            {
                continue;
            }

            var donor = TryReadMsbSafe(gameDir, fileName, detailLog);
            var model = donor?.Models.Enemies.FirstOrDefault(m => m.Name == modelName);
            if (model is MSBE.Model.Enemy enemyModel)
            {
                Log(detailLog, $"model_donor={fileName}");
                return (fileName, enemyModel);
            }
        }

        if (!ModelRegistryScopedToSpawn && Directory.Exists(mapStudio))
        {
            foreach (var path in Directory.EnumerateFiles(mapStudio, "*.msb.dcx"))
            {
                var fileName = Path.GetFileName(path);
                if (!tried.Add(fileName))
                {
                    continue;
                }

                var donor = TryReadMsbSafe(gameDir, fileName, detailLog);
                var model = donor?.Models.Enemies.FirstOrDefault(m => m.Name == modelName);
                if (model is MSBE.Model.Enemy enemyModel)
                {
                    Log(detailLog, $"model_donor={fileName}");
                    return (fileName, enemyModel);
                }
            }
        }

        if (ModelRegistryScopedToSpawn)
        {
            ModelRegistryMissCache.Add(modelName);
        }

        Log(detailLog, $"model_donor=NOT_FOUND tried={tried.Count}");
        return null;
    }
    static long LastMapHeartbeatMs;
    static class MsbMapModelIndexSource
    {
        public const string Cnv = "cnv";
        // Reserved: public const string Vanilla = "vanilla";
    }
    static MSBE.Part.Enemy BuildRadahnLandingHelper(
        MSBE.Part.Enemy template,
        MSBE.Part.Enemy boss,
        string slotName,
        uint helperEntityId)
    {
        return new MSBE.Part.Enemy
        {
            Name = $"cnv_radahn_helper_{slotName}",
            ModelName = template.ModelName,
            NPCParamID = template.NPCParamID,
            ThinkParamID = template.ThinkParamID,
            CharaInitID = template.CharaInitID,
            EntityID = helperEntityId,
            Position = boss.Position,
            Rotation = boss.Rotation,
            BackupEventAnimID = -1,
            WalkRouteName = "",
        };
    }
}

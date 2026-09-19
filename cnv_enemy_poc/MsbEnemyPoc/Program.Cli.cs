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

// CLI routing + argument resolution (T-073 R3)

static partial class Program
{
    static string ResolveSpawnMapPath(string[] args)
    {
        foreach (var arg in args)
        {
            if (arg.StartsWith("--spawn-map=", StringComparison.OrdinalIgnoreCase))
            {
                return Path.GetFullPath(arg["--spawn-map=".Length..].Trim('"'));
            }
        }

        return Path.Combine(
            ResolveRingrandomRoot(),
            "cnv_randomizer",
            "output",
            "runtime",
            "cnv_enemy_spawn_map.txt");
    }

    static string? ResolveMapFilter(string[] args)
    {
        foreach (var arg in args)
        {
            if (arg.StartsWith("--map-filter=", StringComparison.OrdinalIgnoreCase))
            {
                return arg["--map-filter=".Length..].Trim();
            }
        }

        return null;
    }

    static int ResolveParallelDegree(string[] args)
    {
        foreach (var arg in args)
        {
            if (arg.StartsWith("--parallel=", StringComparison.OrdinalIgnoreCase)
                && int.TryParse(arg["--parallel=".Length..], out var parallel))
            {
                return Math.Max(1, parallel);
            }
        }

        return Math.Max(1, Environment.ProcessorCount);
    }

    static int ResolveMaxParallelDegree(string[] args)
    {
        foreach (var arg in args)
        {
            if (arg.StartsWith("--max-parallel=", StringComparison.OrdinalIgnoreCase)
                && int.TryParse(arg["--max-parallel=".Length..], out var maxParallel))
            {
                return Math.Max(1, maxParallel);
            }
        }

        return Math.Min(96, Math.Max(Environment.ProcessorCount * 2, 32));
    }

    static int ResolveMapInflightLimit(string[] args)
    {
        foreach (var arg in args)
        {
            if (arg.StartsWith("--map-inflight=", StringComparison.OrdinalIgnoreCase)
                && int.TryParse(arg["--map-inflight=".Length..], out var inflight))
            {
                return Math.Clamp(inflight, 1, 256);
            }
        }

        return 48;
    }

    static bool ResolveDynamicParallel(string[] args) =>
        args.Any(a => string.Equals(a, "--dynamic-parallel", StringComparison.OrdinalIgnoreCase));

    static bool ResolveQuietApply(string[] args) =>
        args.Any(a => string.Equals(a, "--quiet", StringComparison.OrdinalIgnoreCase));

    static bool ResolveProfileApply(string[] args) =>
        args.Any(a => string.Equals(a, "--profile", StringComparison.OrdinalIgnoreCase));

    static bool ResolveNoMsbSourceCache(string[] args) =>
        args.Any(a => string.Equals(a, "--no-msb-source-cache", StringComparison.OrdinalIgnoreCase));

    static string ResolveIndexOutPath(string[] args)
    {
        foreach (var arg in args)
        {
            if (arg.StartsWith("--out=", StringComparison.OrdinalIgnoreCase))
            {
                return Path.GetFullPath(arg["--out=".Length..]);
            }
        }

        return Path.Combine(
            ResolveRingrandomRoot(),
            "cnv_randomizer",
            "cache",
            "enemy_index.raw.json");
    }

    static string ResolvePickupIndexOutPath(string[] args)
    {
        foreach (var arg in args)
        {
            if (arg.StartsWith("--out=", StringComparison.OrdinalIgnoreCase))
            {
                return Path.GetFullPath(arg["--out=".Length..]);
            }
        }

        return Path.Combine(
            ResolveRingrandomRoot(),
            "cnv_randomizer",
            "cache",
            "pickup_slot_index.json");
    }

    static int ResolveMaxMaps(string[] args)
    {
        foreach (var arg in args)
        {
            if (arg.StartsWith("--max-maps=", StringComparison.OrdinalIgnoreCase)
                && int.TryParse(arg["--max-maps=".Length..], out var maxMaps))
            {
                return maxMaps;
            }
        }

        return 0;
    }

    static int ResolveSeed(string[] args, int defaultSeed)
    {
        foreach (var arg in args)
        {
            if (arg.StartsWith("--seed=", StringComparison.OrdinalIgnoreCase))
            {
                if (int.TryParse(arg["--seed=".Length..], out var seed))
                {
                    return seed;
                }
            }
        }
        return defaultSeed;
    }

    static string ResolveCsvDir(string gameDir) => Path.Combine(gameDir, "csv");

    static string? ResolveMsbOverride(string[] args)

    {

        foreach (var arg in args)

        {

            if (arg.StartsWith("--msb=", StringComparison.OrdinalIgnoreCase))

            {

                return arg["--msb=".Length..].Trim('"');

            }

        }



        return FindCachedMsb();

    }

    static string ResolveToolRoot()

    {

        var dir = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);

        for (var i = 0; i < 8; i++)

        {

            if (File.Exists(Path.Combine(dir, "ENEMY_POC.bat")))

            {

                return dir;

            }



            var parent = Directory.GetParent(dir);

            if (parent is null)

            {

                break;

            }



            dir = parent.FullName;

        }



        return Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", ".."));

    }

    static string ResolveRingrandomRoot() =>

        Path.GetFullPath(Path.Combine(ResolveToolRoot(), ".."));

    static string ResolveModMapStudioDir(string gameDir, StringBuilder detailLog)

    {

        var candidates = new[]

        {

            Path.Combine(gameDir, "mod", "map", "MapStudio"),

            Path.Combine(gameDir, "mod", "map", "mapstudio"),

        };



        foreach (var path in candidates)

        {

            if (Directory.Exists(path))

            {

                Log(detailLog, $"mod_mapstudio_pick={path}");

                return path;

            }

        }



        var created = candidates[0];

        Log(detailLog, $"mod_mapstudio_pick={created} (created)");

        return created;

    }

    static string? FindCachedMsb()

    {

        var cacheRoot = Path.Combine(ResolveToolRoot(), "cache");

        if (!Directory.Exists(cacheRoot))

        {

            return null;

        }



        var preferred = new[]

        {

            Path.Combine(cacheRoot, $"{MapId}.msbe.dcx"),

            Path.Combine(cacheRoot, $"{MapId}.msb.dcx"),

            Path.Combine(cacheRoot, "map", "mapstudio", $"{MapId}.msbe.dcx"),

            Path.Combine(cacheRoot, "map", "mapstudio", $"{MapId}.msb.dcx"),

        };

        foreach (var path in preferred)

        {

            if (File.Exists(path))

            {

                return path;

            }

        }



        var any = Directory.EnumerateFiles(cacheRoot, "*.*", SearchOption.AllDirectories)

            .Where(p => p.Contains(MapId, StringComparison.OrdinalIgnoreCase))

            .Where(p => p.EndsWith(".msbe.dcx", StringComparison.OrdinalIgnoreCase)

                        || p.EndsWith(".msb.dcx", StringComparison.OrdinalIgnoreCase))

            .OrderBy(p => p, StringComparer.OrdinalIgnoreCase)

            .FirstOrDefault();

        return any;

    }

    static string ResolveGameDir(string[] args)

    {

        foreach (var arg in args)

        {

            if (arg.StartsWith("--game=", StringComparison.OrdinalIgnoreCase))

            {

                return arg["--game=".Length..].Trim('"');

            }

        }



        var ringrandom = ResolveRingrandomRoot();

        var gamePathJson = Path.Combine(ringrandom, "game_path.json");

        if (File.Exists(gamePathJson))

        {

            var text = File.ReadAllText(gamePathJson);

            var key = "\"game_dir\"";

            var idx = text.IndexOf(key, StringComparison.Ordinal);

            if (idx >= 0)

            {

                var start = text.IndexOf('"', idx + key.Length) + 1;

                var end = text.IndexOf('"', start);

                if (start > 0 && end > start)

                {

                    return text[start..end].Replace("\\\\", "\\");

                }

            }

        }



        var env = Environment.GetEnvironmentVariable("CNV_GAME_DIR");

        if (!string.IsNullOrWhiteSpace(env))

        {

            return env;

        }



        return @"V:\games\Elden Ring\Game";

    }


}

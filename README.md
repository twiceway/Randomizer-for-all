# Randomizer for all

Enemy + ground-loot randomizer for **Elden Ring: The Convergence 3.0**.

This repository is a **public English source mirror for Nexus Mods review / CS**.

- Nexus file: `Randomizer-for-all-1.0.1-scripts.zip` (scripts pack; **no `.exe` in the zip**)
- Author Nexus username: **twicewayYYB**
- **Staff / CS brief (English):** [packaging/NEXUS_STAFF_BRIEF_EN.md](packaging/NEXUS_STAFF_BRIEF_EN.md)
- **Chinese main development repo (Gitee — not this mirror):**  
  `https://gitee.com/twiceway/RingRandom`

## What this is

A normal Windows desktop tool for Convergence 3.0 + ME3:

- randomizes enemies and ground pickups
- **Nexus pack:** Python GUI via bats (no PyInstaller EXE in the zip); helpers compile locally with .NET 8 SDK
- **Gitee full pack:** optional `RandomizerForAll.exe` onedir for players who want a double-click GUI
- includes a pickup hook DLL (`cnv_pickup_hook.dll`)

Pack flags used on the GUI zip on purpose: **no UPX**, **no nested `base_library.zip`**.  
It is not malware.

## Build the release zip (reviewers)

Full steps: **[packaging/BUILD.md](packaging/BUILD.md)**  
Staff checklist: **[packaging/NEXUS_STAFF_BRIEF_EN.md](packaging/NEXUS_STAFF_BRIEF_EN.md)**

Short version on Windows:

```bat
packaging\pack_release.bat
```

Output:

```text
dist\Randomizer-for-all-1.0.1.zip
dist\Randomizer-for-all-1.0.1-scripts.zip
```

## Run from source

1. Copy `game_path.example.json` to `cnv_randomizer/game_path.json`
2. Set `game_dir` to your Convergence `Game` folder
3. Run `LAUNCH_GUI.bat`

## Repository layout

| Folder | Purpose |
|--------|---------|
| `cnv_randomizer/` | GUI and randomization logic (Python) |
| `cnv_pickup_hook/` | Pickup hook (C++) |
| `cnv_enemy_poc/` | Map / NPC helpers (C#) |
| `packaging/` | Build scripts + English Nexus staff brief |
| `捐皮契约/` | Offline tables used at runtime |

This tree is **product source only** for security review (no local game paths, no private agent notes).

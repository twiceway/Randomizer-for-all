# Randomizer for all

Enemy + ground-loot randomizer for **Elden Ring: The Convergence 3.0**.

This repository is the **public source** for the Nexus Mods file:

`Randomizer-for-all-1.0.0.zip`

Author Nexus username: **twicewayYYB**

## What this is

A normal Windows desktop tool:

- randomizes enemies and ground pickups for Convergence
- ships a GUI (`RandomizerForAll.exe` in the release zip)
- includes a small pickup hook DLL and two helper programs used by the tool

It is packed with PyInstaller. Pack flags used on purpose: **no UPX**, **no nested `base_library.zip`**.  
It is not malware.

## Build the release zip (reviewers)

Full steps: **[packaging/BUILD.md](packaging/BUILD.md)**

Short version on Windows:

```bat
packaging\pack_release.bat
```

Output:

```text
dist\Randomizer-for-all-1.0.0.zip
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
| `packaging/` | How the Nexus zip is built |
| `捐皮契约/` | Offline tables used at runtime |

This public tree is **product source only** (no local game paths, no private notes).

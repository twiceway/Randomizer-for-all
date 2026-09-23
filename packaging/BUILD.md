# Build Randomizer for all 1.0.1

Public **review mirror** source for Nexus Mods.

**Staff / CS brief (English only):** **[NEXUS_STAFF_BRIEF_EN.md](./NEXUS_STAFF_BRIEF_EN.md)**  
← start there for dual-track packs, why no `.exe`, and verification checklist.

Main development continues on **Gitee** (`https://gitee.com/twiceway/RingRandom`).  
This GitHub tree is filtered product source for security review, not the primary repo.

**Dual-track packs:**

| Zip | Contents | Audience |
|-----|----------|----------|
| `Randomizer-for-all-1.0.1.zip` | PyInstaller GUI exe + `data/` | Gitee / full UI |
| `Randomizer-for-all-1.0.1-scripts.zip` | No `.exe` in zip; bats + Python + C# sources; local `dotnet build` | **Nexus preferred** |

Full GUI pack uses **PyInstaller** (one-folder): `--noupx`, `--debug=noarchive`.  
Scripts pack skips PyInstaller. Both ship the pickup DLL; scripts pack does **not** ship helper EXEs (C# sources only).

It does not install anything in the background. It is not malware.

---

## Requirements (Windows)

| Need | Why |
|------|-----|
| Windows 10/11 x64 | Target OS |
| Python 3.13 + `pip install pyinstaller` | GUI pack / packer (scripts pack players also need Python) |
| .NET 8 SDK | Helper tools (`MsbEnemyPoc`, `NpcSoulPatch`) |
| Visual Studio 2022 (C++ desktop) | Pickup hook DLL |
| Convergence `Game` folder | Pack copies offline item CSV tables into the zip |

Local path file (do **not** commit):

1. Copy `game_path.example.json` → `cnv_randomizer/game_path.json`
2. Set `game_dir` to your Elden Ring / Convergence `Game` directory

---

## Build release zips

From the repository root:

```bat
packaging\pack_release.bat
```

Default `--mode both` → both zips under `dist\`.

```bat
packaging\pack_release.bat --mode scripts --skip-prep --skip-dotnet
packaging\pack_release.bat --mode exe --skip-pyinstaller
```

What the script does:

1. Builds the C# helpers (unless skipped)
2. Builds / picks up `cnv_pickup_hook.dll`
3. **exe mode**: PyInstaller onedir + `data/`
4. **scripts mode**: `data/` + bats from `packaging/scripts_pack/` (no GUI exe)
5. Cleans `dist/` to only the finished zip(s)

Player CLI (scripts pack): `data/cnv_randomizer/player_run.py`

---

## Run from source (developers)

```bat
LAUNCH_GUI.bat
```

Or:

```bat
cd cnv_randomizer
python player_run.py doctor
python player_run.py gui
```

---

## Source layout

| Path | Contents |
|------|----------|
| `cnv_randomizer/` | GUI + randomization logic + `player_run.py` |
| `cnv_pickup_hook/` | Ground-loot hook (C++) |
| `cnv_enemy_poc/` | Map / NPC helper tools (C#) |
| `packaging/` | Release packaging + `scripts_pack/` bats |
| `捐皮契约/` | Offline tables shipped with the tool |

---

## Nexus review notes

- Author Nexus username: **twicewayYYB**
- Prefer uploading **`Randomizer-for-all-1.0.1-scripts.zip`** (no `.exe` in the zip; helpers built locally with .NET 8 SDK)
- Full GUI zip: Gitee; build: `packaging\pack_release.bat --mode both`
- Staff brief: **[NEXUS_STAFF_BRIEF_EN.md](./NEXUS_STAFF_BRIEF_EN.md)**

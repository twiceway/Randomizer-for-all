# Build Randomizer for all 1.0.0

Public source for the Nexus Mods file **`Randomizer-for-all-1.0.0.zip`**.

This project is a normal Windows desktop tool for **Elden Ring: The Convergence 3.0**.  
The release zip is packed with **PyInstaller** (one-folder layout).

Security-related pack flags used on purpose:

- **no UPX** (`--noupx`)
- **no nested `base_library.zip`** (`--debug=noarchive`)

It does not install anything in the background. It is not malware.

---

## Requirements (Windows)

| Need | Why |
|------|-----|
| Windows 10/11 x64 | Target OS |
| Python 3.13 + `pip install pyinstaller` | GUI / packer |
| .NET 8 SDK | Two small helper tools (`MsbEnemyPoc`, `NpcSoulPatch`) |
| Visual Studio 2022 (C++ desktop) | Pickup hook DLL |
| Convergence `Game` folder | Pack copies offline item CSV tables into the zip |

Local path file (do **not** commit):

1. Copy `game_path.example.json` → `cnv_randomizer/game_path.json`
2. Set `game_dir` to your Elden Ring / Convergence `Game` directory

---

## Build the same zip Nexus received

From the repository root:

```bat
packaging\pack_release.bat
```

Result:

```text
dist\Randomizer-for-all-1.0.0.zip
```

What the script does:

1. Builds the C# helpers (unless skipped)
2. Builds / picks up `cnv_pickup_hook.dll`
3. Packs `cnv_randomizer_gui.py` with PyInstaller (`--noupx`, `--debug=noarchive`, version resource)
4. Stages data + docs and writes the release zip

Useful flags:

```bat
packaging\pack_release.bat --skip-prep --skip-dotnet
```

Use this only when prep cache and helpers are already built.

---

## Run from source (developers)

```bat
LAUNCH_GUI.bat
```

This opens the same GUI without packing. Players should use the zip / `RandomizerForAll.exe`.

---

## Source layout

| Path | Contents |
|------|----------|
| `cnv_randomizer/` | GUI + randomization logic (Python) |
| `cnv_pickup_hook/` | Ground-loot hook (C++) |
| `cnv_enemy_poc/` | Map / NPC helper tools (C#) |
| `packaging/` | Release packaging |
| `捐皮契约/` | Offline tables shipped with the tool |

---

## Nexus review notes

- Author Nexus username: **twicewayYYB**
- Product / file: **Randomizer-for-all-1.0.0**
- Build entry: `packaging\pack_release.bat` → `dist\Randomizer-for-all-1.0.0.zip`
- VirusTotal for the uploaded zip was **0/65** at author submission time

# Nexus Mods staff brief — Randomizer for all (v1.0.1)

**Audience:** Nexus Mods reviewers / support staff (English).  
**Not for:** day-to-day Chinese development docs (those stay on **Gitee**).  

| Host | Language | Role |
|------|----------|------|
| **Gitee** `twiceway/RingRandom` | Chinese | Main repo / author |
| **GitHub** `twiceway/Randomizer-for-all` | **English** | This brief + filtered source for CS / review |

**Author Nexus username:** twicewayYYB  

This document explains the **dual-track distribution** and why the Nexus upload contains **no `.exe`**.

---

## 1. What the mod is

| Item | Fact |
|------|------|
| Product name | **Randomizer for all** |
| Game | **Elden Ring: The Convergence 3.0** + **ME3** launcher |
| Not for | Vanilla Elden Ring, Nexus mod **428**, other overhauls |
| Features | Enemy randomization + ground-loot hook + in-GUI “install mod into game” |
| Platforms | Windows 10/11 x64 |

It is a normal desktop tool. It does **not** install anything in the background. It is **not** malware.

---

## 2. Dual-track packs (why two zips)

| Pack | File name | Contents | Channel |
|------|-----------|----------|---------|
| **A — Full GUI** | `Randomizer-for-all-1.0.1.zip` | PyInstaller GUI (`RandomizerForAll.exe` + `_internal`) + prebuilt helper `.exe` + data | **Gitee / mirrors** (not the Nexus primary file) |
| **B — Scripts** | `Randomizer-for-all-1.0.1-scripts.zip` | **Zero `.exe` anywhere in the zip** · bats · Python sources · C# helper sources · pickup DLL | **Nexus Mods preferred primary file** |

**Policy:** Nexus main file = **scripts pack**. Full GUI zip is published on Gitee; Nexus page may link to it as an optional mirror.

---

## 3. Why the Nexus zip has no `.exe`

1. Avoid AV / automated scanner false positives on PyInstaller onedir and small helper EXEs.  
2. Meet a clear “no executable binaries in the upload” review path.  
3. Same features as the full pack: players run the **same Python GUI** from source; map helpers are **built once on the player PC** with the **.NET 8 SDK**.

Hard rules for pack B:

- No `RandomizerForAll.exe`, no `_internal/`.  
- No prebuilt `MsbEnemyPoc.exe` / `NpcSoulPatch.exe` in the zip.  
- Helper tools ship as **C# source**; `dotnet build` runs via `0_InstallRuntime.bat` / first generate.  
- Pickup hook ships as **`cnv_pickup_hook.dll`** (DLL, not EXE) — required at runtime.

---

## 4. Player install (scripts pack — Nexus)

Requirements: Windows 10/11, **Python 3.13** (Add to PATH, with tkinter), **.NET 8 SDK**.

1. Extract to a short path.  
2. Run **`0_InstallRuntime.bat`** (Chinese users: `0_安装运行环境.bat`, GBK-encoded).  
   - Tries winget for Python / .NET 8 SDK, then builds the two helper tools.  
3. Run **`1_OpenGUI.bat`** (Chinese: `1_打开界面.bat`).  
   - Black console stays with “please wait” until the GUI window appears.  
4. In the GUI: **Install mod** tab → **Generate**.  
5. Fully quit the game, launch Convergence via ME3 as usual.

English bats are ASCII + CRLF. Chinese bats must stay **GBK**, not UTF-8 (cmd code page).

Player-facing text in the zip: `README_Install_EN.txt` / `README_安装_中文.txt`.

---

## 5. Source repositories

| Role | URL | Note |
|------|-----|------|
| **Main development** | https://gitee.com/twiceway/RingRandom | Day-to-day commits; source of truth |
| **Public review mirror** | https://github.com/twiceway/Randomizer-for-all | Filtered product source for Nexus review only |

This GitHub tree excludes private agent/docs folders. Do not treat the GitHub mirror as the only source of truth.

---

## 6. How to rebuild the scripts zip (reviewers)

See **[BUILD.md](./BUILD.md)** for full steps.

Short version from repo root:

```bat
packaging\pack_release.bat --mode scripts
```

Output: `dist\Randomizer-for-all-1.0.1-scripts.zip`

Default `packaging\pack_release.bat` (`--mode both`) also builds the full GUI zip.

Pack flags used on purpose for the GUI pack: **no UPX**, **no nested `base_library.zip`** (`--debug=noarchive`), version-file metadata.

---

## 7. Quick verification checklist for staff

- [ ] Nexus primary file name ends with `-scripts.zip`.  
- [ ] Zip search finds **zero** `.exe` files.  
- [ ] Root has `0_InstallRuntime.bat` / `1_OpenGUI.bat` and English README.  
- [ ] `data/cnv_randomizer/` contains Python sources (GUI runs via Python).  
- [ ] `data/cnv_enemy_poc/` contains `.cs` / `.csproj` for helpers (no `bin/.../*.exe` in the zip).  
- [ ] `data/bin/cnv_pickup_hook.dll` present.  
- [ ] Mod description states **Requires The Convergence 3.0 + ME3**, **not** vanilla / not 428.

---

## 8. FAQ for support tickets

| Question | Answer |
|----------|--------|
| Why no EXE on Nexus? | Scripts pack is intentional; helpers compile locally with .NET 8 SDK. |
| Where is the double-click GUI EXE? | Full pack on Gitee; Nexus prefers the no-exe scripts pack. |
| Is the pickup DLL malware? | No — it is a normal game mod DLL loaded by ME3 like other Convergence mods. |
| Can it be used with Nexus 428? | No. This product is Convergence-only. |
| Generate takes long? | Full map pass is often ~3–4 minutes on a warm machine. |
| Nothing changed in-game? | Fully quit and relaunch via Convergence/ME3; explored/killed areas may not refresh — new save recommended. |

---

## 9. Related files in this `packaging/` folder

| File | Purpose |
|------|---------|
| `BUILD.md` | How to build both release zips |
| `NEXUS_STAFF_BRIEF_EN.md` | This brief (staff / CS) |
| `scripts_pack/README.md` | Bat encoding notes |
| `export_github_source.py` | Builds the filtered GitHub review tree |

End of brief.

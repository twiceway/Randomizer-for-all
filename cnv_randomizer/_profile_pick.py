"""Profile enemy generate pick phase."""
from __future__ import annotations

import cProfile
import pstats
import sys
from io import StringIO
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from enemy_randomizer_core import _load_json, run_enemy_randomize

cfg = _load_json(SCRIPT_DIR / "config.json")
pr = cProfile.Profile()
pr.enable()
run_enemy_randomize(cfg, seed=95831820)
pr.disable()
s = StringIO()
ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
ps.print_stats(40)
text = s.getvalue()
out = SCRIPT_DIR / "output" / "runtime" / "_pick_profile.txt"
out.write_text(text, encoding="utf-8")
print(text[:8000])

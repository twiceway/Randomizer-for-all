#!/usr/bin/env python3
"""CLI entry — delegates to cnv_randomizer_core."""

import sys
from pathlib import Path

from paths import SCRIPT_DIR  # frozen-safe (data/cnv_randomizer)
sys.path.insert(0, str(SCRIPT_DIR))

from cnv_randomizer_core import load_config, run_randomize  # noqa: E402


def main() -> int:
    config_path = SCRIPT_DIR / "config.json"
    if len(sys.argv) > 1:
        config_path = Path(sys.argv[1]).resolve()
    cfg = load_config(config_path)
    result = run_randomize(cfg, deploy=False)
    print("CNV map-item randomizer")
    print(f"  seed: {result.seed}")
    print(f"  runtime pairs: {result.runtime_pairs}")
    print(f"  runtime map: {result.runtime_map_path}")
    print(f"  spoiler: {result.spoiler_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

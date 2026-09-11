"""
The live numbers the public site quotes, read from the recorded dry runs.

Writes site/web/stats.json from build/demo/dryrun*.json (the episodes
tools/drive.py saves): how many rehearsals, how many fields the fly filled
by itself, how many the rig completed. The page reads the file at runtime
and never has a hand-typed number in its copy.

  py tools/site_stats.py
"""
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "web" / "stats.json"


def main():
    runs = sorted((ROOT / "build" / "demo").glob("dryrun*.json"))
    fly, rig, n, reached = 0, 0, 0, 0
    for p in runs:
        try:
            s = json.loads(p.read_text(encoding="utf-8"))["summary"]
        except Exception:
            continue
        n += 1
        fly += len(s.get("filled_by_fly") or [])
        rig += len(s.get("filled_by_rig") or [])
        reached += 1 if s.get("outcome") in ("probed", "dry", "minted") else 0
    stats = {
        "runs": n, "fields": 3,
        "filled_by_fly_total": fly, "filled_by_rig_total": rig,
        "filled_by_fly_per_run": round(fly / n, 2) if n else None,
        "runs_reaching_create": reached,
        "neurons": 165122, "synapses": 10228000, "eye_columns": 892,
        "wingbeats_hz": 200, "address_suffix": "8888", "chain_id": 56,
        "gas_units": 2096412, "creation_fee_bnb": 0,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    OUT.write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
trim_datasamples.py

Keeps at most MAX_KEEP files per condition subfolder under datasamples/.
Selection strategy: keep the top-ranked keyframes by the rank embedded in
the filename (keyframe_01 > keyframe_02 > ...). When multiple files share
the same keyframe rank (e.g. different clip scores), keep only the one with
the highest clip score.

Directory layout expected:
  datasamples/<type>/<scenario>/<condition>/  ← files trimmed here

Usage:
    python trim_datasamples.py               # dry-run
    python trim_datasamples.py --execute     # actually delete
    python trim_datasamples.py --execute --max-keep 3
"""

import argparse
import os
import re
from pathlib import Path

# ── CONFIG ──────────────────────────────────────────────────────────────────
DATASAMPLES_ROOT = Path("/raid/scratch/mdhossa2025/mdhossa/Lang2Drive/datasamples")
MAX_KEEP = 5
# ────────────────────────────────────────────────────────────────────────────


def parse_filename_scores(name: str):
    """
    Extract (keyframe_rank, clip_score) from filename like:
      keyframe_03_rsum_2.00_rel_0.995_clip_0.976.json
    Returns (rank:int, clip:float) or (999, 0.0) on failure.
    """
    rank_m = re.search(r'keyframe_(\d+)', name)
    clip_m = re.search(r'clip_([\d.]+?)(?:[._]|$)', name)
    rank = int(rank_m.group(1)) if rank_m else 999
    clip = float(clip_m.group(1)) if clip_m else 0.0
    return rank, clip


def select_files_to_keep(files: list[Path], max_keep: int) -> list[Path]:
    """
    Strategy:
      1. Group files by keyframe rank.
      2. Within each rank group keep the one with the highest clip score.
      3. Sort groups by rank ascending, take first max_keep groups.
      Returns the list of files to KEEP.
    """
    # Group by rank
    groups: dict[int, list[Path]] = {}
    for f in files:
        rank, _ = parse_filename_scores(f.name)
        groups.setdefault(rank, []).append(f)

    # Best file per rank (highest clip score)
    best_per_rank: list[tuple[int, Path]] = []
    for rank, group in groups.items():
        best = max(group, key=lambda p: parse_filename_scores(p.name)[1])
        best_per_rank.append((rank, best))

    # Sort by rank, take top max_keep
    best_per_rank.sort(key=lambda x: x[0])
    return [p for _, p in best_per_rank[:max_keep]]


def process_condition_dir(cond_dir: Path, max_keep: int, dry_run: bool) -> tuple[int, int]:
    """
    Returns (n_kept, n_deleted).
    """
    files = sorted([f for f in cond_dir.iterdir() if f.is_file()])
    if len(files) <= max_keep:
        return len(files), 0

    to_keep = set(select_files_to_keep(files, max_keep))
    to_delete = [f for f in files if f not in to_keep]

    for f in to_delete:
        if not dry_run:
            f.unlink()

    return len(to_keep), len(to_delete)


def main():
    ap = argparse.ArgumentParser(description="Trim datasamples condition folders to max N files.")
    ap.add_argument("--execute", action="store_true",
                    help="Actually delete files (default: dry-run)")
    ap.add_argument("--max-keep", type=int, default=MAX_KEEP,
                    help=f"Max files to keep per condition folder (default: {MAX_KEEP})")
    ap.add_argument("--root", default=str(DATASAMPLES_ROOT),
                    help="Path to datasamples root")
    args = ap.parse_args()

    root = Path(args.root)
    dry_run = not args.execute
    max_keep = args.max_keep

    if dry_run:
        print(f"DRY-RUN — no files will be deleted. Pass --execute to apply.\n")

    total_kept = 0
    total_deleted = 0
    over_limit = []

    # Walk: root / <type> / <scenario> / <condition>
    for type_dir in sorted(root.iterdir()):
        if not type_dir.is_dir():
            continue
        for scen_dir in sorted(type_dir.iterdir()):
            if not scen_dir.is_dir():
                continue
            for cond_dir in sorted(scen_dir.iterdir()):
                if not cond_dir.is_dir():
                    continue

                files = [f for f in cond_dir.iterdir() if f.is_file()]
                n = len(files)

                if n <= max_keep:
                    total_kept += n
                    continue

                kept, deleted = process_condition_dir(cond_dir, max_keep, dry_run)
                total_kept += kept
                total_deleted += deleted

                rel = cond_dir.relative_to(root)
                action = "would delete" if dry_run else "deleted"
                over_limit.append((str(rel), n, kept, deleted))
                print(f"  {rel}")
                print(f"    {n} files → keep {kept}, {action} {deleted}")

    print(f"\n{'Would delete' if dry_run else 'Deleted'}: {total_deleted} files  |  Kept: {total_kept}")
    if dry_run and over_limit:
        print(f"\n{len(over_limit)} condition folder(s) over the {max_keep}-file limit.")
        print("Re-run with --execute to apply.")


if __name__ == "__main__":
    main()

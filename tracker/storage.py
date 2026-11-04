"""Tiny helpers for append/upsert of tidy CSV files in data/."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def read_csv(path: Path, **kw) -> pd.DataFrame:
    if not Path(path).exists():
        return pd.DataFrame()
    return pd.read_csv(path, **kw)


def upsert(path: Path, new: pd.DataFrame, keys: list[str], sort: list[str] | None = None) -> pd.DataFrame:
    """Merge `new` into the CSV at `path`; rows in `new` win on key collisions."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = read_csv(path)
    if not old.empty and not new.empty:
        # align dtypes for key columns so duplicates are detected
        for k in keys:
            old[k] = old[k].astype(str)
            new = new.assign(**{k: new[k].astype(str)})
    frames = [f for f in (old, new) if not f.empty]
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=keys, keep="last")
    df = df.sort_values(sort or keys).reset_index(drop=True)
    df.to_csv(path, index=False)
    return df

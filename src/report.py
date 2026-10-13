"""CSV report and console summary of screening results."""

import datetime
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd


def write_report(
    results: list[dict[str, Any]], out_dir: Path, filename: str, columns: Sequence[str], top_n: int
) -> Path:
    """Write results (sorted by Total_Score) to ``filename`` with ``{date}`` filled in, print the top N."""
    df = pd.DataFrame(results).sort_values("Total_Score", ascending=False)
    df = df[[c for c in columns if c in df.columns]]

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename.format(date=today)
    df.to_csv(path, index=False, encoding="utf-8-sig")  # sig for Excel

    print("\nAnalysis Complete!")
    print(f"Passed: {len(df)} stocks")
    print(f"Saved to: {path}")
    print(f"\nTop {top_n} Candidates:")
    print(df.head(top_n).to_string(index=False))
    return path

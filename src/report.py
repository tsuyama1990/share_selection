"""CSV report and console summary of screening results."""
import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence

import pandas as pd

def write_report(results: List[Dict[str, Any]], out_dir: Path, filename: str,
                 columns: Sequence[str], top_n: int) -> Path:
    """
    Save results to a dated CSV (sorted by Total_Score) and print the top N.

    Parameters
    ----------
    results : List[Dict[str, Any]]
        Result rows from ``Screener.evaluate`` (must not be empty).
    out_dir : Path
        Output directory (created if missing).
    filename : str
        File name template; ``{date}`` is replaced by YYYY-MM-DD.
    columns : Sequence[str]
        Columns to write, in order (those absent from the results are skipped).
    top_n : int
        Number of top candidates printed to the console.

    Returns
    -------
    Path
        Path of the written CSV.
    """
    df = pd.DataFrame(results).sort_values('Total_Score', ascending=False)
    df = df[[c for c in columns if c in df.columns]]

    today = datetime.datetime.now().strftime('%Y-%m-%d')
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename.format(date=today)
    df.to_csv(path, index=False, encoding='utf-8-sig')  # sig for Excel

    print("\nAnalysis Complete!")
    print(f"Passed: {len(df)} stocks")
    print(f"Saved to: {path}")
    print(f"\nTop {top_n} Candidates:")
    print(df.head(top_n).to_string(index=False))
    return path

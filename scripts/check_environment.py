"""Verify the dashboard runtime and optional Tencent market feed."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SRC))

import numpy as np
import pandas as pd
from dashboard.strategy_factory import Costs
from quant_trading.market_data import fetch_tencent_daily


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--network", action="store_true", help="also query Tencent A-share data"
    )
    args = parser.parse_args()

    print(f"Python: {sys.version.split()[0]}")
    print(f"NumPy: {np.__version__}")
    print(f"Pandas: {pd.__version__}")
    print(f"Dashboard strategy engine: OK ({Costs()})")

    values = pd.Series(np.arange(1, 21, dtype=float)).rolling(5).mean()
    assert values.iloc[-3:].tolist() == [16.0, 17.0, 18.0]
    print("Indicator calculation: OK")

    if args.network:
        data = fetch_tencent_daily("sh000001", limit=120)
        print(f"Tencent A-share data: OK ({len(data)} rows)")
        print(data.tail(2)[["close", "volume"]])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

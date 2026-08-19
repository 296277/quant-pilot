# QuantPilot Quant Trading Cockpit

**Language / 语言:** [简体中文](README.md) · English

QuantPilot is a locally running quantitative trading cockpit for A-shares and
cryptocurrencies. It provides market data, watchlists, strategy candidates,
portfolio backtests, monitoring, sector/theme/index analysis, local paper
trading, and OKX Demo paper trading.

> **Current status: early experimental version.** The project is still rough
> and some data sources, analysis pages, parameter guidance, advanced risk
> controls, error handling, and broker adapters are incomplete. It is intended for learning, research,
> and paper testing only. It is not investment or automated-trading advice,
> has no live-order entry point, and does not promise any returns.

## Dashboard Preview

### Market Dashboard

The dashboard shows major indices, market breadth, trend strength, sector heat,
and monitoring summaries.

![QuantPilot Market Dashboard](docs/images/quantpilot-market.png)

### Strategy Candidates

Choose a market, sector, and asset to automatically generate and compare
multiple candidate strategies. The page reports out-of-sample return,
benchmark-relative performance, drawdown, Sharpe, and trade count.

![QuantPilot Strategy Candidates](docs/images/quantpilot-strategy.png)

## One-click Startup on Windows

When dependencies are installed, double-click `一键启动量化面板.cmd`. The
launcher opens <http://127.0.0.1:8765>, reuses an existing service, and records
startup failures under `data/processed/dashboard/`.

## Installation

Python 3.10 or later is required:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Then run the Windows launcher, or start the service manually:

```powershell
.\.venv\Scripts\python.exe dashboard\server.py
```

## Features

| Module | Current capability |
| --- | --- |
| Interface language | Switch between Simplified Chinese and English in the top-right selector; the choice is saved locally and restored on the next visit |
| Market dashboard | Major indices, breadth, turnover overview, trend strength, and sector heat |
| Watchlist and monitoring | Local watchlist, price/change/indicator rules, trigger history, and dashboard summaries |
| Market analysis | Limit-up ladder, theme, sector, stock, index analysis, and financial-data coverage boundaries |
| Strategy candidates | Generate and rank up to 14 candidates for A-shares or cryptocurrencies |
| Strategy library | Trend, breakout, mean reversion, SuperTrend + ADX, Turtle breakout, Bollinger + RSI, MACD + volume, volatility squeeze, multi-timeframe, relative strength, regime adaptive, and signal voting strategies |
| Parameter Lab | Edit validated strategy parameters and recalculate full-sample and out-of-sample results; save, load, copy, delete, import, and export browser-local strategy versions |
| Research validation | Train/test separation, out-of-sample return, buy-and-hold benchmark, drawdown, Sharpe, win rate, trade count, and fee modeling |
| Portfolio backtest | Multi-asset portfolios with capital, position limits, exposure, stop loss, take profit, holding period, and trade details |
| Local paper trading | Replay a selected strategy through the holdout sample with cash, positions, orders, P&L, and equity history |
| OKX Demo | Encrypted Demo credentials, balance/position/order/fill sync, adjustable parameters, signal preview, and confirmed simulated orders |
| miniQMT | Read-only synchronization of a local QMT A-share account; no order API is called |
| Data and environment | Unified data mode, coverage, trading date, update time, and live/delayed/cached state, plus parallel health checks for A-share, index, limit-up pool, crypto, and local-file sources |

## Typical Workflow

1. Review indices, breadth, and sector conditions, or add assets to the watchlist.
2. Open Strategy and choose Tencent A-shares, Gate.io crypto, or a local CSV snapshot, then select a sector and asset.
3. Generate candidates and compare out-of-sample return, benchmark-relative return, drawdown, Sharpe, and trade count.
4. Inspect a candidate's rules, parameters, equity curve, and recent trades; edit parameters, recalculate, and save useful variants locally.
5. Open Data to review each source's mode, trading date, update time, and availability.
6. Send the strategy to a local paper account for historical replay; crypto candidates can also be sent to OKX Demo.
7. In OKX Demo, adjust parameters, calculate a signal from the latest completed daily bar, and confirm a simulated order after review.

QuantPilot does not run unattended strategies in the background and never
submits live orders.

## Data Sources

- Tencent public A-share quotes.
- Gate.io public cryptocurrency candles.
- Eastmoney for the full-market limit-up pool and as a partial market-snapshot fallback.
- Local CSV snapshots under `data/raw/`.

When network data is unavailable, the market page retains the last local
snapshot. Runtime caches and broker credentials are excluded from Git by
default.

## Paper-trading Safety

- The OKX adapter always sends `x-simulated-trading: 1`.
- Only `*-USDT` spot market simulation orders are supported.
- Every simulated order requires browser and server-side confirmation.
- API credentials are encrypted with Windows DPAPI for the current local user;
  they are never written to the frontend or Git.
- miniQMT is read-only and does not call broker order APIs.

See [docs/BROKER_ADAPTERS.md](docs/BROKER_ADAPTERS.md) for configuration.

## Tests

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -s tests
```

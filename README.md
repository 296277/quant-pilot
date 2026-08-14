# QuantPilot 量化驾驶舱

QuantPilot 是一个本地运行的 A 股与虚拟货币量化驾驶舱，提供行情、自选、策略候选、组合回测、
监控、行业/概念/指数分析、本地模拟交易和 OKX Demo 模拟交易。

> 仅用于研究和模拟。项目没有实盘下单入口，不承诺收益。

## 一键启动（Windows）

已经安装依赖时，双击：

```text
一键启动量化面板.cmd
```

启动成功后会自动打开 <http://127.0.0.1:8765>。重复双击不会启动多个服务；
失败原因会直接显示在窗口中。

## 首次安装

需要 Python 3.10 或更高版本：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

安装后双击 `一键启动量化面板.cmd`。也可以手动启动：

```powershell
.\.venv\Scripts\python.exe dashboard\server.py
```

如需指定其他 Python，可设置当前终端环境变量：

```powershell
$env:QUANT_DASHBOARD_PYTHON = 'D:\Python\python.exe'
```

## 主要功能

- 市场看板、自选、连板梯队、概念、行业、个股、财务和指数分析。
- A 股与虚拟货币策略候选生成，内置趋势、突破、均值回归、SuperTrend + ADX、
  海龟突破、布林带 + RSI、MACD + 成交量、波动率挤压、多周期、相对强弱、
  市场状态自适应和多信号组合等策略。
- 训练段生成参数、留出段对比、费用建模、净值/回撤/交易明细展示。
- 本地历史回放模拟账户。
- OKX Demo 账户同步、策略参数调整、最新信号预览和需二次确认的模拟订单。
- miniQMT A 股账户只读同步。

## 数据来源

- 腾讯公开 A 股行情。
- Gate.io 公开虚拟货币 K 线。
- 东方财富仅作为部分市场快照的备用来源。
- `data/raw/` 中的本地 CSV 快照。

网络行情不可用时，市场页会保留上次本地快照。运行时缓存和账户配置都位于
`data/processed/` 或 `.market-cache/`，默认不会提交到 Git。

## 模拟交易安全

- OKX 适配器固定发送 `x-simulated-trading: 1`。
- 只允许 `*-USDT` 现货市价模拟单。
- 每笔模拟订单都要经过浏览器二次确认和服务端确认标记校验。
- API 凭据使用 Windows DPAPI 加密保存在当前用户本机，不写入前端或 Git。
- miniQMT 当前只读，不调用委托接口。

详细配置见 [docs/BROKER_ADAPTERS.md](docs/BROKER_ADAPTERS.md)。

## 项目结构

```text
dashboard/                 面板后端、前端、策略工厂和交易适配器
src/quant_trading/         公共行情客户端
scripts/check_environment.py  面板环境自检
tests/                     面板确定性测试
docs/                      模拟交易配置说明
data/                      本地行情与运行时状态（默认不提交）
requirements.txt           Python 依赖
一键启动量化面板.cmd        Windows 启动入口
```

## 测试

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -s tests
```

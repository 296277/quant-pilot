(() => {
  'use strict';

  const STORAGE_KEY = 'quantpilot-language';
  const SUPPORTED = new Set(['zh-CN', 'en-US']);
  const textState = new WeakMap();
  const attributeState = new WeakMap();
  let locale = readLocale();
  let observer;
  let scheduled = false;

  const entries = [
    ['公开市场快照、指数趋势与研究标的池', 'Public market snapshots, index trends, and the research universe'],
    ['多标的组合回测、净值与交易明细', 'Multi-asset portfolio backtests, equity curves, and trade details'],
    ['本地规则、市场快照评估与触发记录', 'Local rules, snapshot evaluation, and trigger history'],
    ['配置板块强弱、领涨领跌与成分股', 'Configured sector strength, leaders, laggards, and constituents'],
    ['本地模拟账户、持仓、订单与历史回放', 'Local paper accounts, positions, orders, and historical replay'],
    ['Python 运行时、策略引擎与行情接口检查', 'Python runtime, strategy engine, and market data checks'],
    ['候选参数来自训练段，排序依据为样本外研究评分', 'Parameters are fitted on training data and ranked by out-of-sample research scores'],
    ['验证 Python、NumPy、Pandas、策略引擎与行情接口。', 'Check Python, NumPy, Pandas, the strategy engine, and market data interfaces.'],
    ['周线过滤方向，日线负责进入和退出，降低逆大周期交易。', 'The weekly trend sets direction while daily bars time entries and exits.'],
    ['趋势、突破、MACD、RSI 与成交量五类信号投票，避免单一指标决定仓位。', 'Trend, breakout, MACD, RSI, and volume signals vote instead of relying on one indicator.'],
    ['比较所选股票、板块成员与基准指数的滚动收益，仅持有板块前列且跑赢基准的标的。', 'Compare rolling returns against sector peers and the benchmark, holding only relative leaders.'],
    ['ADX 判断趋势/震荡状态，趋势市使用通道突破，震荡市使用布林带与 RSI 回归。', 'ADX identifies trend or range regimes, switching between breakouts and Bollinger/RSI reversion.'],
    ['只有价格跌破布林下轨且 RSI 同时超卖才入场，减少单指标过早抄底。', 'Enter only when price breaks the lower Bollinger Band and RSI is oversold.'],
    ['通道突破捕捉趋势，按 ATR 止损距离计算风险仓位。', 'Capture trends with channel breakouts and size risk using the ATR stop distance.'],
    ['仅在 ADX 确认趋势时跟随 SuperTrend，并以 ATR 波动带作为动态防线。', 'Follow SuperTrend only when ADX confirms a trend, using ATR as a dynamic defense.'],
    ['布林带收进 Keltner 通道识别蓄势，释放后只跟随向上突破。', 'Detect compression inside Keltner Channels and follow upside releases.'],
    ['MACD 多头动量叠加成交量放大和长期方向确认。', 'Confirm bullish MACD momentum with expanding volume and the long-term trend.'],
    ['当前项目未接入授权财报源，不展示虚构财务指标', 'No licensed financial statement source is connected; fabricated metrics are never shown'],
    ['价格、成交额、换手、量比、市值、技术指标、回测与模拟交易', 'Price, turnover, volume ratio, market cap, indicators, backtests, and paper trading'],
    ['利润表、资产负债表、现金流、估值历史、机构一致预期', 'Income statement, balance sheet, cash flow, valuation history, and analyst consensus'],
    ['财务模块需要明确数据源授权和复权口径。接入前不会用随机数或过期样例填充。', 'Financial data requires a licensed source and a defined adjustment method. No random or stale sample data is used.'],
    ['强制使用 OKX 模拟交易请求头；支持需二次确认的现货市价模拟订单，绝不发送实盘。', 'The OKX simulated-trading header is enforced. Demo spot market orders require confirmation and never reach live trading.'],
    ['使用最后一根已完成 OKX 日线计算；信号预览不会自动下单。', 'Signals use the latest completed OKX daily bar. Previewing never places an order.'],
    ['配置已使用 Windows 当前用户加密保存在本机，下次打开可直接使用', 'Encrypted for the current Windows user and available next time'],
    ['配置仅在本次面板运行期间保留，关闭后自动清除', 'Kept only for this dashboard session and cleared on exit'],
    ['直接填写所需信息，并自行选择是否加密保存到本机', 'Enter the required details and choose whether to encrypt them locally'],
    ['miniQMT 只读；OKX Demo 支持需确认的模拟订单，绝不发送实盘', 'miniQMT is read-only; OKX Demo orders require confirmation and never reach live trading'],
    ['连续涨停按日线收盘涨幅和板块阈值近似计算；封单额、炸板次数需要逐笔/盘口数据，当前不伪造。', 'Limit-up streaks are estimated from daily closes and board thresholds. Order-book-only metrics are not fabricated.'],
    ['全市场涨停池数据；连板数、封板时间、炸板次数和封单金额来自行情源。', 'Full-market limit-up pool; streaks, seal times, break counts, and sealed capital come from the market data source.'],
    ['东方财富涨停池（全市场）', 'Eastmoney Limit-up Pool (Full Market)'],
    ['涨停池实时刷新失败，已显示最近快照：', 'Live limit-up refresh failed; showing the latest snapshot: '],
    ['市场快照当前为部分覆盖，榜单仍可查看；涨跌家数、广度、全市场均值暂不作为完整市场结论。', 'The snapshot has partial coverage. Rankings remain available, but breadth and market-wide averages are not treated as complete.'],
    ['输入 A 股代码查看日线、指标和策略候选', 'Enter an A-share code to view daily bars, indicators, and strategy candidates'],
    ['腾讯公开报价（项目观察池）', 'Tencent public quotes (project universe)'],
    ['东方财富公开市场快照', 'Eastmoney public market snapshot'],
    ['腾讯公开日线', 'Tencent public daily bars'],
    ['项目配置的 A 股观察池，不宣称全市场覆盖', 'Project A-share universe; not full-market coverage'],
    ['按项目配置板块聚合，不代表交易所官方行业分类', 'Aggregated by configured sectors; not an official exchange classification'],
    ['项目配置标的池', 'Configured asset universe'],
    ['项目配置池', 'Configured universe'],
    ['覆盖本项目', 'Covers the project\'s '], ['个配置板块', 'configured sectors'],
    ['不宣称全市场概念库', 'not a full-market concept database'],
    ['板块多标的组合回测 · 收盘信号次日开盘执行', 'Sector portfolio backtest · close signals execute at the next open'],
    ['本地规则 · 手动刷新市场快照后评估', 'Local rules · evaluated after a manual market refresh'],
    ['选择研究方向并建立候选标的篮', 'Choose a research theme and build a candidate basket'],
    ['原始快照、来源与样本区间', 'Raw snapshots, sources, and sample ranges'],
    ['数据覆盖边界与待接入财务源', 'Data coverage boundaries and pending financial sources'],
    ['涨停候选与连续涨停近似统计', 'Limit-up candidates and estimated streaks'],
    ['行业热度、成交与内部结构', 'Sector heat, turnover, and internal structure'],
    ['日线趋势、指标与策略候选', 'Daily trends, indicators, and strategy candidates'],
    ['主要指数趋势与均线状态', 'Major index trends and moving-average states'],
    ['本地保存的观察标的', 'Locally saved watchlist'],
    ['策略池扫描与单股候选生成', 'Strategy scan and single-asset candidate generation'],
    ['等待生成候选策略', 'Waiting to generate strategy candidates'],
    ['正在获取板块历史并运行组合回测…', 'Loading sector history and running the portfolio backtest…'],
    ['正在刷新全市场快照与指数日线…', 'Refreshing the market snapshot and index daily bars…'],
    ['正在计算涨停候选与连续涨停天数…', 'Calculating limit-up candidates and streaks…'],
    ['正在计算配置板块强弱…', 'Calculating configured sector strength…'],
    ['正在读取四个主要指数日线…', 'Loading daily bars for four major indices…'],
    ['正在获取日线并计算策略…', 'Loading daily bars and calculating strategies…'],
    ['正在读取交易平台配置…', 'Loading trading platform configuration…'],
    ['正在扫描研究标的池…', 'Scanning the research universe…'],
    ['正在生成主题候选…', 'Generating theme candidates…'],
    ['正在读取市场快照…', 'Loading market snapshot…'],
    ['正在读取监控规则…', 'Loading monitoring rules…'],
    ['正在计算连板梯队…', 'Calculating limit-up ladder…'],
    ['正在读取概念统计…', 'Loading concept statistics…'],
    ['正在读取行业统计…', 'Loading sector statistics…'],
    ['正在读取模拟账户…', 'Loading paper account…'],
    ['正在读取数据资产…', 'Loading data assets…'],
    ['正在读取主题池…', 'Loading theme pool…'],
    ['正在读取自选…', 'Loading watchlist…'],
    ['正在读取指数…', 'Loading indices…'],
    ['正在执行自检…', 'Running system check…'],
    ['实时刷新暂不可用，已保留上次快照。', 'Live refresh is unavailable; the last snapshot is retained.'],
    ['指数行情暂时不可用，已显示上次快照。', 'Index quotes are temporarily unavailable; the last snapshot is shown.'],
    ['上游暂时断开连接，可能触发了访问频率限制', 'The upstream connection closed, possibly due to rate limiting'],
    ['上游请求超时', 'The upstream request timed out'],
    ['行业数据请求超时，请稍后重试', 'The sector data request timed out. Please try again later.'],
    ['行业分析加载失败：', 'Failed to load sector analysis: '],
    ['项目读取失败：', 'Failed to load project: '],
    ['请先选择一个候选策略', 'Select a strategy candidate first'],
    ['请先为虚拟货币生成并选择候选策略', 'Generate and select a crypto strategy candidate first'],
    ['策略已带到 OKX Demo，可调整参数并预览信号', 'Strategy sent to OKX Demo. Adjust parameters and preview the signal.'],
    ['模拟账户已创建', 'Paper account created'],
    ['模拟账户已重置', 'Paper account reset'],
    ['监控规则已添加', 'Monitoring rule added'],
    ['监控规则已评估', 'Monitoring rules evaluated'],
    ['已移出自选', 'Removed from watchlist'],
    ['已加入自选', 'Added to watchlist'],
    ['确定重置当前模拟账户和全部模拟订单吗？', 'Reset the current paper account and all simulated orders?'],
    ['将当前策略带到 OKX Demo 交易页', 'Send this strategy to the OKX Demo trading page'],
    ['仅虚拟货币候选可部署到 OKX Demo', 'Only crypto candidates can be deployed to OKX Demo'],
    ['尚未创建模拟账户', 'No paper account yet'],
    ['在策略工坊选择候选策略后点击“模拟运行”', 'Select a candidate in Strategy and start a paper simulation'],
    ['账户从留出样本起点开始按日回放。', 'The account replays daily from the holdout sample start.'],
    ['创建后将替换当前模拟账户。', 'Creating this account will replace the current paper account.'],
    ['推进回放后将显示模拟订单', 'Simulated orders appear after advancing the replay'],
    ['点击“同步账户”读取资金、持仓、委托和成交。', 'Select Sync Account to load funds, positions, orders, and fills.'],
    ['当前观察池没有可用行业行情。', 'No sector quotes are available for the current universe.'],
    ['暂无触发记录，可在监控中心添加规则。', 'No triggers yet. Add rules in Monitoring.'],
    ['暂无自选标的，可在策略扫描页点击星标添加。', 'No watchlist assets. Add them with the star in Strategy Scan.'],
    ['当前条件没有命中标的', 'No assets match the current filters'],
    ['配置参数后运行组合回测。', 'Configure the parameters, then run the portfolio backtest.'],
    ['等待输入股票代码', 'Waiting for a stock code'],
    ['暂无已完成交易', 'No completed trades'],
    ['暂无可绘制数据', 'No chart data available'],
    ['暂无触发记录', 'No trigger history'],
    ['暂无规则', 'No rules'],
    ['暂无数据', 'No data'],
    ['暂无', 'None'],
    ['市场看板', 'Market Dashboard'], ['回测工作台', 'Backtest Workspace'],
    ['监控中心', 'Monitoring'], ['连板梯队', 'Limit-up Ladder'],
    ['概念分析', 'Theme Analysis'], ['行业分析', 'Sector Analysis'],
    ['个股分析', 'Stock Analysis'], ['指数分析', 'Index Analysis'],
    ['财务数据覆盖', 'Financial Data Coverage'], ['策略池扫描', 'Strategy Scan'],
    ['主题候选', 'Theme Candidates'], ['环境状态', 'System Status'],
    ['运行环境自检', 'System Check'], ['量化驾驶舱', 'Quant Trading Cockpit'],
    ['模拟交易模式', 'Paper Trading Mode'], ['禁止实盘下单', 'Live orders disabled'],
    ['策略', 'Strategy'], ['回测', 'Backtest'], ['看板', 'Dashboard'],
    ['自选', 'Watchlist'], ['财务', 'Financials'], ['指数', 'Indices'],
    ['交易', 'Trading'], ['数据', 'Data'], ['本地', 'Local'],
    ['数据来源', 'Data Source'], ['板块', 'Sector'], ['股票', 'Stock'],
    ['我的策略版本', 'My Strategy Versions'], ['保存在当前浏览器本地', 'Stored locally in this browser'],
    ['导入 JSON', 'Import JSON'], ['参数实验室', 'Parameter Lab'],
    ['修改后重新计算完整样本与样本外结果', 'Edit parameters and recalculate full-sample and out-of-sample results'],
    ['候选原始参数', 'Original Candidate Parameters'], ['重新计算', 'Recalculate'],
    ['恢复候选参数', 'Restore Candidate Parameters'], ['输入版本名称，例如：BTC 低风险版', 'Enter a version name, e.g. BTC Low Risk'],
    ['保存版本', 'Save Version'], ['导出 JSON', 'Export JSON'],
    ['参数仅用于本次研究重算；保存版本不会自动下单。', 'Parameters apply only to this research recalculation; saving a version never places orders.'],
    ['当前结果已按自定义参数重新计算；保存版本不会自动下单。', 'Results were recalculated with custom parameters; saving a version never places orders.'],
    ['参数已修改，等待重新计算', 'Parameters changed; waiting to recalculate'],
    ['已使用自定义参数重算', 'Recalculated with Custom Parameters'],
    ['数据源健康中心', 'Data Source Health'], ['检测全部数据源', 'Check All Data Sources'],
    ['检测时间', 'Checked at'], ['数据模式', 'Data Mode'], ['覆盖范围', 'Coverage'],
    ['交易日期', 'Trading Date'], ['更新时间', 'Updated at'], ['记录数', 'Records'],
    ['可用', 'Available'], ['实时', 'Live'], ['缓存快照', 'Cached Snapshot'], ['延迟日线', 'Delayed Daily Data'],
    ['本地数据', 'Local Data'], ['不可用', 'Unavailable'], ['未检测', 'Not Checked'], ['未知', 'Unknown'],
    ['最近一次请求可用', 'Latest request succeeded'], ['网络状态尚未检测', 'Network status not checked'],
    ['本地文件数据', 'Local file data'], ['数据源状态检查失败', 'Data source health check failed'],
    ['重新检测', 'Check Again'], ['加载', 'Load'], ['复制', 'Copy'], ['导出', 'Export'], ['删除', 'Delete'],
    ['暂无保存版本。生成策略、调整参数后可在参数实验室保存。', 'No saved versions. Generate a strategy, edit its parameters, and save it in the Parameter Lab.'],
    ['个版本', 'versions'], ['个参数', 'parameters'],
    ['快周期', 'Fast Period'], ['慢周期', 'Slow Period'], ['入场窗口', 'Entry Window'], ['退出窗口', 'Exit Window'],
    ['计算窗口', 'Calculation Window'], ['波动带宽', 'Band Width'], ['指标周期', 'Indicator Period'],
    ['入场阈值', 'Entry Threshold'], ['退出阈值', 'Exit Threshold'], ['回看周期', 'Lookback Period'],
    ['过滤周期', 'Filter Period'], ['ATR 周期', 'ATR Period'], ['ATR 倍数', 'ATR Multiplier'],
    ['ADX 周期', 'ADX Period'], ['ADX 阈值', 'ADX Threshold'], ['ATR 止损', 'ATR Stop'],
    ['单次风险比例', 'Risk per Trade'], ['最大仓位', 'Maximum Exposure'], ['RSI 周期', 'RSI Period'],
    ['RSI 入场', 'RSI Entry'], ['RSI 退出', 'RSI Exit'], ['信号周期', 'Signal Period'],
    ['均量窗口', 'Volume Average Window'], ['放量倍数', 'Volume Multiplier'], ['布林带宽', 'Bollinger Width'],
    ['Keltner 带宽', 'Keltner Width'], ['周线快周期', 'Weekly Fast Period'], ['周线慢周期', 'Weekly Slow Period'],
    ['日线 EMA', 'Daily EMA'], ['板块前列比例', 'Top Sector Fraction'], ['趋势窗口', 'Trend Window'],
    ['突破窗口', 'Breakout Window'], ['突破退出窗口', 'Breakout Exit Window'], ['布林窗口', 'Bollinger Window'],
    ['MACD 快周期', 'MACD Fast Period'], ['MACD 慢周期', 'MACD Slow Period'], ['MACD 信号周期', 'MACD Signal Period'],
    ['入场票数', 'Entry Votes'], ['退出票数', 'Exit Votes'],
    ['币种分类', 'Crypto Group'], ['虚拟货币', 'Crypto'],
    ['本地行情日线', 'Local Daily Bars'], ['本地股票日线', 'Local Stock Daily Bars'],
    ['本地虚拟货币日线', 'Local Crypto Daily Bars'], ['买入费率', 'Buy Fee'],
    ['卖出费率', 'Sell Fee'], ['生成候选', 'Generate Candidates'],
    ['候选策略', 'Strategy Candidates'], ['买入持有', 'Buy and Hold'],
    ['本地模拟', 'Local Paper'], ['部署到 OKX Demo', 'Deploy to OKX Demo'],
    ['净值对比', 'Equity Comparison'], ['净值', 'Equity'], ['价格', 'Price'],
    ['边界与风险', 'Constraints and Risks'], ['最近交易', 'Recent Trades'],
    ['收盘后产生信号', 'Signals after close'], ['次日开盘执行', 'Execute next open'],
    ['训练 / 测试隔离', 'Train / test separation'], ['含双边成本', 'Round-trip costs included'],
    ['买入', 'Buy'], ['卖出', 'Sell'], ['持有', 'Holding'], ['净收益', 'Net Return'],
    ['同时检查腾讯行情', 'Also check Tencent quotes'], ['运行自检', 'Run Check'],
    ['等待执行', 'Waiting'], ['打开导航', 'Open navigation'],
    ['刷新当前页面', 'Refresh current page'], ['刷新', 'Refresh'],
    ['选择界面语言', 'Select interface language'], ['语言', 'Language'],
    ['自定义股票代码', 'Custom stock code'], ['自定义名称（可选）', 'Custom name (optional)'],
    ['自定义标的显示名称', 'Custom asset display name'], ['可选', 'Optional'],
    ['研究优先级', 'Research Priority'], ['样本外收益', 'Out-of-sample Return'],
    ['相对基准', 'vs Benchmark'], ['最大回撤', 'Max Drawdown'], ['夏普', 'Sharpe'],
    ['交易次数', 'Trades'], ['入场', 'Entry'], ['退出', 'Exit'], ['仓位', 'Position'],
    ['超额收益', 'Excess Return'], ['全样本收益', 'Full-sample Return'],
    ['对比买入持有', 'Compared with buy and hold'], ['虚线为测试起点', 'Dashed line marks test start'],
    ['模拟账户设置', 'Paper Account Setup'], ['初始资金', 'Initial Capital'],
    ['单边滑点', 'One-way Slippage'], ['创建并开始', 'Create and Start'], ['取消', 'Cancel'],
    ['进入策略工坊', 'Open Strategy'], ['回放完成', 'Replay Complete'],
    ['待运行', 'Ready'], ['运行中', 'Running'], ['虚拟货币账户', 'Crypto Account'],
    ['A 股账户', 'A-share Account'], ['单步', 'Step'], ['运行到底', 'Run to End'],
    ['重置模拟账户', 'Reset Paper Account'], ['留出样本回放', 'Holdout Replay'],
    ['账户权益', 'Account Equity'], ['累计盈亏', 'Total P&L'], ['可用现金', 'Available Cash'],
    ['持仓市值', 'Position Value'], ['浮动盈亏', 'Unrealized P&L'], ['按当前回放收盘价', 'At current replay close'],
    ['模拟账户净值', 'Paper Account Equity'], ['逐日权益', 'Daily Equity'],
    ['当前持仓', 'Current Position'], ['持仓中', 'Invested'], ['空仓', 'Flat'],
    ['数量', 'Quantity'], ['平均成本', 'Average Cost'], ['最新价格', 'Last Price'], ['市值', 'Market Value'],
    ['模拟订单', 'Simulated Orders'], ['日期', 'Date'], ['方向', 'Side'], ['状态', 'Status'],
    ['金额', 'Amount'], ['费用', 'Fees'], ['原因', 'Reason'], ['已成交', 'Filled'], ['受限', 'Blocked'],
    ['交易账户', 'Trading Account'], ['本机已保存', 'Saved Locally'], ['本次已配置', 'Configured'],
    ['待配置', 'Setup Required'], ['已连接', 'Connected'], ['已配置', 'Configured'],
    ['清空配置', 'Clear Configuration'], ['同步账户', 'Sync Account'],
    ['最新已完成日线', 'Latest Completed Daily Bar'], ['收盘价', 'Close'],
    ['前值 → 目标仓位', 'Previous → Target Position'], ['买入信号', 'Buy Signal'],
    ['卖出信号', 'Sell Signal'], ['维持当前目标', 'Maintain Current Target'],
    ['持仓 / 委托 / 成交', 'Positions / Orders / Fills'], ['当前委托', 'Open Orders'], ['最近成交', 'Recent Fills'],
    ['市场快照', 'Market Snapshot'], ['板块热度', 'Sector Heat'], ['领涨', 'Leaders'], ['领跌', 'Laggards'],
    ['个股涨 / 平 / 跌', 'Stocks Up / Flat / Down'], ['上涨率', 'Advance Rate'],
    ['强势 / 弱势', 'Strong / Weak'], ['涨跌幅超过', 'Absolute change above'],
    ['涨停 / 跌停', 'Limit Up / Limit Down'], ['按板块近似阈值汇总', 'Estimated using board thresholds'],
    ['换手 / 量比', 'Turnover / Volume Ratio'], ['全市场简单平均', 'Simple market average'],
    ['涨跌分布 / 广度', 'Distribution / Breadth'], ['趋势强度', 'Trend Strength'],
    ['指数均线 / 新高低', 'Index averages / range'], ['站上 MA5', 'Above MA5'], ['站上 MA20', 'Above MA20'],
    ['60日位置', '60-day Position'], ['60日高/低', '60-day High / Low'], ['平均', 'Average'], ['中位', 'Median'],
    ['涨 ', 'Up '], ['平 ', 'Flat '], ['跌 ', 'Down '],
    ['是', 'Yes'], ['否', 'No'],
    ['涨幅榜', 'Top Gainers'], ['跌幅榜', 'Top Losers'], ['成交额榜', 'Turnover Leaders'], ['活跃换手', 'Active Turnover'],
    ['查看规则', 'View Rules'], ['触发记录', 'Trigger History'], ['清空', 'Clear'],
    ['新增规则', 'New Rule'], ['股票代码', 'Stock Code'], ['显示名称', 'Display Name'],
    ['规则', 'Rule'], ['阈值', 'Threshold'], ['添加规则', 'Add Rule'], ['监控规则', 'Monitoring Rules'],
    ['全部板块', 'All Sectors'], ['全部策略', 'All Strategies'],
    ['搜索代码、名称或策略', 'Search code, name, or strategy'], ['运行扫描', 'Run Scan'],
    ['标的', 'Asset'], ['评分', 'Score'], ['现价', 'Last Price'], ['涨跌幅', 'Change'],
    ['量比', 'Volume Ratio'], ['日 K', 'Daily Candles'], ['操作', 'Action'], ['加入自选', 'Add to Watchlist'],
    ['我的自选', 'My Watchlist'], ['未分类', 'Uncategorized'], ['移除', 'Remove'],
    ['本地保存', 'saved locally'],
    ['股票池', 'Stock Universe'], ['最大持仓数', 'Max Positions'], ['最大总仓位', 'Max Exposure'],
    ['回测天数', 'Backtest Days'], ['止损', 'Stop Loss'], ['止盈', 'Take Profit'],
    ['最长持有日', 'Max Holding Days'], ['运行回测', 'Run Backtest'], ['总收益', 'Total Return'],
    ['年化', 'Annualized'], ['基准', 'Benchmark'], ['超额', 'Excess'], ['胜率', 'Win Rate'],
    ['最终权益', 'Final Equity'], ['成交约束', 'Execution Constraints'], ['策略净值 / 基准 / 回撤', 'Strategy / Benchmark / Drawdown'],
    ['交易明细', 'Trade Details'], ['没有完成交易', 'No completed trades'],
    ['训练段定参', 'Fit on training data'], ['次日开盘', 'Next-day open'],
    ['费用建模', 'Fee modeling'], ['多标的组合', 'Multi-asset portfolio'],
    ['价格高于', 'Price Above'], ['价格低于', 'Price Below'], ['涨幅达到', 'Gain Reaches'],
    ['跌幅达到', 'Loss Reaches'], ['量比达到', 'Volume Ratio Reaches'],
    ['最强主线', 'Strongest Theme'], ['最大风险', 'Biggest Risk'], ['覆盖板块', 'Covered Sectors'],
    ['资金活跃', 'Most Active'], ['领涨方向', 'Leading Themes'], ['领跌方向', 'Lagging Themes'],
    ['中位涨跌', 'Median Change'], ['成交额', 'Turnover'], ['换手率', 'Turnover Rate'],
    ['换手', 'Turnover'], ['成交', 'Turnover'],
    ['转到策略工坊', 'Open in Strategy'], ['样本外', 'Out of Sample'], ['回撤', 'Drawdown'],
    ['可用与待接入', 'Available and Pending'], ['已可用', 'Available'], ['尚未接入', 'Not Connected'],
    ['行业热度', 'Sector Heat'], ['重新加载', 'Reload'], ['细分方向', 'Segment'],
    ['观察标的', 'observed assets'], ['分析', 'Analyze'],
    ['候选', 'Candidates'], ['板及以上', ' consecutive limit-ups or more'], ['连板', ' consecutive limit-ups'],
    ['涨停', 'Limit-up'], ['首封', 'First seal'], ['封单', 'Sealed capital'], ['炸板', 'Breaks'],
    ['研究逻辑', 'Research Rationale'], ['重点风险', 'Key Risk'], ['全选候选标的', 'Select all candidates'],
    ['选择', 'Select '], ['已选', 'Selected'], ['可加入研究篮', 'Available for research basket'],
    ['本地数据资产', 'Local Data Assets'], ['文件', 'File'], ['周期', 'Interval'], ['来源', 'Source'],
    ['区间', 'Range'], ['条数', 'Rows'], ['大小', 'Size'], ['复权', 'Adjustment'],
    ['原始数据保持不变', 'raw data remains unchanged'], ['个快照', 'snapshots'],
    ['腾讯公开分钟K线（备用源）', 'Tencent public minute bars (fallback)'], ['Gate.io 公共现货K线', 'Gate.io public spot bars'],
    ['自检通过', 'Check Passed'], ['自检未通过', 'Check Failed'], ['环境自检通过', 'System check passed'],
    ['环境自检发现问题', 'System check found issues'], ['自检失败', 'Check failed'],
    ['自适应趋势跟随', 'Adaptive Trend Following'], ['唐奇安通道突破', 'Donchian Channel Breakout'],
    ['自适应趋势', 'Adaptive Trend'], ['通道突破', 'Channel Breakout'],
    ['MACD + 成交量', 'MACD + Volume'], ['波动率挤压', 'Volatility Squeeze'],
    ['状态自适应', 'Regime Adaptive'], ['多信号投票', 'Multi-signal Voting'],
    ['布林超跌回归', 'Bollinger Oversold Reversion'], ['RSI 超卖修复', 'RSI Oversold Recovery'],
    ['长趋势动量过滤', 'Long-term Momentum Filter'], ['海龟突破 + ATR', 'Turtle Breakout + ATR'],
    ['布林带 + RSI', 'Bollinger Bands + RSI'], ['MACD + 成交量放大', 'MACD + Volume Expansion'],
    ['波动率挤压突破', 'Volatility Squeeze Breakout'], ['周线 + 日线多周期趋势', 'Weekly + Daily Multi-timeframe Trend'],
    ['市场状态自适应', 'Market Regime Adaptive'], ['多信号投票组合', 'Multi-signal Voting'],
    ['板块相对强弱', 'Sector Relative Strength'], ['趋势风控', 'Trend Risk Control'],
    ['突破风控', 'Breakout Risk Control'], ['双重均值回归', 'Dual-confirmation Mean Reversion'],
    ['量价动量', 'Price-volume Momentum'], ['波动突破', 'Volatility Breakout'],
    ['多周期', 'Multi-timeframe'], ['横截面选股', 'Cross-sectional Selection'],
    ['状态切换', 'Regime Switching'], ['信号组合', 'Signal Ensemble'],
    ['趋势', 'Trend'], ['突破', 'Breakout'], ['均值回归', 'Mean Reversion'], ['超跌', 'Oversold'], ['动量', 'Momentum'],
    ['高波动', 'High Volatility'], ['中等波动', 'Medium Volatility'], ['低波动', 'Low Volatility'],
    ['EMA 方向与价格位置双重确认，适合持续性行情。', 'EMA direction and price position provide dual confirmation for persistent trends.'],
    ['震荡市容易反复切换并累积交易成本。', 'Range-bound markets can cause repeated switching and accumulated costs.'],
    ['快 EMA 高于慢 EMA 且收盘价位于慢 EMA 上方。', 'Fast EMA is above slow EMA and the close is above slow EMA.'],
    ['快慢 EMA 关系反转或价格跌回慢 EMA 下方。', 'Exit when the EMA relationship reverses or price falls below slow EMA.'],
    ['突破前期高点入场、跌破短通道退出，强调捕捉大波段。', 'Enter above prior highs and exit below the short channel to capture large trends.'],
    ['假突破时可能快速回撤，交易次数通常较少。', 'False breakouts can reverse quickly, and trades are usually infrequent.'],
    ['收盘价突破前期最高价。', 'The close breaks above the previous high.'],
    ['收盘价跌破短周期最低价。', 'The close breaks below the short-period low.'],
    ['价格跌出波动带后等待回归中轨，偏逆向。', 'Wait for price to revert toward the middle band after breaking below the volatility band.'],
    ['单边下跌中可能过早接入，需关注最大回撤。', 'Entries may be premature during persistent declines; monitor drawdown.'],
    ['收盘价跌破布林下轨。', 'The close breaks below the lower Bollinger Band.'],
    ['价格回到布林中轨。', 'Exit when price returns to the middle Bollinger Band.'],
    ['RSI 进入超卖区后等待修复，持仓逻辑直观。', 'Enter after RSI becomes oversold and hold for a recovery.'],
    ['极端弱势中 RSI 可长期钝化，暴露时间可能偏高。', 'RSI may remain oversold in severe weakness, extending exposure.'],
    ['RSI 低于训练段对应的超卖阈值。', 'RSI is below the oversold threshold fitted on training data.'],
    ['RSI 修复至退出阈值。', 'Exit when RSI recovers to the exit threshold.'],
    ['中期动量为正且站上长期均线时持有，减少逆势参与。', 'Hold when medium-term momentum is positive and price is above the long-term average.'],
    ['趋势反转时存在退出滞后，也可能错过快速 V 形反弹。', 'Exits lag trend reversals and may miss fast V-shaped rebounds.'],
    ['中期收益为正且价格高于长期均线。', 'Medium-term return is positive and price is above the long-term average.'],
    ['任一条件失效。', 'Exit when either condition fails.'],
    ['ADX 与 SuperTrend 都有滞后，趋势末端仍可能回吐。', 'ADX and SuperTrend both lag, so late-trend gains may be surrendered.'],
    ['价格站上 SuperTrend 且 ADX 超过趋势阈值。', 'Price is above SuperTrend and ADX exceeds the trend threshold.'],
    ['收盘价跌破 ATR 动态 SuperTrend 线。', 'Exit when the close breaks the dynamic ATR SuperTrend line.'],
    ['满仓或空仓；ATR 线动态收紧退出位置。', 'Fully invested or flat; the ATR line dynamically tightens the exit.'],
    ['横盘期可能连续假突破；低波动时仓位上限仍需约束。', 'Ranges may produce repeated false breakouts; cap exposure in low volatility.'],
    ['跌破短通道或入场价下方 N 倍 ATR。', 'Exit below the short channel or N ATR below entry.'],
    ['单次价格风险约占资金固定比例，仓位不超过上限。', 'Size each trade to a fixed capital risk without exceeding the exposure cap.'],
    ['持续下跌时两个指标仍会同时钝化，不能替代止损纪律。', 'Both indicators can remain depressed in a persistent decline and do not replace stop discipline.'],
    ['跌破布林下轨且 RSI 低于超卖阈值。', 'Price breaks the lower Bollinger Band while RSI is below the oversold threshold.'],
    ['回归中轨或 RSI 修复。', 'Exit on a return to the middle band or an RSI recovery.'],
    ['异常放量可能来自消息冲击，随后快速反转。', 'Volume spikes may be news-driven and reverse quickly.'],
    ['MACD 位于零轴上方并上穿信号线，成交量显著高于均量。', 'MACD is above zero and crosses its signal line with volume above average.'],
    ['MACD 转弱或价格跌破趋势线。', 'Exit when MACD weakens or price breaks the trend line.'],
    ['挤压释放方向可能反复，跳空会放大实际滑点。', 'Squeeze releases may whipsaw, while gaps can increase real slippage.'],
    ['近期出现挤压，释放后价格突破布林上轨。', 'A recent squeeze releases with price above the upper Bollinger Band.'],
    ['跌回中轨或触发 ATR 跟踪止损。', 'Exit at the middle band or an ATR trailing stop.'],
    ['周线确认较慢，快速反转阶段会延迟退出。', 'Weekly confirmation is slow and delays exits during fast reversals.'],
    ['周线快线高于慢线，日线站上 EMA 且短期动量为正。', 'Weekly fast average is above slow average while daily price is above EMA with positive momentum.'],
    ['周线方向反转或日线跌破 EMA。', 'Exit when the weekly trend reverses or daily price falls below EMA.'],
    ['市场状态切换存在识别延迟，临界区可能频繁换挡。', 'Regime detection lags and may switch frequently near boundaries.'],
    ['趋势状态等待突破；震荡状态等待布林与 RSI 双重超卖。', 'Wait for breakouts in trends and dual Bollinger/RSI oversold signals in ranges.'],
    ['按当前子策略退出；趋势状态消失时先降为现金。', 'Follow the active sub-strategy exit and move to cash when the trend regime ends.'],
    ['两个子策略互斥，任一时点最多满仓。', 'The two sub-strategies are mutually exclusive with at most full exposure.'],
    ['高度相关的技术信号可能同时失效，投票不等于真正分散。', 'Correlated technical signals may fail together; voting is not true diversification.'],
    ['五个子信号中至少三个同时支持做多。', 'At least three of five signals support a long position.'],
    ['支持票数降至一个或更少。', 'Exit when support falls to one vote or fewer.'],
    ['满仓或空仓；不使用未来票数。', 'Fully invested or flat, without future votes.'],
    ['板块样本较少、成分变更和基准选择会影响结果，存在幸存者偏差。', 'Small sector samples, constituent changes, and benchmark choice may introduce survivorship bias.'],
    ['滚动收益跑赢基准，且强度位于板块前列并站上趋势线。', 'Rolling return beats the benchmark, ranks near the sector top, and is above trend.'],
    ['不再跑赢基准、排名跌出前半或跌破趋势线。', 'Exit when benchmark outperformance ends, rank falls below the top half, or trend breaks.'],
    ['当前面板对所选股票执行；切换股票可比较同板块排名。', 'The dashboard applies this to the selected stock; switch stocks to compare sector ranks.'],
    ['满仓或空仓。', 'Fully invested or flat.'],
    ['收盘价突破前期最高价。', 'The close breaks above the prior high.'],
    ['大盘蓝筹', 'Large-cap Blue Chips'], ['人工智能与算力', 'AI and Computing'], ['半导体', 'Semiconductors'],
    ['新能源', 'New Energy'], ['机器人', 'Robotics'], ['医药生物', 'Healthcare'], ['低空经济', 'Low-altitude Economy'],
    ['主流币', 'Major Coins'], ['公链生态', 'Layer 1 Ecosystem'],
    ['上证指数', 'SSE Composite'], ['深证成指', 'SZSE Component'], ['创业板指', 'ChiNext Index'], ['科创50', 'STAR 50'],
    ['AI 算力基础设施', 'AI Computing Infrastructure'], ['服务器、光模块、国产算力', 'Servers, optical modules, and domestic computing'],
    ['估值与资本开支周期', 'Valuation and capex cycles'], ['人形机器人', 'Humanoid Robotics'],
    ['减速器、传感器、电机与执行器', 'Reducers, sensors, motors, and actuators'], ['量产节奏与订单兑现', 'Mass-production pace and order delivery'],
    ['整机、动力、航电与空管', 'Airframes, propulsion, avionics, and traffic control'], ['政策落地与商业化周期', 'Policy implementation and commercialization cycle'],
    ['半导体国产化', 'Domestic Semiconductors'], ['设备、制造、设计与封测', 'Equipment, manufacturing, design, packaging, and testing'],
    ['行业周期与研发投入', 'Industry cycles and R&D investment'], ['新能源修复', 'New Energy Recovery'],
    ['电池、光伏、储能与电力电子', 'Batteries, solar, storage, and power electronics'], ['产能过剩与价格竞争', 'Overcapacity and price competition'],
    ['创新药与医疗器械', 'Innovative Drugs and Medical Devices'], ['创新药、CXO 与高端器械', 'Innovative drugs, CXO, and advanced devices'],
    ['研发失败与政策变化', 'R&D failure and policy changes'], ['国产 AI 芯片', 'Domestic AI Chips'],
    ['算力芯片与软件生态', 'Computing chips and software ecosystem'], ['高估值与供应链约束', 'High valuation and supply-chain constraints'],
    ['服务器', 'Servers'], ['高性能计算与液冷服务器', 'High-performance and liquid-cooled servers'], ['资本开支波动', 'Capex volatility'],
    ['AI 服务器', 'AI Servers'], ['国内服务器核心厂商', 'Leading domestic server vendor'], ['订单与毛利率波动', 'Order and margin volatility'],
    ['光模块', 'Optical Modules'], ['高速光模块与海外算力链', 'High-speed optical modules and overseas computing chain'],
    ['海外需求与贸易风险', 'Overseas demand and trade risks'], ['大模型应用', 'Foundation Model Applications'],
    ['语音与行业大模型', 'Speech and industry foundation models'], ['商业化兑现周期', 'Commercialization cycle'],
    ['腾讯 A 股日线', 'Tencent A-share Daily'], ['Gate.io 虚拟货币', 'Gate.io Crypto'],
    ['本地股票快照', 'Local Stock Snapshot'], ['本地虚拟货币快照', 'Local Crypto Snapshot'],
    ['根已收盘日线', 'completed daily bars'], ['根训练/测试', 'training/test bars'],
    ['个候选策略', 'strategy candidates'], ['个候选', 'candidates'], ['个标的', 'assets'],
    ['笔交易', 'trades'], ['笔成交', 'fills'], ['笔（最近）', 'recent trades'],
    ['条记录', 'records'],
    ['待数据', 'need more data'], ['未启用', 'Disabled'], ['行情数据', 'Market Data'],
    ['最新收盘', 'Latest Close'], ['当日变化', 'Daily Change'], ['波动分档', 'Volatility Tier'],
    ['样本外起点', 'Out-of-sample Start'], ['板块比较', 'Sector Comparison'], ['训练', 'training'], ['测试', 'test'],
  ];

  const translations = new Map(entries);
  const orderedEntries = [...entries].sort((a, b) => b[0].length - a[0].length);

  function readLocale() {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (SUPPORTED.has(saved)) return saved;
    } catch (_) { /* Local storage may be disabled. */ }
    return String(navigator.language || '').toLowerCase().startsWith('zh') ? 'zh-CN' : 'en-US';
  }

  function translate(value) {
    const source = String(value ?? '');
    if (locale === 'zh-CN' || !/[\u3400-\u9fff]/.test(source)) return source;
    const exact = translations.get(source.trim());
    if (exact) return source.replace(source.trim(), exact);
    let result = source;
    for (const [zh, en] of orderedEntries) result = result.split(zh).join(en);
    return result
      .replace(/已为\s+(.+?)\s+生成\s+(\d+)\s+strategy candidates/, '$2 strategy candidates generated for $1')
      .replace(/(\d+)\s+assets\s+·\s+(\d+)涨\/(\d+)跌/g, '$1 assets · $2 up / $3 down')
      .replace(/(\d+)涨\/(\d+)跌/g, '$1 up / $2 down')
      .replace(/(\d+)涨\/(\d+)Down/g, '$1 up / $2 down')
      .replace(/候选\s+(\d+)\s+assets/g, '$1 candidate assets')
      .replace(/(\d+)板/g, '$1-day streak')
      .replace(/(\d+)\s*个observed assets/g, '$1 observed assets')
      .replace(/([A-Za-z])Candidates/g, '$1 Candidates')
      .replace(/(\d+(?:\.\d+)?)\s*只/g, '$1 assets')
      .replace(/(\d+(?:\.\d+)?)\s*根/g, '$1 bars')
      .replace(/(\d+(?:\.\d+)?)\s*笔/g, '$1 trades')
      .replace(/(\d+(?:\.\d+)?)\s*条/g, '$1 rows')
      .replace(/(\d+(?:\.\d+)?)\s*天/g, '$1 days')
      .replace(/(\d+(?:\.\d+)?)\s*日/g, '$1 days')
      .replace(/(\d+(?:\.\d+)?)\s*亿/g, '$1B')
      .replace(/A 股/g, 'A-share')
      .replace(/请求失败/g, 'Request failed')
      .replace(/请稍后再试/g, 'Please try again later')
      .replace(/未知数据源/g, 'Unknown data source')
      .replace(/请选择有效/g, 'Please select a valid ')
      .replace(/缺少标的代码/g, 'Asset code is required');
  }

  function translateTextNode(node) {
    if (!node.nodeValue || !node.parentElement || /^(SCRIPT|STYLE|TEXTAREA)$/i.test(node.parentElement.tagName)) return;
    const current = node.nodeValue;
    const saved = textState.get(node);
    const original = saved && current === saved.translated ? saved.original : current;
    const next = locale === 'zh-CN' ? original : translate(original);
    textState.set(node, { original, translated: next });
    if (current !== next) node.nodeValue = next;
  }

  function translateAttribute(element, name) {
    if (!element.hasAttribute(name)) return;
    const current = element.getAttribute(name) || '';
    const savedMap = attributeState.get(element) || {};
    const saved = savedMap[name];
    const original = saved && current === saved.translated ? saved.original : current;
    const next = locale === 'zh-CN' ? original : translate(original);
    savedMap[name] = { original, translated: next };
    attributeState.set(element, savedMap);
    if (current !== next) element.setAttribute(name, next);
  }

  function translateDom(root = document.body) {
    if (!root) return;
    if (root.nodeType === Node.TEXT_NODE) translateTextNode(root);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) translateTextNode(node);
    const elements = root.nodeType === Node.ELEMENT_NODE ? [root, ...root.querySelectorAll('*')] : [...document.querySelectorAll('*')];
    elements.forEach((element) => ['placeholder', 'title', 'aria-label'].forEach((name) => translateAttribute(element, name)));
    document.documentElement.lang = locale;
    const select = document.getElementById('languageSelect');
    if (select && select.value !== locale) select.value = locale;
  }

  function scheduleTranslation() {
    if (scheduled) return;
    scheduled = true;
    queueMicrotask(() => { scheduled = false; translateDom(); });
  }

  function setLocale(next) {
    if (!SUPPORTED.has(next)) return;
    locale = next;
    try { window.localStorage.setItem(STORAGE_KEY, locale); } catch (_) { /* Keep the session setting. */ }
    translateDom();
    window.dispatchEvent(new CustomEvent('quantpilot:languagechange', { detail: { locale } }));
  }

  function init() {
    const select = document.getElementById('languageSelect');
    if (select) {
      select.value = locale;
      select.addEventListener('change', (event) => setLocale(event.target.value));
    }
    translateDom();
    observer = new MutationObserver(scheduleTranslation);
    observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['placeholder', 'title', 'aria-label'] });
  }

  window.I18n = {
    getLocale: () => locale,
    localeForIntl: () => locale,
    setLocale,
    t: translate,
    translateDom,
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();

const terminalState = {
  market: null,
  indices: null,
  watchlist: [],
  scan: null,
  scanGroup: 'all',
  scanStrategy: 'all',
  scanSearch: '',
  backtest: null,
  monitor: null,
  ladder: null,
  concepts: null,
  selectedConcept: null,
  stock: null,
};

const terminalLoaded = new Set();

function terminalHostReady(host) {
  host?.classList.remove('page-loading', 'terminal-error');
}

function terminalHostError(host, error) {
  if (!host) return;
  host.classList.remove('page-loading');
  host.classList.add('terminal-error');
  host.textContent = error?.message || String(error);
}

function tMoney(value) {
  const number = Number(value || 0);
  if (Math.abs(number) >= 1e12) return `${(number / 1e12).toFixed(2)}万亿`;
  if (Math.abs(number) >= 1e8) return `${(number / 1e8).toFixed(2)}亿`;
  if (Math.abs(number) >= 1e4) return `${(number / 1e4).toFixed(2)}万`;
  return fmtNum(number);
}

function tPct(value, digits = 2) { return fmtPct(value, digits); }
function tClass(value) { return metricClass(value); }

function terminalToolbar(title, note, refreshAction = '') {
  return `<div class="terminal-page-head"><div><h2>${escapeHtml(title)}</h2><span>${escapeHtml(note || '')}</span></div>${refreshAction ? `<button class="secondary-button" data-terminal-action="${refreshAction}" title="刷新">↻ 刷新</button>` : ''}</div>`;
}

function miniSparkline(values, color = '#4a8cff') {
  const clean = values.map(Number).filter(Number.isFinite);
  if (clean.length < 2) return '';
  const width = 130, height = 38, min = Math.min(...clean), max = Math.max(...clean), spread = max - min || 1;
  const points = clean.map((value, index) => `${(index / (clean.length - 1) * width).toFixed(1)},${(height - (value - min) / spread * (height - 4) - 2).toFixed(1)}`).join(' ');
  return `<svg class="mini-spark" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none"><polyline points="${points}" fill="none" stroke="${color}" stroke-width="2"/></svg>`;
}

function barChart(items) {
  const max = Math.max(...items.map((item) => item.count), 1);
  return `<div class="breadth-bars">${items.map((item) => `<div><span>${item.count}</span><i style="height:${Math.max(5, item.count / max * 88)}px" class="${item.label.startsWith('-') || item.label.startsWith('<') ? 'down' : 'up'}"></i><small>${escapeHtml(item.label)}</small></div>`).join('')}</div>`;
}

async function loadMarket(force = false) {
  const host = $('#marketContent');
  host.innerHTML = '<div class="page-loading">正在刷新全市场快照与指数日线…</div>';
  try {
    terminalState.market = await api(`/api/terminal/market${force ? '?refresh=1' : ''}`);
    terminalLoaded.add('market');
    renderMarket();
  } catch (error) { host.innerHTML = `<div class="terminal-error">${escapeHtml(error.message)}</div>`; }
}

function rankList(title, items, metric, format) {
  return `<section class="terminal-panel rank-panel"><div class="terminal-panel-head"><h3>${escapeHtml(title)}</h3><span>TOP ${items.length}</span></div><div class="rank-list">${items.map((item, index) => `<button data-stock-open="${item.symbol}"><i>${index + 1}</i><div><strong>${escapeHtml(item.name)}</strong><small>${item.code}</small></div><b class="${tClass(metric(item))}">${format(metric(item))}</b></button>`).join('')}</div></section>`;
}

function renderMarket() {
  const host = $('#marketContent');
  terminalHostReady(host);
  const data = terminalState.market;
  const summary = data.summary;
  const complete = Boolean(data.complete), scope = complete ? `${data.universe_count} 只` : `${data.universe_count}/${data.reported_total} 只 · 覆盖 ${fmtNum(data.coverage * 100, 1)}%`;
  host.innerHTML = `${terminalToolbar('市场看板', `${data.source} · ${data.as_of}${data.stale ? ' · 缓存数据' : ''} · ${scope}`, 'refresh-market')}
    ${data.warning ? `<div class="terminal-warning">${escapeHtml(data.warning)}</div>` : ''}
    ${complete ? '' : '<div class="terminal-warning">市场快照当前为部分覆盖，榜单仍可查看；涨跌家数、广度、全市场均值暂不作为完整市场结论。</div>'}
    <div class="index-strip">${data.indices.map((item) => item.error ? `<div class="index-card"><span>${escapeHtml(item.name)}</span><small>${escapeHtml(item.error)}</small></div>` : `<button class="index-card" data-index-symbol="${item.symbol}"><div><span>${escapeHtml(item.name)}</span><small>${item.symbol}</small></div><strong class="${tClass(item.change)}">${tPct(item.change)}</strong><b>${fmtNum(item.price)}</b>${miniSparkline(item.series.map((point) => point.close), item.change >= 0 ? '#ff5f67' : '#2dc78d')}</button>`).join('')}</div>
    <div class="market-kpis">
      ${[['个股涨 / 平 / 跌', complete ? `${summary.up} / ${summary.flat} / ${summary.down}` : '待完整快照', complete ? `上涨率 ${fmtNum(summary.up / data.universe_count * 100, 1)}%` : scope], ['强势 / 弱势', complete ? `${summary.strong} / ${summary.weak}` : '待完整快照', '涨跌幅超过 3%'], ['涨停 / 跌停', complete ? `${summary.limit_up} / ${summary.limit_down}` : '待完整快照', '按板块近似阈值汇总'], ['成交额', complete ? tMoney(summary.amount) : '部分样本', scope], ['换手 / 量比', complete ? `${tPct(summary.average_turnover, 1)} / ${fmtNum(summary.average_volume_ratio)}` : '部分样本', complete ? '全市场简单平均' : '不作全市场结论']].map(([label, value, note]) => `<div class="terminal-kpi"><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`).join('')}
    </div>
    <div class="market-grid">
      <section class="terminal-panel breadth-panel"><div class="terminal-panel-head"><h3>涨跌分布 / 广度</h3><span>${scope}</span></div>${complete ? `${barChart(data.breadth)}<div class="breadth-summary"><b class="positive">涨 ${summary.up}</b><b>平 ${summary.flat}</b><b class="negative">跌 ${summary.down}</b><span>平均 ${tPct(summary.mean_change)}</span><span>中位 ${tPct(summary.median_change)}</span></div>` : '<div class="terminal-empty">部分覆盖快照不计算市场广度</div>'}</section>
      <section class="terminal-panel"><div class="terminal-panel-head"><h3>趋势强度</h3><span>指数均线 / 新高低</span></div><div class="trend-matrix">${data.indices.filter((item) => !item.error).map((item) => `<div><strong>${escapeHtml(item.name)}</strong><span class="${item.price > item.ma5 ? 'positive' : 'negative'}">站上 MA5 ${item.price > item.ma5 ? '是' : '否'}</span><span class="${item.price > item.ma20 ? 'positive' : 'negative'}">站上 MA20 ${item.price > item.ma20 ? '是' : '否'}</span><span>60日位置 ${fmtNum((item.price - item.low60) / Math.max(item.high60 - item.low60, 0.01) * 100, 0)}%</span></div>`).join('')}</div></section>
      <section class="terminal-panel"><div class="terminal-panel-head"><h3>监控中心</h3><button class="row-button" data-nav-view="monitor">查看规则 →</button></div><div id="marketMonitorPreview" class="monitor-preview"><span>正在读取触发记录…</span></div></section>
    </div>
    <div class="group-heat terminal-panel"><div class="terminal-panel-head"><h3>板块热度</h3><span>项目配置标的池</span></div><div class="heat-columns"><div><h4 class="positive">领涨</h4>${data.groups.slice().sort((a,b) => b.change-a.change).slice(0,5).map(groupRow).join('')}</div><div><h4 class="negative">领跌</h4>${data.groups.slice().sort((a,b) => a.change-b.change).slice(0,5).map(groupRow).join('')}</div></div></div>
    <div class="rank-grid">${rankList('涨幅榜', data.leaders, item => item.change, value => tPct(value))}${rankList('跌幅榜', data.laggards, item => item.change, value => tPct(value))}${rankList('成交额榜', data.turnover_leaders, item => item.amount, value => tMoney(value))}${rankList('活跃换手', data.active, item => item.turnover, value => tPct(value, 1))}</div>`;
  bindTerminalActions(host);
  loadMonitorPreview();
}

function groupRow(group) {
  return `<button class="group-row" data-concept-id="${group.id}"><div><strong>${escapeHtml(group.name)}</strong><small>${group.count} 只 · ${group.up}涨/${group.down}跌</small></div><b class="${tClass(group.change)}">${tPct(group.change)}</b></button>`;
}

async function loadMonitorPreview() {
  try {
    const data = await api('/api/terminal/monitor');
    const host = $('#marketMonitorPreview');
    if (!host) return;
    host.innerHTML = (data.events || []).slice(0, 5).map((event) => `<button data-nav-view="monitor"><strong>${escapeHtml(event.name)}</strong><span>${monitorTypeLabel(event.type)} ${monitorValue(event.type, event.current)}</span><small>${String(event.triggered_at).replace('T', ' ')}</small></button>`).join('') || '<span>暂无触发记录，可在监控中心添加规则。</span>';
    $('#monitorBadge').textContent = data.events?.length ? data.events.length : '';
  } catch (_) {}
}

async function loadStrategyScan(force = false) {
  const host = $('#view-factory .factory-results');
  const scanHost = ensureScanPanel();
  scanHost.innerHTML = '<div class="page-loading">正在扫描研究标的池…</div>';
  try {
    terminalState.scan = await api('/api/terminal/strategy-scan', { method: 'POST', body: JSON.stringify({ group: terminalState.scanGroup, strategy: terminalState.scanStrategy, force }) });
    terminalLoaded.add('scan');
    renderStrategyScan();
  } catch (error) { scanHost.innerHTML = `<div class="terminal-error">${escapeHtml(error.message)}</div>`; }
}

function ensureScanPanel() {
  let panel = $('#strategyScanPanel');
  if (!panel) {
    panel = document.createElement('div');
    panel.id = 'strategyScanPanel';
    panel.className = 'strategy-scan-panel';
    $('#view-factory').prepend(panel);
  }
  return panel;
}

function renderStrategyScan() {
  const host = ensureScanPanel();
  const data = terminalState.scan;
  const groups = state.universe?.groups?.stocks || [];
  const strategies = Object.entries(data.strategy_labels || {});
  const query = terminalState.scanSearch.toLowerCase();
  const items = (data.items || []).filter(item => !query || `${item.name}${item.symbol}${item.strategy_name}${item.group_name}`.toLowerCase().includes(query));
  host.innerHTML = `${terminalToolbar('策略池扫描', `命中 ${items.length} 只 · 扫描 ${data.scanned} 只 · ${data.as_of}`, 'refresh-scan')}
    <div class="scan-toolbar"><select id="scanGroup"><option value="all">全部板块</option>${groups.map(group => `<option value="${group.id}" ${terminalState.scanGroup === group.id ? 'selected' : ''}>${escapeHtml(group.name)}</option>`).join('')}</select><select id="scanStrategy"><option value="all">全部策略</option>${strategies.map(([id,name]) => `<option value="${id}" ${terminalState.scanStrategy === id ? 'selected' : ''}>${escapeHtml(name)}</option>`).join('')}</select><input id="scanSearch" value="${escapeHtml(terminalState.scanSearch)}" placeholder="搜索代码、名称或策略"><button class="secondary-button" id="runScanButton">运行扫描</button></div>
    <div class="scan-table table-page"><div class="table-scroll terminal-table-scroll"><table><thead><tr><th>标的</th><th>策略</th><th>评分</th><th>现价</th><th>涨跌幅</th><th>量比</th><th>板块</th><th>日 K</th><th>60D 动量</th><th>操作</th></tr></thead><tbody>${items.map(item => `<tr><td><button class="stock-link" data-stock-open="${item.symbol}"><strong>${escapeHtml(item.name)}</strong><small>${item.symbol}</small></button></td><td><span class="tag">${escapeHtml(item.strategy_name)}</span></td><td><b class="score-value">${fmtNum(item.score,1)}</b></td><td class="mono">${fmtNum(item.price)}</td><td class="${tClass(item.change)} mono">${tPct(item.change)}</td><td>${fmtNum(item.volume_ratio)}</td><td>${escapeHtml(item.group_name)}</td><td>${miniCandles(item.series)}</td><td class="${tClass(item.momentum60)} mono">${tPct(item.momentum60)}</td><td><button class="icon-mini" data-watch-add="${item.symbol}" data-name="${escapeHtml(item.name)}" data-group="${escapeHtml(item.group_name)}" title="加入自选">☆</button></td></tr>`).join('') || '<tr><td colspan="10">当前条件没有命中标的</td></tr>'}</tbody></table></div></div>`;
  $('#scanGroup').addEventListener('change', event => { terminalState.scanGroup = event.target.value; });
  $('#scanStrategy').addEventListener('change', event => { terminalState.scanStrategy = event.target.value; });
  $('#scanSearch').addEventListener('input', event => { terminalState.scanSearch = event.target.value; renderStrategyScan(); });
  $('#runScanButton').addEventListener('click', () => loadStrategyScan(true));
  bindTerminalActions(host);
}

function miniCandles(series) {
  if (!series?.length) return '—';
  const width=126, height=44, high=Math.max(...series.map(p=>p.high)), low=Math.min(...series.map(p=>p.low)), range=high-low||1, step=width/series.length;
  return `<svg class="mini-candles" viewBox="0 0 ${width} ${height}">${series.map((p,i)=>{const x=i*step+step/2, yH=(high-p.high)/range*(height-4)+2, yL=(high-p.low)/range*(height-4)+2, yO=(high-p.open)/range*(height-4)+2, yC=(high-p.close)/range*(height-4)+2, color=p.close>=p.open?'#ff5f67':'#2dc78d'; return `<line x1="${x}" x2="${x}" y1="${yH}" y2="${yL}" stroke="${color}"/><rect x="${x-step*.25}" y="${Math.min(yO,yC)}" width="${step*.5}" height="${Math.max(1,Math.abs(yC-yO))}" fill="${color}"/>`;}).join('')}</svg>`;
}

async function updateWatchlist(action, symbol, name='', group='') {
  const result = await api('/api/terminal/watchlist', { method:'POST', body: JSON.stringify({action,symbol,name,group}) });
  terminalState.watchlist = result.items || [];
  toast(action === 'remove' ? '已移出自选' : '已加入自选');
  if ($('#view-watchlist').classList.contains('active')) renderWatchlist();
}

async function loadWatchlist() {
  const result = await api('/api/terminal/watchlist');
  terminalState.watchlist = result.items || [];
  terminalLoaded.add('watchlist');
  renderWatchlist();
}

function renderWatchlist() {
  const host=$('#watchlistContent');
  terminalHostReady(host);
  host.innerHTML=`${terminalToolbar('我的自选', `${terminalState.watchlist.length} 个标的 · 本地保存`)}<div class="watchlist-grid">${terminalState.watchlist.map(item=>`<article class="watch-card"><button data-stock-open="${item.symbol}"><strong>${escapeHtml(item.name)}</strong><span>${item.symbol}</span><small>${escapeHtml(item.group || '未分类')}</small></button><button class="icon-mini danger-button" data-watch-remove="${item.symbol}" title="移除">×</button></article>`).join('') || '<div class="terminal-empty">暂无自选标的，可在策略扫描页点击星标添加。</div>'}</div>`;
  bindTerminalActions(host);
}

function renderBacktestForm() {
  const host=$('#backtestContent');
  const groups=state.universe?.groups?.stocks||[], strategies=terminalState.scan?.strategy_labels||{
    adaptive_trend:'自适应趋势',channel_breakout:'通道突破',supertrend_adx:'SuperTrend + ADX',turtle_atr:'海龟突破 + ATR',bollinger_rsi:'布林带 + RSI',macd_volume:'MACD + 成交量',squeeze_breakout:'波动率挤压',multi_timeframe:'多周期趋势',regime_adaptive:'状态自适应',signal_voting:'多信号投票'};
  host.innerHTML=`${terminalToolbar('回测工作台','板块多标的组合回测 · 收盘信号次日开盘执行')}
    <div class="backtest-layout"><aside class="backtest-settings terminal-panel"><label>策略<select id="btStrategy">${Object.entries(strategies).map(([id,name])=>`<option value="${id}">${escapeHtml(name)}</option>`).join('')}</select></label><label>股票池<select id="btGroup">${groups.map(group=>`<option value="${group.id}">${escapeHtml(group.name)} · ${group.assets.length}只</option>`).join('')}</select></label><div class="form-pair"><label>初始资金<input id="btCash" type="number" value="100000" min="1000"></label><label>最大持仓数<input id="btPositions" type="number" value="3" min="1" max="5"></label></div><div class="form-pair"><label>最大总仓位 %<input id="btExposure" type="number" value="100" min="10" max="100"></label><label>回测天数<input id="btLookback" type="number" value="300" min="80" max="1000"></label></div><div class="form-pair"><label>止损 %<input id="btStop" type="number" value="8" min="0" max="50"></label><label>止盈 %<input id="btTake" type="number" value="25" min="0" max="200"></label></div><label>最长持有日<input id="btHold" type="number" value="60" min="1" max="1000"></label><button class="primary-button" id="runBacktest">▶ 运行回测</button><div class="paper-rules"><span>训练段定参</span><span>次日开盘</span><span>费用建模</span><span>多标的组合</span></div></aside><main id="backtestResult" class="backtest-result"><div class="terminal-empty">配置参数后运行组合回测。</div></main></div>`;
  $('#runBacktest').addEventListener('click', runBacktest);
}

async function runBacktest() {
  const button=$('#runBacktest'), host=$('#backtestResult'); button.disabled=true; host.innerHTML='<div class="page-loading">正在获取板块历史并运行组合回测…</div>';
  const payload={strategy:$('#btStrategy').value,group:$('#btGroup').value,initial_cash:Number($('#btCash').value),max_positions:Number($('#btPositions').value),max_exposure:Number($('#btExposure').value)/100,lookback:Number($('#btLookback').value),stop_loss:Number($('#btStop').value)/100,take_profit:Number($('#btTake').value)/100,max_hold:Number($('#btHold').value)};
  try { terminalState.backtest=await api('/api/terminal/backtest',{method:'POST',body:JSON.stringify(payload)}); renderBacktestResult(); }
  catch(error){host.innerHTML=`<div class="terminal-error">${escapeHtml(error.message)}</div>`;} finally{button.disabled=false;}
}

function renderBacktestResult(){
  const host=$('#backtestResult'), d=terminalState.backtest, m=d.metrics;
  host.innerHTML=`<div class="backtest-title"><div><h3>${escapeHtml(d.strategy_name)} · ${escapeHtml(d.group.name)}</h3><span>${d.series[0]?.date} → ${d.series.at(-1)?.date} · ${d.series.length} 日</span></div><b>${d.trades.length} 笔交易</b></div><div class="backtest-kpis">${[['总收益',tPct(m.total_return),tClass(m.total_return)],['年化',tPct(m.annual_return),tClass(m.annual_return)],['基准',tPct(d.benchmark_return),tClass(d.benchmark_return)],['超额',tPct(d.excess_return),tClass(d.excess_return)],['夏普',fmtNum(m.sharpe),''],['最大回撤',tPct(m.max_drawdown),'negative'],['胜率',tPct(d.win_rate),''],['最终权益',fmtNum(d.final_equity),'']].map(([l,v,c])=>`<div><span>${l}</span><strong class="${c}">${v}</strong></div>`).join('')}</div><div class="terminal-warning"><b>成交约束：</b>${d.execution_notes.map(escapeHtml).join(' · ')}</div><section class="terminal-panel"><div class="terminal-panel-head"><h3>策略净值 / 基准 / 回撤</h3></div><div id="backtestChart" class="terminal-chart"></div></section><section class="terminal-panel"><div class="terminal-panel-head"><h3>交易明细</h3><span>${d.trades.length} 笔</span></div><div class="table-scroll backtest-trades"><table><thead><tr><th>标的</th><th>买入</th><th>卖出</th><th>持有</th><th>净收益</th><th>原因</th></tr></thead><tbody>${d.trades.slice().reverse().map(t=>`<tr><td>${escapeHtml(t.name)}<small>${t.symbol}</small></td><td>${t.entry_date}<small>${fmtNum(t.entry_price)}</small></td><td>${t.exit_date}<small>${fmtNum(t.exit_price)}</small></td><td>${t.holding_days}日</td><td class="${tClass(t.net_return)}">${tPct(t.net_return)}</td><td>${escapeHtml(t.reason)}</td></tr>`).join('')||'<tr><td colspan="6">没有完成交易</td></tr>'}</tbody></table></div></section>`; drawTerminalLineChart($('#backtestChart'),d.series);
}

function drawTerminalLineChart(host, series){
  if(!host||!series.length)return; const width=Math.max(700,host.clientWidth||900),height=320,p={l:45,r:18,t:18,b:28}, vals=series.flatMap(x=>[x.equity,x.benchmark]),min=Math.min(...vals),max=Math.max(...vals),spread=max-min||1,x=i=>p.l+i*(width-p.l-p.r)/Math.max(1,series.length-1),y=v=>p.t+(max-v)/spread*(height-p.t-p.b),path=key=>series.map((v,i)=>`${i?'L':'M'}${x(i).toFixed(1)},${y(v[key]).toFixed(1)}`).join(' '); host.innerHTML=`<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">${[0,.25,.5,.75,1].map(r=>`<line class="chart-grid" x1="${p.l}" x2="${width-p.r}" y1="${p.t+r*(height-p.t-p.b)}" y2="${p.t+r*(height-p.t-p.b)}"/>`).join('')}<path class="chart-benchmark" d="${path('benchmark')}"/><path class="chart-strategy" d="${path('equity')}"/></svg>`;
}

function monitorTypeLabel(type){return ({price_above:'价格高于',price_below:'价格低于',change_above:'涨幅达到',change_below:'跌幅达到',volume_ratio_above:'量比达到'}[type]||type);}
function monitorValue(type,value){return type.startsWith('change_')?tPct(value):fmtNum(value);}

async function loadMonitor(){terminalState.monitor=await api('/api/terminal/monitor');terminalLoaded.add('monitor');renderMonitor();}
function renderMonitor(){
  const host=$('#monitorContent'),d=terminalState.monitor; $('#monitorBadge').textContent=d.events?.length?d.events.length:'';
  terminalHostReady(host);
  host.innerHTML=`${terminalToolbar('监控中心', '本地规则 · 手动刷新市场快照后评估', 'evaluate-monitor')}<div class="monitor-layout"><main class="terminal-panel"><div class="terminal-panel-head"><h3>触发记录</h3><button class="row-button" data-monitor-clear>清空</button></div><div class="event-list">${(d.events||[]).map(e=>`<article><div><strong>${escapeHtml(e.name)}</strong><small>${e.symbol}</small><span class="tag">${monitorTypeLabel(e.type)}</span></div><b class="${tClass(e.change)}">${monitorValue(e.type,e.current)}</b><p>阈值 ${monitorValue(e.type,e.threshold)} · 股价 ${fmtNum(e.price)} · ${String(e.triggered_at).replace('T',' ')}</p></article>`).join('')||'<div class="terminal-empty">暂无触发记录</div>'}</div></main><aside><section class="terminal-panel monitor-add"><div class="terminal-panel-head"><h3>新增规则</h3></div><label>股票代码<input id="monitorSymbol" placeholder="600519 / sh600519"></label><label>显示名称<input id="monitorName" placeholder="可选"></label><label>规则<select id="monitorType">${d.rule_types.map(t=>`<option value="${t.id}">${escapeHtml(t.name)}</option>`).join('')}</select></label><label>阈值<input id="monitorThreshold" type="number" step="0.01" value="5"></label><button class="primary-button" id="addMonitorRule">添加规则</button></section><section class="terminal-panel rule-list"><div class="terminal-panel-head"><h3>监控规则</h3><span>${d.rules.length}</span></div>${d.rules.map(r=>`<article><div><strong>${escapeHtml(r.name)}</strong><small>${r.symbol} · ${monitorTypeLabel(r.type)} ${monitorValue(r.type,r.threshold)}</small></div><button class="icon-mini danger-button" data-monitor-delete="${r.id}">×</button></article>`).join('')||'<div class="terminal-empty">暂无规则</div>'}</section></aside></div>`;
  $('#addMonitorRule').addEventListener('click',addMonitorRule); bindTerminalActions(host);
}
async function addMonitorRule(){try{terminalState.monitor=await api('/api/terminal/monitor',{method:'POST',body:JSON.stringify({action:'add',symbol:$('#monitorSymbol').value,name:$('#monitorName').value,type:$('#monitorType').value,threshold:monitorThresholdValue()})});renderMonitor();toast('监控规则已添加');}catch(e){toast(e.message,true);}}
function monitorThresholdValue(){const type=$('#monitorType').value,value=Number($('#monitorThreshold').value);return type.startsWith('change_')?value/100:value;}

async function loadLadder(force=false){const host=$('#ladderContent');host.innerHTML='<div class="page-loading">正在计算涨停候选与连续涨停天数…</div>';try{terminalState.ladder=await api(`/api/terminal/limit-ladder${force?'?refresh=1':''}`);terminalLoaded.add('ladder');renderLadder();}catch(e){host.innerHTML=`<div class="terminal-error">${escapeHtml(e.message)}</div>`;}}
function renderLadder(){const host=$('#ladderContent'),d=terminalState.ladder;terminalHostReady(host);host.innerHTML=`${terminalToolbar('连板梯队',`${d.source} · ${d.as_of} · 候选 ${d.total} 只`,'refresh-ladder')}<div class="terminal-warning">连续涨停按日线收盘涨幅和板块阈值近似计算；封单额、炸板次数需要逐笔/盘口数据，当前不伪造。</div><div class="ladder-stack">${[4,3,2,1].map(level=>`<section class="ladder-level level-${level}"><div class="terminal-panel-head"><h3>${level===4?'4板及以上':`${level}板`} · ${(d.ladders[level]||[]).length}</h3></div><div class="ladder-cards">${(d.ladders[level]||[]).map(item=>`<button data-stock-open="${item.symbol}"><strong>${escapeHtml(item.name)}</strong><span>${item.code}</span><b class="positive">${tPct(item.change)}</b><small>${item.streak} 连板 · ${tMoney(item.amount)}</small><div>${(item.groups||[]).map(g=>`<i>${escapeHtml(g)}</i>`).join('')}</div></button>`).join('')||'<span class="terminal-empty">暂无</span>'}</div></section>`).join('')}</div>`;bindTerminalActions(host);}

async function loadConcepts(force=false){const host=$('#conceptContent');host.innerHTML='<div class="page-loading">正在计算配置板块强弱…</div>';try{terminalState.concepts=await api(`/api/terminal/concepts${force?'?refresh=1':''}`);terminalLoaded.add('concepts');renderConcepts();}catch(e){host.innerHTML=`<div class="terminal-error">${escapeHtml(e.message)}</div>`;}}
function renderConcepts(){const host=$('#conceptContent'),d=terminalState.concepts;terminalHostReady(host);if(!terminalState.selectedConcept)terminalState.selectedConcept=d.groups[0]?.id;const selected=d.groups.find(g=>g.id===terminalState.selectedConcept)||d.groups[0];host.innerHTML=`${terminalToolbar('概念分析',`${d.as_of} · ${d.scope_note}`,'refresh-concepts')}<div class="concept-kpis">${[['最强主线',d.strongest?.name,tPct(d.strongest?.change)],['最大风险',d.weakest?.name,tPct(d.weakest?.change)],['覆盖板块',d.groups.length,'项目配置池'],['资金活跃',d.groups.slice().sort((a,b)=>b.amount-a.amount)[0]?.name,tMoney(d.groups.slice().sort((a,b)=>b.amount-a.amount)[0]?.amount)]].map(([l,v,n])=>`<div><span>${l}</span><strong>${escapeHtml(v||'—')}</strong><small>${escapeHtml(n||'')}</small></div>`).join('')}</div><div class="heat-columns terminal-panel"><div><h4 class="positive">领涨方向</h4>${d.leaders.map(groupRow).join('')}</div><div><h4 class="negative">领跌方向</h4>${d.laggards.map(groupRow).join('')}</div></div>${selected?conceptDetail(selected):''}`;bindTerminalActions(host);}
function conceptDetail(group){return `<section class="terminal-panel concept-detail"><div class="terminal-panel-head"><div><h3>${escapeHtml(group.name)}</h3><span>${group.count}只 · ${group.up}涨/${group.down}跌 · 平均 ${tPct(group.change)}</span></div></div><div class="concept-metrics"><div><span>中位涨跌</span><b class="${tClass(group.median_change)}">${tPct(group.median_change)}</b></div><div><span>成交额</span><b>${tMoney(group.amount)}</b></div><div><span>换手率</span><b>${tPct(group.turnover,1)}</b></div><div><span>量比</span><b>${fmtNum(group.volume_ratio)}</b></div></div><div class="concept-members">${group.members.map(item=>`<button data-stock-open="${item.symbol}"><strong>${escapeHtml(item.name)}</strong><span>${item.code}</span><b class="${tClass(item.change)}">${tPct(item.change)}</b><small>换手 ${tPct(item.turnover,1)} · 成交 ${tMoney(item.amount)}</small></button>`).join('')}</div></section>`;}

function renderStockForm(){const host=$('#stockAnalysisContent');host.innerHTML=`${terminalToolbar('个股分析','输入 A 股代码查看日线、指标和策略候选')}<div class="stock-search terminal-panel"><input id="stockAnalysisSymbol" placeholder="600519 / sh600519"><button class="primary-button" id="runStockAnalysis">分析</button></div><div id="stockAnalysisResult"><div class="terminal-empty">等待输入股票代码</div></div>`;$('#runStockAnalysis').addEventListener('click',()=>loadStockAnalysis($('#stockAnalysisSymbol').value));}
async function loadStockAnalysis(symbol){const host=$('#stockAnalysisResult');host.innerHTML='<div class="page-loading">正在获取日线并计算策略…</div>';try{terminalState.stock=await api(`/api/terminal/stock/${encodeURIComponent(symbol)}`);renderStockAnalysisResult();}catch(e){host.innerHTML=`<div class="terminal-error">${escapeHtml(e.message)}</div>`;}}
function renderStockAnalysisResult(){const host=$('#stockAnalysisResult'),d=terminalState.stock;host.innerHTML=`<div class="stock-analysis-head"><div><h3>${d.symbol}</h3><span>${d.latest.date} · ${d.profile.volatility_tier}</span></div><strong>${fmtNum(d.latest.close)}</strong><b class="${tClass(d.latest.change)}">${tPct(d.latest.change)}</b><button class="secondary-button" data-factory-symbol="${d.symbol}">转到策略工坊</button></div><section class="terminal-panel"><div class="terminal-panel-head"><h3>价格 / MA20 / MA60</h3></div><div id="stockPriceChart" class="terminal-chart"></div></section><div class="candidate-grid compact-candidates">${d.candidates.slice(0,8).map(c=>`<article class="candidate-card" style="--family-color:${familyColor(c.family)}"><div class="candidate-top"><span>${escapeHtml(c.family)}</span><b>#${c.rank}</b></div><h3>${escapeHtml(c.name)}</h3><div class="candidate-primary"><span>样本外</span><strong class="${tClass(c.test.total_return)}">${tPct(c.test.total_return)}</strong></div><div class="mini-metrics"><div><span>超额</span><b class="${tClass(c.test.excess_return)}">${tPct(c.test.excess_return)}</b></div><div><span>回撤</span><b class="negative">${tPct(c.test.max_drawdown)}</b></div></div></article>`).join('')}</div>`;drawStockChart($('#stockPriceChart'),d.series);bindTerminalActions(host);}
function drawStockChart(host,series){const width=Math.max(700,host.clientWidth||900),height=300,p={l:45,r:16,t:15,b:25},values=series.flatMap(v=>[v.close,v.ma20,v.ma60].filter(Number.isFinite)),min=Math.min(...values),max=Math.max(...values),spread=max-min||1,x=i=>p.l+i*(width-p.l-p.r)/(series.length-1),y=v=>p.t+(max-v)/spread*(height-p.t-p.b),path=k=>series.map((v,i)=>Number.isFinite(v[k])?`${i?'L':'M'}${x(i).toFixed(1)},${y(v[k]).toFixed(1)}`:'').join(' ');host.innerHTML=`<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none"><path class="chart-strategy" d="${path('close')}"/><path class="chart-benchmark ma20" d="${path('ma20')}"/><path class="chart-benchmark ma60" d="${path('ma60')}"/></svg>`;}

function renderFinance(){const host=$('#financeContent');host.innerHTML=`${terminalToolbar('财务数据覆盖','当前项目未接入授权财报源，不展示虚构财务指标')}<div class="terminal-panel finance-boundary"><h3>可用与待接入</h3><div class="boundary-grid"><article><b class="positive">已可用</b><span>价格、成交额、换手、量比、市值、技术指标、回测与模拟交易</span></article><article><b class="negative">尚未接入</b><span>利润表、资产负债表、现金流、估值历史、机构一致预期</span></article></div><p>财务模块需要明确数据源授权和复权口径。接入前不会用随机数或过期样例填充。</p></div>`;}

async function loadIndices(force=false){const host=$('#indicesContent');host.innerHTML='<div class="page-loading">正在读取四个主要指数日线…</div>';try{terminalState.indices=await api(`/api/terminal/indices${force?'?refresh=1':''}`);terminalLoaded.add('indices');renderIndices();}catch(e){terminalHostError(host,e);}}
function renderIndices(){const host=$('#indicesContent'),d=terminalState.indices;if(!d)return;terminalHostReady(host);host.innerHTML=`${terminalToolbar('指数分析',`${d.as_of} · ${d.source}${d.stale?' · 缓存数据':''}`,'refresh-indices')}${d.warning?`<div class="terminal-warning">${escapeHtml(d.warning)}</div>`:''}<div class="index-analysis-grid">${d.indices.filter(i=>!i.error).map(i=>`<article class="terminal-panel"><div class="index-analysis-head"><div><h3>${escapeHtml(i.name)}</h3><span>${i.symbol}</span></div><strong>${fmtNum(i.price)}</strong><b class="${tClass(i.change)}">${tPct(i.change)}</b></div>${miniSparkline(i.series.map(p=>p.close),i.change>=0?'#ff5f67':'#2dc78d')}<dl><div><dt>MA5</dt><dd>${fmtNum(i.ma5)}</dd></div><div><dt>MA20</dt><dd>${fmtNum(i.ma20)}</dd></div><div><dt>MA60</dt><dd>${fmtNum(i.ma60)}</dd></div><div><dt>60日高/低</dt><dd>${fmtNum(i.high60)} / ${fmtNum(i.low60)}</dd></div></dl></article>`).join('')}</div>`;bindTerminalActions(host);}

function bindTerminalActions(root=document){
  root.querySelectorAll('[data-terminal-action="refresh-market"]').forEach(b=>b.onclick=()=>loadMarket(true));
  root.querySelectorAll('[data-terminal-action="refresh-scan"]').forEach(b=>b.onclick=()=>loadStrategyScan(true));
  root.querySelectorAll('[data-terminal-action="refresh-ladder"]').forEach(b=>b.onclick=()=>loadLadder(true));
  root.querySelectorAll('[data-terminal-action="refresh-concepts"]').forEach(b=>b.onclick=()=>loadConcepts(true));
  root.querySelectorAll('[data-terminal-action="refresh-indices"]').forEach(b=>b.onclick=()=>loadIndices(true));
  root.querySelectorAll('[data-terminal-action="evaluate-monitor"]').forEach(b=>b.onclick=async()=>{terminalState.monitor=await api('/api/terminal/monitor',{method:'POST',body:JSON.stringify({action:'evaluate',force:true})});renderMonitor();toast('监控规则已评估');});
  root.querySelectorAll('[data-nav-view]').forEach(b=>b.onclick=()=>switchView(b.dataset.navView));
  root.querySelectorAll('[data-stock-open]').forEach(b=>b.onclick=()=>{switchView('stock');if(!$('#stockAnalysisSymbol'))renderStockForm();$('#stockAnalysisSymbol').value=b.dataset.stockOpen;loadStockAnalysis(b.dataset.stockOpen);});
  root.querySelectorAll('[data-watch-add]').forEach(b=>b.onclick=()=>updateWatchlist('add',b.dataset.watchAdd,b.dataset.name,b.dataset.group));
  root.querySelectorAll('[data-watch-remove]').forEach(b=>b.onclick=()=>updateWatchlist('remove',b.dataset.watchRemove));
  root.querySelectorAll('[data-concept-id]').forEach(b=>b.onclick=()=>{terminalState.selectedConcept=b.dataset.conceptId;switchView('concepts');renderConcepts();});
  root.querySelectorAll('[data-monitor-delete]').forEach(b=>b.onclick=async()=>{terminalState.monitor=await api('/api/terminal/monitor',{method:'POST',body:JSON.stringify({action:'delete',id:Number(b.dataset.monitorDelete)})});renderMonitor();});
  root.querySelectorAll('[data-monitor-clear]').forEach(b=>b.onclick=async()=>{terminalState.monitor=await api('/api/terminal/monitor',{method:'POST',body:JSON.stringify({action:'clear_events'})});renderMonitor();});
  root.querySelectorAll('[data-factory-symbol]').forEach(b=>b.onclick=()=>{switchView('factory');$('#customSymbolInput').value=b.dataset.factorySymbol;$('#customAssetNameInput').value='';});
}

async function terminalViewChanged(view){
  try{
    if(view==='market'&&!terminalLoaded.has('market'))await loadMarket();
    if(view==='watchlist'&&!terminalLoaded.has('watchlist'))await loadWatchlist();
    if(view==='factory'&&!terminalLoaded.has('scan'))await loadStrategyScan();
    if(view==='backtest'&&!$('#runBacktest'))renderBacktestForm();
    if(view==='monitor'&&!terminalLoaded.has('monitor'))await loadMonitor();
    if(view==='ladder'&&!terminalLoaded.has('ladder'))await loadLadder();
    if(view==='concepts'&&!terminalLoaded.has('concepts'))await loadConcepts();
    if(view==='stock'&&!$('#runStockAnalysis'))renderStockForm();
    if(view==='finance'&&!$('#financeContent').children.length)renderFinance();
    if(view==='indices'&&!terminalLoaded.has('indices'))await loadIndices();
  }catch(error){toast(error.message,true);}
}

document.addEventListener('DOMContentLoaded',()=>{
  const observer=new MutationObserver(()=>{const active=$('.view.active');if(active)terminalViewChanged(active.id.replace('view-',''));});
  observer.observe(document.querySelector('.main-content'),{subtree:true,attributes:true,attributeFilter:['class']});
  window.setTimeout(()=>terminalViewChanged('market'),50);
});

const state = {
  overview: null,
  datasets: [],
  candidates: null,
  selectedCandidate: null,
  source: 'tencent',
  universe: null,
  paper: null,
  paperDraft: null,
  brokers: null,
  brokerProvider: 'local',
  brokerSnapshot: null,
  okxStrategyDraft: null,
  okxStrategyPreview: null,
  chart: 'equity',
  loadedViews: new Set(),
  dataHealth: null,
  strategyVersions: [],
  candidateBaselines: new Map(),
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const OKX_STRATEGY_STORAGE_KEY = 'quant-dashboard-okx-demo-strategy-v1';
const STRATEGY_VERSION_STORAGE_KEY = 'quantpilot-strategy-versions-v1';

function cloneJson(value) { return JSON.parse(JSON.stringify(value)); }

function restoreStrategyVersions() {
  try {
    const saved = JSON.parse(window.localStorage.getItem(STRATEGY_VERSION_STORAGE_KEY) || '[]');
    state.strategyVersions = Array.isArray(saved) ? saved.filter((item) => item && typeof item === 'object' && item.id && item.strategy_id && item.parameters && item.request).slice(0, 50) : [];
  } catch (_) {
    state.strategyVersions = [];
    window.localStorage.removeItem(STRATEGY_VERSION_STORAGE_KEY);
  }
}

function persistStrategyVersions() {
  try { window.localStorage.setItem(STRATEGY_VERSION_STORAGE_KEY, JSON.stringify(state.strategyVersions.slice(0, 50))); }
  catch (_) { toast('浏览器无法保存策略版本，请使用导出 JSON', true); }
}

function restoreOkxStrategyDraft() {
  try {
    const saved = JSON.parse(window.localStorage.getItem(OKX_STRATEGY_STORAGE_KEY) || 'null');
    if (!saved || typeof saved !== 'object' || !/^[A-Z0-9]{2,12}-USDT$/.test(saved.inst_id || '') || !saved.strategy_id || !saved.parameters || typeof saved.parameters !== 'object') return;
    state.okxStrategyDraft = saved;
  } catch (_) {
    window.localStorage.removeItem(OKX_STRATEGY_STORAGE_KEY);
  }
}

function persistOkxStrategyDraft() {
  try {
    if (state.okxStrategyDraft) window.localStorage.setItem(OKX_STRATEGY_STORAGE_KEY, JSON.stringify(state.okxStrategyDraft));
    else window.localStorage.removeItem(OKX_STRATEGY_STORAGE_KEY);
  } catch (_) {
    // 浏览器禁用本地存储时仍允许当前会话继续使用策略。
  }
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
}

function fmtPct(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return `${Number(value) >= 0 ? '+' : ''}${(Number(value) * 100).toFixed(digits)}%`;
}

function fmtNum(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return Number(value).toLocaleString(window.I18n?.localeForIntl?.() || 'zh-CN', { maximumFractionDigits: digits });
}

function metricClass(value) { return Number(value) >= 0 ? 'positive' : 'negative'; }

function closeSidebar() {
  const sidebar = $('#sidebar');
  if (!sidebar) return;
  sidebar.classList.remove('open');
  if (window.matchMedia('(max-width: 820px)').matches) sidebar.style.transform = 'translateX(-100%)';
}

function toast(message, error = false) {
  const el = $('#toast');
  el.textContent = window.I18n?.t?.(message) || message;
  el.className = `toast show${error ? ' error' : ''}`;
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => { el.className = 'toast'; }, 3200);
}

async function api(url, options = {}) {
  const response = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  const payload = await response.json();
  if (!response.ok || payload.error) {
    const message = payload.error || `请求失败 (${response.status})`;
    throw new Error(window.I18n?.t?.(message) || message);
  }
  return payload;
}

function setSource(source) {
  state.source = source;
  $('#dataSourceSelect').value = source;
  const local = source.startsWith('local');
  $('#groupControl').classList.toggle('hidden', local);
  $('#assetControl').classList.toggle('hidden', local);
  $('#localControl').classList.toggle('hidden', !local);
  $('#customSymbolInput').classList.toggle('hidden', source !== 'tencent');
  $('#customAssetNameInput').classList.toggle('hidden', local);
  $('#assetSelectCombo').classList.toggle('custom-enabled', source === 'tencent');
  if (local) renderDatasetOptions(); else renderGroupOptions();
}

function updateClock() {
  const now = new Date();
  $('#clock').textContent = now.toLocaleString(window.I18n?.localeForIntl?.() || 'zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function renderDatasetOptions() {
  const select = $('#datasetSelect');
  const daily = state.datasets.filter((item) => item.interval === '1d' || item.path.includes('_1d_'));
  const cryptoMode = state.source === 'local_crypto';
  const items = daily.filter((item) => cryptoMode ? /btc|usdt|crypto/i.test(`${item.symbol} ${item.path}`) : /^(sh|sz|bj)\d{6}$/i.test(item.symbol || ''));
  $('#datasetLabel').textContent = cryptoMode ? '本地虚拟货币日线' : '本地股票日线';
  select.innerHTML = items.map((item) => `<option value="${escapeHtml(item.path)}">${escapeHtml(item.symbol)} · ${escapeHtml(item.name)} · ${escapeHtml(item.rows)} bars</option>`).join('');
}

function renderSourceOptions() {
  const sources = state.universe?.sources || [];
  $('#dataSourceSelect').innerHTML = sources.map((source) => `<option value="${source.id}">${escapeHtml(source.name)}</option>`).join('');
  setSource(state.source);
}

function currentAssetType() {
  return state.universe?.sources?.find((source) => source.id === state.source)?.asset_type || 'stocks';
}

function renderGroupOptions() {
  const type = currentAssetType();
  const groups = state.universe?.groups?.[type] || [];
  $('#groupLabel').textContent = type === 'crypto' ? '币种分类' : '板块';
  $('#assetLabel').textContent = type === 'crypto' ? '虚拟货币' : '股票';
  $('#groupSelect').innerHTML = groups.map((group) => `<option value="${group.id}">${escapeHtml(group.name)}</option>`).join('');
  renderAssetOptions();
}

function renderAssetOptions() {
  const type = currentAssetType();
  const groups = state.universe?.groups?.[type] || [];
  const group = groups.find((item) => item.id === $('#groupSelect').value) || groups[0];
  $('#assetSelect').innerHTML = (group?.assets || []).map((asset) => `<option value="${asset.symbol}">${escapeHtml(asset.name)} · ${escapeHtml(asset.symbol)}</option>`).join('');
  const selected = (group?.assets || []).find((asset) => asset.symbol === $('#assetSelect').value) || group?.assets?.[0];
  $('#customAssetNameInput').value = selected?.name || '';
  if (state.source === 'tencent') {
    $('#customSymbolInput').value = '';
    $('#assetSelect').classList.remove('overridden');
  }
}

function dataStateLabel(status) {
  return ({ healthy: '可用', live: '实时', cached: '缓存快照', delayed: '延迟日线', local: '本地数据', unavailable: '不可用', unchecked: '未检测' }[status] || status || '未知');
}

function dataStateBadge(status, label = '') {
  return `<span class="data-state-badge ${escapeHtml(status || 'unchecked')}">${escapeHtml(label || dataStateLabel(status))}</span>`;
}

function renderStrategyVersions() {
  const host = $('#strategyVersionList');
  if (!host) return;
  $('#strategyVersionMeta').textContent = `${state.strategyVersions.length} 个版本 · 保存在当前浏览器本地`;
  host.innerHTML = state.strategyVersions.map((version) => `<article class="strategy-version-card" data-version-id="${escapeHtml(version.id)}">
    <strong>${escapeHtml(version.name)}</strong><span>${escapeHtml(version.label || version.symbol)} · ${escapeHtml(version.strategy_name || version.strategy_id)}</span>
    <small>${escapeHtml(String(version.created_at || '').replace('T', ' ').slice(0, 16))} · ${Object.keys(version.parameters || {}).length} 个参数</small>
    <div class="strategy-version-actions"><button data-version-load="${escapeHtml(version.id)}">加载</button><button data-version-copy="${escapeHtml(version.id)}">复制</button><button data-version-export="${escapeHtml(version.id)}">导出</button><button data-version-delete="${escapeHtml(version.id)}">删除</button></div>
  </article>`).join('') || '<div class="strategy-library-empty">暂无保存版本。生成策略、调整参数后可在参数实验室保存。</div>';
  host.querySelectorAll('[data-version-load]').forEach((button) => button.onclick = () => loadStrategyVersion(button.dataset.versionLoad));
  host.querySelectorAll('[data-version-copy]').forEach((button) => button.onclick = () => copyStrategyVersion(button.dataset.versionCopy));
  host.querySelectorAll('[data-version-export]').forEach((button) => button.onclick = () => exportStrategyVersion(button.dataset.versionExport));
  host.querySelectorAll('[data-version-delete]').forEach((button) => button.onclick = () => deleteStrategyVersion(button.dataset.versionDelete));
}

function renderFactoryStatus(result) {
  const latest = result.latest || {};
  $('#factoryStatus').classList.remove('hidden');
  $('#stockLabel').textContent = `${result.symbol || ''} · ${result.label || ''}`;
  const sourceNames = Object.fromEntries((state.universe?.sources || []).map((source) => [source.id, source.name]));
  const dataStatus = result.data_status || {};
  $('#stockSource').innerHTML = `${escapeHtml(sourceNames[result.source] || '行情数据')} · ${escapeHtml(result.bars)} 根已收盘日线 · ${dataStateBadge(dataStatus.status, dataStatus.mode)}`;
  const relative = result.relative_strength_context || {};
  $('#stockMetrics').innerHTML = [
    ['最新收盘', fmtNum(latest.close)],
    ['当日变化', fmtPct(latest.change)],
    ['波动分档', result.profile?.volatility_tier || '—'],
    ['样本外起点', result.split?.test_start || '—'],
    ['板块比较', relative.available ? `${relative.group_name} · ${relative.peer_count}只` : '未启用'],
    ['数据交易日', dataStatus.trade_date || latest.date || '—'],
  ].map(([label, value]) => `<div><span>${label}</span><b class="${label === '当日变化' ? metricClass(latest.change) : ''}">${escapeHtml(value)}</b></div>`).join('');
}

function familyColor(family) {
  return ({ '趋势': '#4a8cff', '突破': '#f5bf4f', '均值回归': '#42c7c1', '超跌': '#9a7cff', '动量': '#ff8b45', '趋势风控': '#3fb8ff', '突破风控': '#f5bf4f', '双重均值回归': '#42c7c1', '量价动量': '#ff8b45', '波动突破': '#e8cf62', '多周期': '#6fa7ff', '横截面选股': '#d890ff', '状态切换': '#43d19b', '信号组合': '#ff777f' }[family] || '#4a8cff');
}

function renderCandidates(result) {
  const candidates = result.candidates || [];
  const skipped = result.skipped_strategies || [];
  $('#candidateMeta').textContent = `${candidates.length} 个候选 · ${result.split.train_bars}/${result.split.test_bars} 根训练/测试${skipped.length ? ` · ${skipped.map((item) => item.name).join('、')}待数据` : ''}`;
  $('#candidateGrid').innerHTML = candidates.map((item) => {
    const test = item.test || {};
    const color = familyColor(item.family);
    return `<button class="candidate-card ${state.selectedCandidate === item.id ? 'active' : ''}" data-candidate="${item.id}" style="--family-color:${color}">
      <div class="candidate-top"><span>${escapeHtml(item.family)}</span><b>研究优先级 ${item.rank}</b></div>
      <h3>${escapeHtml(item.name)}</h3>
      <div class="candidate-primary"><span>样本外收益</span><strong class="${metricClass(test.total_return)}">${fmtPct(test.total_return)}</strong></div>
      <div class="mini-metrics"><div><span>相对基准</span><b class="${metricClass(test.excess_return)}">${fmtPct(test.excess_return)}</b></div><div><span>最大回撤</span><b class="negative">${fmtPct(test.max_drawdown)}</b></div><div><span>夏普</span><b>${fmtNum(test.sharpe)}</b></div><div><span>交易次数</span><b>${test.trades ?? '—'}</b></div></div>
    </button>`;
  }).join('');
  $$('#candidateGrid [data-candidate]').forEach((button) => button.addEventListener('click', () => {
    state.selectedCandidate = button.dataset.candidate;
    renderCandidates(result);
    renderCandidateDetail(candidates.find((item) => item.id === state.selectedCandidate));
  }));
  if (!state.selectedCandidate && candidates[0]) state.selectedCandidate = candidates[0].id;
  renderCandidateDetail(candidates.find((item) => item.id === state.selectedCandidate));
}

function renderCandidateDetail(item) {
  if (!item) return;
  $('#detailFamily').textContent = item.family;
  $('#detailFamily').style.color = familyColor(item.family);
  $('#detailName').textContent = item.name;
  $('#detailRank').textContent = `研究优先级 ${item.rank}`;
  $('#detailDescription').textContent = item.description;
  $('#detailRisk').textContent = item.risk;
  $('#detailRules').innerHTML = [
    ['入场', item.entry_rule],
    ['退出', item.exit_rule],
    ['仓位', item.position_rule],
  ].map(([label, value]) => `<div><b>${label}</b><span>${escapeHtml(value || '—')}</span></div>`).join('');
  $('#detailParameters').innerHTML = Object.entries(item.parameters || {}).map(([key, value]) => `<span>${escapeHtml(key)} <b>${escapeHtml(fmtNum(value, 2))}</b></span>`).join('');
  renderParameterEditor(item);
  renderStrategyComparison(item);
  const test = item.test || {};
  const full = item.full || {};
  const cells = [
    ['样本外收益', fmtPct(test.total_return), metricClass(test.total_return), `基准 ${fmtPct(test.benchmark_return)}`],
    ['超额收益', fmtPct(test.excess_return), metricClass(test.excess_return), '对比买入持有'],
    ['最大回撤', fmtPct(test.max_drawdown), 'negative', '样本外'],
    ['夏普', fmtNum(test.sharpe), '', `按日线 ${state.candidates?.periods_per_year || 252} 年化`],
    ['交易次数', fmtNum(test.trades, 0), '', `胜率 ${fmtPct(test.win_rate, 0)}`],
    ['全样本收益', fmtPct(full.total_return), metricClass(full.total_return), `暴露 ${fmtPct(full.exposure, 0)}`],
  ];
  $('#detailMetrics').innerHTML = cells.map(([label, value, className, note]) => `<div class="metric-cell"><span>${label}</span><strong class="${className}">${value}</strong><small>${note}</small></div>`).join('');
  $('#chartPeriod').textContent = `${test.start} → ${test.end} · 虚线为测试起点`;
  $('#tradeCount').textContent = `${item.trades?.length || 0} 笔（最近）`;
  $('#tradeRows').innerHTML = (item.trades || []).slice(-8).reverse().map((trade) => `<tr><td class="mono">${escapeHtml(String(trade.entry_date || '').slice(0, 10))}</td><td class="mono">${escapeHtml(String(trade.exit_date || '').slice(0, 10))}</td><td>${fmtNum(trade.holding_days, 0)} 天</td><td class="${metricClass(trade.net_return)} mono">${fmtPct(trade.net_return)}</td></tr>`).join('') || '<tr><td colspan="4">暂无已完成交易</td></tr>';
  const okxButton = $('#okxDraftButton');
  const okxEligible = state.candidates?.source === 'gate';
  okxButton.disabled = !okxEligible;
  okxButton.title = okxEligible ? '将当前策略带到 OKX Demo 交易页' : '仅虚拟货币候选可部署到 OKX Demo';
  drawStrategyChart(item, state.chart);
}

function renderStrategyComparison(item) {
  const host = $('#strategyComparison');
  if (!host) return;
  const original = state.candidateBaselines.get(item.id);
  if (!original || !item.customized) { host.innerHTML = ''; return; }
  const fields = [['样本外收益', 'total_return'], ['相对基准', 'excess_return'], ['最大回撤', 'max_drawdown'], ['夏普', 'sharpe']];
  host.innerHTML = `<div class="section-heading"><div><h3>原始候选 vs 用户版本</h3><span>当前参数版本与生成时参数的研究结果对比</span></div></div><div class="comparison-grid"><div class="comparison-label"><b>指标</b><span>原始候选</span><span>用户版本</span><span>变化</span></div>${fields.map(([label, key]) => { const a = Number(original.test?.[key] ?? 0); const b = Number(item.test?.[key] ?? 0); const diff = b - a; return `<div class="comparison-row"><b>${label}</b><span>${key === 'sharpe' ? fmtNum(a) : fmtPct(a)}</span><span>${key === 'sharpe' ? fmtNum(b) : fmtPct(b)}</span><strong class="${metricClass(diff)}">${key === 'sharpe' ? fmtNum(diff) : fmtPct(diff)}</strong></div>`; }).join('')}</div>`;
}

function renderParameterEditor(item) {
  const schema = item.parameter_schema || Object.keys(item.parameters || {}).map((key) => ({ key, label: key, min: -1000000, max: 1000000, step: 0.01 }));
  $('#parameterEditor').innerHTML = schema.map((field) => `<div class="parameter-field"><label for="parameter-${escapeHtml(field.key)}"><span>${escapeHtml(field.label || field.key)}</span><code>${escapeHtml(field.key)}</code></label><input id="parameter-${escapeHtml(field.key)}" data-strategy-parameter="${escapeHtml(field.key)}" type="number" value="${escapeHtml(item.parameters?.[field.key])}" min="${escapeHtml(field.min)}" max="${escapeHtml(field.max)}" step="${escapeHtml(field.step)}"><small>${escapeHtml(field.min)} – ${escapeHtml(field.max)}</small></div>`).join('');
  $('#parameterState').textContent = item.customized ? '已使用自定义参数重算' : '候选原始参数';
  $('#parameterWarning').textContent = item.customized ? '当前结果已按自定义参数重新计算；保存版本不会自动下单。' : '参数仅用于本次研究重算；保存版本不会自动下单。';
  $$('[data-strategy-parameter]').forEach((input) => input.addEventListener('input', () => { $('#parameterState').textContent = '参数已修改，等待重新计算'; }));
}

function currentCandidate() {
  return state.candidates?.candidates?.find((item) => item.id === state.selectedCandidate);
}

function readStrategyParameters() {
  const values = {};
  for (const input of $$('[data-strategy-parameter]')) {
    if (!input.reportValidity()) throw new Error(`${input.dataset.strategyParameter} 参数超出允许范围`);
    values[input.dataset.strategyParameter] = Number(input.value);
  }
  return values;
}

async function recalculateStrategy(parameters = null, notify = true) {
  const candidate = currentCandidate();
  if (!candidate || !state.candidates?.request) { toast('请先生成并选择候选策略', true); return false; }
  const button = $('#recalculateStrategyButton');
  button.disabled = true; button.textContent = '正在重新计算…';
  try {
    const result = await api('/api/strategy-recalculate', { method: 'POST', body: JSON.stringify({ ...state.candidates.request, strategy_id: candidate.id, parameters: parameters || readStrategyParameters() }) });
    const merged = { ...candidate, ...result, rank: candidate.rank, customized: true };
    const index = state.candidates.candidates.findIndex((item) => item.id === candidate.id);
    state.candidates.candidates[index] = merged;
    state.candidates.data_status = result.data_status || state.candidates.data_status;
    renderFactoryStatus(state.candidates);
    renderCandidates(state.candidates);
    if (notify) toast('已按自定义参数重新计算策略');
    return true;
  } catch (error) { toast(error.message, true); return false; }
  finally { button.disabled = false; button.textContent = '重新计算'; }
}

function resetStrategyParameters() {
  const baseline = state.candidateBaselines.get(state.selectedCandidate);
  if (!baseline || !state.candidates) return;
  const index = state.candidates.candidates.findIndex((item) => item.id === state.selectedCandidate);
  state.candidates.candidates[index] = cloneJson(baseline);
  renderCandidates(state.candidates);
  toast('已恢复候选原始参数和结果');
}

function versionIdentifier() {
  return window.crypto?.randomUUID?.() || `strategy-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function strategyVersionPayload(candidate, name) {
  return {
    schema_version: 1,
    id: versionIdentifier(),
    name,
    created_at: new Date().toISOString(),
    symbol: state.candidates.symbol,
    label: state.candidates.label,
    source: state.candidates.source,
    group: state.candidates.group,
    strategy_id: candidate.id,
    strategy_name: candidate.name,
    strategy_family: candidate.family,
    parameters: cloneJson(candidate.parameters),
    parameter_schema: cloneJson(candidate.parameter_schema || []),
    metrics: { test: cloneJson(candidate.test || {}), full: cloneJson(candidate.full || {}) },
    request: cloneJson(state.candidates.request),
  };
}

function saveStrategyVersion() {
  const candidate = currentCandidate();
  if (!candidate) { toast('请先选择候选策略', true); return; }
  const input = $('#strategyVersionName');
  const name = input.value.trim() || `${state.candidates.label} · ${candidate.name}`;
  state.strategyVersions.unshift(strategyVersionPayload(candidate, name));
  state.strategyVersions = state.strategyVersions.slice(0, 50);
  persistStrategyVersions(); renderStrategyVersions(); input.value = '';
  toast('策略版本已保存在当前浏览器');
}

function downloadJson(payload, filename) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' });
  const url = URL.createObjectURL(blob), anchor = document.createElement('a');
  anchor.href = url; anchor.download = filename.replace(/[^\w\u4e00-\u9fff.-]+/g, '_'); anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function exportCurrentStrategy() {
  const candidate = currentCandidate();
  if (!candidate) { toast('请先选择候选策略', true); return; }
  const version = strategyVersionPayload(candidate, `${state.candidates.label} · ${candidate.name}`);
  downloadJson(version, `quantpilot-${state.candidates.symbol}-${candidate.id}.json`);
}

function exportStrategyVersion(id) {
  const version = state.strategyVersions.find((item) => item.id === id);
  if (version) downloadJson(version, `quantpilot-${version.symbol}-${version.strategy_id}.json`);
}

function copyStrategyVersion(id) {
  const version = state.strategyVersions.find((item) => item.id === id);
  if (!version) return;
  state.strategyVersions.unshift({ ...cloneJson(version), id: versionIdentifier(), name: `${version.name} 副本`, created_at: new Date().toISOString() });
  persistStrategyVersions(); renderStrategyVersions();
}

function deleteStrategyVersion(id) {
  const version = state.strategyVersions.find((item) => item.id === id);
  if (!version || !window.confirm(`确定删除策略版本“${version.name}”吗？`)) return;
  state.strategyVersions = state.strategyVersions.filter((item) => item.id !== id);
  persistStrategyVersions(); renderStrategyVersions();
}

async function loadStrategyVersion(id) {
  const version = state.strategyVersions.find((item) => item.id === id);
  if (!version) return;
  toast('正在加载策略版本并重新获取研究数据…');
  try {
    const result = await api('/api/strategy-candidates', { method: 'POST', body: JSON.stringify(version.request) });
    state.candidates = result; state.selectedCandidate = version.strategy_id;
    state.candidateBaselines = new Map(result.candidates.map((item) => [item.id, cloneJson(item)]));
    if (!result.candidates.some((item) => item.id === version.strategy_id)) throw new Error('当前数据不支持这个策略版本');
    renderFactoryStatus(result); $('#factoryEmpty').classList.add('hidden'); $('#factoryResults').classList.remove('hidden'); renderCandidates(result);
    const ok = await recalculateStrategy(version.parameters, false);
    if (ok) { $('#strategyVersionName').value = version.name; toast('策略版本已加载并重新计算'); }
  } catch (error) { toast(error.message, true); }
}

async function importStrategyFile(file) {
  if (!file || file.size > 1024 * 1024) { toast('请选择小于 1MB 的策略 JSON 文件', true); return; }
  try {
    const parsed = JSON.parse(await file.text());
    const items = Array.isArray(parsed) ? parsed : [parsed];
    const valid = items.filter((item) => item && item.strategy_id && item.parameters && item.request).map((item) => ({ ...item, id: versionIdentifier(), imported_at: new Date().toISOString() }));
    if (!valid.length) throw new Error('文件中没有有效的 QuantPilot 策略版本');
    state.strategyVersions = [...valid, ...state.strategyVersions].slice(0, 50);
    persistStrategyVersions(); renderStrategyVersions(); toast(`已导入 ${valid.length} 个策略版本`);
  } catch (error) { toast(error.message, true); }
  finally { $('#strategyImportInput').value = ''; }
}

function drawStrategyChart(item, mode = 'equity') {
  const host = $('#strategyChart');
  const series = item.series || [];
  if (!series.length) { host.innerHTML = '<div class="page-loading">暂无可绘制数据</div>'; return; }
  const width = Math.max(600, host.clientWidth || 900), height = 300;
  const pad = { left: 42, right: 14, top: 14, bottom: 24 };
  const valuesA = series.map((point) => Number(mode === 'price' ? point.close : point.equity)).filter(Number.isFinite);
  const valuesB = series.map((point) => Number(mode === 'price' ? point.indicator_a : point.benchmark)).filter(Number.isFinite);
  const all = valuesA.concat(valuesB);
  let min = Math.min(...all), max = Math.max(...all);
  if (min === max) { min -= 1; max += 1; }
  const x = (index) => pad.left + index * (width - pad.left - pad.right) / Math.max(1, series.length - 1);
  const y = (value) => pad.top + (max - value) * (height - pad.top - pad.bottom) / (max - min);
  const path = (values) => values.map((value, index) => Number.isFinite(value) ? `${index ? 'L' : 'M'} ${x(index).toFixed(1)} ${y(value).toFixed(1)}` : '').join(' ');
  const splitIndex = series.findIndex((point) => point.is_test);
  const splitX = splitIndex > 0 ? x(splitIndex) : null;
  const grids = [0, .25, .5, .75, 1].map((ratio) => { const yy = pad.top + ratio * (height - pad.top - pad.bottom); const value = max - ratio * (max - min); return `<line class="chart-grid" x1="${pad.left}" x2="${width - pad.right}" y1="${yy}" y2="${yy}"/><text class="chart-label" x="4" y="${yy + 3}">${mode === 'price' ? fmtNum(value) : fmtNum(value, 2)}</text>`; }).join('');
  const labels = [0, Math.floor(series.length / 2), series.length - 1].map((index) => `<text class="chart-label" x="${x(index)}" y="${height - 5}" text-anchor="middle">${escapeHtml(String(series[index].date).slice(0, 10))}</text>`).join('');
  const area = mode === 'equity' ? `${path(valuesA)} L ${x(series.length - 1)} ${height - pad.bottom} L ${x(0)} ${height - pad.bottom} Z` : '';
  host.innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="策略曲线"><defs><linearGradient id="areaFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#4a8cff"/><stop offset="1" stop-color="#4a8cff" stop-opacity="0"/></linearGradient></defs>${grids}${splitX ? `<rect class="test-zone" x="${splitX}" y="${pad.top}" width="${width - pad.right - splitX}" height="${height - pad.top - pad.bottom}"/><line class="split-line" x1="${splitX}" x2="${splitX}" y1="${pad.top}" y2="${height - pad.bottom}"/>` : ''}${area ? `<path class="chart-area" d="${area}"/>` : ''}<path class="chart-benchmark" d="${path(valuesB)}"/><path class="chart-strategy" d="${path(valuesA)}"/>${labels}</svg>`;
}

async function generateCandidates() {
  const button = $('#generateButton');
  button.disabled = true;
  button.innerHTML = '<span>…</span> 正在生成';
  try {
    const payload = { source: state.source, group: state.source.startsWith('local') ? null : $('#groupSelect').value, custom_label: state.source.startsWith('local') ? null : $('#customAssetNameInput').value.trim(), buy_cost: Number($('#buyCost').value) / 100, sell_cost: Number($('#sellCost').value) / 100 };
    if (state.source.startsWith('local')) payload.dataset = $('#datasetSelect').value;
    else payload.symbol = state.source === 'tencent' && $('#customSymbolInput').value.trim() ? $('#customSymbolInput').value.trim() : $('#assetSelect').value;
    const result = await api('/api/strategy-candidates', { method: 'POST', body: JSON.stringify(payload) });
    state.candidates = result;
    state.selectedCandidate = null;
    state.candidateBaselines = new Map(result.candidates.map((item) => [item.id, cloneJson(item)]));
    renderFactoryStatus(result);
    $('#factoryEmpty').classList.add('hidden');
    $('#factoryResults').classList.remove('hidden');
    renderCandidates(result);
    toast(`已为 ${result.symbol} 生成 ${result.candidates.length} 个候选策略`);
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.innerHTML = '<span>▶</span> 生成候选'; }
}

function stagePaperStrategy() {
  const candidate = state.candidates?.candidates?.find((item) => item.id === state.selectedCandidate);
  if (!candidate) { toast('请先选择一个候选策略', true); return; }
  state.paperDraft = {
    source: state.candidates.source,
    group: state.candidates.group,
    symbol: state.candidates.symbol,
    label: state.candidates.label,
    custom_label: state.candidates.label,
    dataset: state.candidates.source.startsWith('local') ? $('#datasetSelect').value : null,
    periods_per_year: state.candidates.periods_per_year,
    strategy_id: candidate.id,
    strategy_name: candidate.name,
    strategy_family: candidate.family,
    parameters: candidate.parameters,
    buy_cost: Number($('#buyCost').value) / 100,
    sell_cost: Number($('#sellCost').value) / 100,
  };
  switchView('paper');
  renderPaper();
}

function stageOkxDemoStrategy() {
  const candidate = state.candidates?.candidates?.find((item) => item.id === state.selectedCandidate);
  if (!candidate || state.candidates?.source !== 'gate') { toast('请先为虚拟货币生成并选择候选策略', true); return; }
  state.okxStrategyDraft = {
    inst_id: `${String(state.candidates.symbol).toUpperCase()}-USDT`,
    strategy_id: candidate.id,
    strategy_name: candidate.name,
    strategy_family: candidate.family,
    parameters: { ...candidate.parameters },
    quote_size: 100,
  };
  persistOkxStrategyDraft();
  state.okxStrategyPreview = null;
  state.brokerProvider = 'okx_demo';
  switchView('paper');
  renderPaper();
  toast('策略已带到 OKX Demo，可调整参数并预览信号');
}

function paperMoney(value) {
  return Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function renderPaper() {
  const host = $('#paperContent');
  if (!state.brokers) {
    host.innerHTML = '<div class="page-loading">正在读取交易平台配置…</div>';
    loadBrokerCatalog();
    return;
  }
  if (state.brokerProvider !== 'local') {
    renderExternalBroker();
    return;
  }
  if (state.paperDraft) {
    const draft = state.paperDraft;
    const hasExisting = Boolean(state.paper?.exists);
    host.innerHTML = `<div class="paper-setup"><section class="paper-strategy-band"><div><span class="family-tag">${escapeHtml(draft.strategy_family)}</span><h2>${escapeHtml(draft.strategy_name)}</h2><p>${escapeHtml(draft.label)} · ${escapeHtml(draft.symbol)}</p></div><div class="parameter-strip">${Object.entries(draft.parameters).map(([key, value]) => `<span>${escapeHtml(key)} <b>${escapeHtml(fmtNum(value))}</b></span>`).join('')}</div></section><section class="paper-account-form"><div><h3>模拟账户设置</h3><p>${hasExisting ? '创建后将替换当前模拟账户。' : '账户从留出样本起点开始按日回放。'}</p></div><div class="control-group"><label for="paperInitialCash">初始资金</label><input id="paperInitialCash" type="number" min="1000" step="1000" value="${state.paper?.initial_cash || 100000}"></div><div class="control-group"><label for="paperBuyFee">买入费率</label><div class="percent-input"><input id="paperBuyFee" type="number" min="0" max="5" step="0.01" value="${fmtNum((draft.buy_cost || 0) * 100, 2)}"><span>%</span></div></div><div class="control-group"><label for="paperSellFee">卖出费率</label><div class="percent-input"><input id="paperSellFee" type="number" min="0" max="5" step="0.01" value="${fmtNum((draft.sell_cost || 0) * 100, 2)}"><span>%</span></div></div><div class="control-group"><label for="paperSlippage">单边滑点</label><div class="percent-input"><input id="paperSlippage" type="number" min="0" max="5" step="0.01" value="0.05"><span>%</span></div></div><div class="control-group"><label for="paperLimitUp">涨停约束</label><div class="percent-input"><input id="paperLimitUp" type="number" min="1" max="30" step="0.1" value="9.5"><span>%</span></div></div><div class="control-group"><label for="paperLimitDown">跌停约束</label><div class="percent-input"><input id="paperLimitDown" type="number" min="1" max="30" step="0.1" value="9.5"><span>%</span></div></div><button class="primary-button" id="startPaperButton">▶ 创建并开始</button><button class="secondary-button" id="cancelPaperDraft">取消</button></section><div class="paper-rules"><span>A 股：100 股整手</span><span>A 股：T+1</span><span>涨跌停阈值可配置</span><span>加密资产：最小 0.000001</span><span>本地持久化</span></div></div>`;
    mountBrokerPlatformBar(host);
    $('#startPaperButton').addEventListener('click', startPaperAccount);
    $('#cancelPaperDraft').addEventListener('click', () => { state.paperDraft = null; renderPaper(); });
    return;
  }
  if (!state.paper?.exists) {
    host.innerHTML = `<div class="history-empty"><div class="empty-archive">◎</div><strong>尚未创建模拟账户</strong><span>在策略工坊选择候选策略后点击“模拟运行”</span><button class="secondary-button empty-action" id="goFactoryButton">进入策略工坊</button></div>`;
    mountBrokerPlatformBar(host);
    $('#goFactoryButton').addEventListener('click', () => switchView('factory'));
    return;
  }
  renderPaperAccount(state.paper);
}

async function startPaperAccount() {
  const button = $('#startPaperButton');
  button.disabled = true;
  try {
    const payload = {
      ...state.paperDraft,
      initial_cash: Number($('#paperInitialCash').value),
      buy_cost: Number($('#paperBuyFee').value) / 100,
      sell_cost: Number($('#paperSellFee').value) / 100,
      slippage: Number($('#paperSlippage').value) / 100,
      limit_up_pct: Number($('#paperLimitUp').value) / 100,
      limit_down_pct: Number($('#paperLimitDown').value) / 100,
    };
    state.paper = await api('/api/paper/start', { method: 'POST', body: JSON.stringify(payload) });
    state.paperDraft = null;
    renderPaper();
    toast('模拟账户已创建');
  } catch (error) { toast(error.message, true); button.disabled = false; }
}

function renderPaperAccount(account) {
  const host = $('#paperContent');
  const metrics = account.metrics || {};
  const position = account.position || {};
  const progress = account.progress || { current: 0, total: 1 };
  const progressPct = Math.min(100, progress.total ? progress.current / progress.total * 100 : 0);
  const orders = [...(account.orders || [])].reverse().slice(0, 30);
  const quantityDigits = account.market_type === 'crypto' ? 6 : 0;
  host.innerHTML = `<div class="paper-account"><div class="paper-account-head"><div><div class="paper-status-line"><span class="paper-status ${account.status}">${account.status === 'completed' ? '回放完成' : account.status === 'ready' ? '待运行' : '运行中'}</span><strong>${escapeHtml(account.label)}</strong><small>${escapeHtml(account.symbol)}</small></div><h2>${escapeHtml(account.strategy_name)}</h2><p>${escapeHtml(account.current_date)} · ${account.market_type === 'crypto' ? '虚拟货币账户' : 'A 股账户'} · 仅模拟环境</p></div><div class="paper-controls"><button class="secondary-button" data-paper-steps="1">单步</button><button class="secondary-button" data-paper-steps="20">快进 20 日</button><button class="primary-button" data-paper-steps="10000">运行到底</button><button class="secondary-button" id="restartPaperButton">重新开始回放</button><button class="secondary-button" id="downloadPaperOrders">导出 CSV</button><button class="icon-button danger-button" id="resetPaperButton" title="清空账户" aria-label="清空账户">×</button></div></div><div class="paper-progress"><span style="width:${progressPct}%"></span></div><div class="paper-progress-label"><span>留出样本回放</span><b>${progress.current} / ${progress.total} 日</b></div><div class="metrics-grid paper-metrics"><div class="metric-cell"><span>账户权益</span><strong>${paperMoney(metrics.equity)}</strong><small>初始 ${paperMoney(account.initial_cash)}</small></div><div class="metric-cell"><span>累计盈亏</span><strong class="${metricClass(metrics.total_pnl)}">${metrics.total_pnl >= 0 ? '+' : ''}${paperMoney(metrics.total_pnl)}</strong><small>${fmtPct(metrics.total_return)}</small></div><div class="metric-cell"><span>已实现盈亏</span><strong class="${metricClass(metrics.realized_pnl)}">${metrics.realized_pnl >= 0 ? '+' : ''}${paperMoney(metrics.realized_pnl)}</strong><small>已卖出部分</small></div><div class="metric-cell"><span>可用现金</span><strong>${paperMoney(metrics.cash)}</strong><small>人民币 / USDT</small></div><div class="metric-cell"><span>持仓市值</span><strong>${paperMoney(metrics.market_value)}</strong><small>${fmtNum(position.quantity, quantityDigits)} 份</small></div><div class="metric-cell"><span>浮动盈亏</span><strong class="${metricClass(metrics.unrealized_pnl)}">${metrics.unrealized_pnl >= 0 ? '+' : ''}${paperMoney(metrics.unrealized_pnl)}</strong><small>按当前回放收盘价</small></div><div class="metric-cell"><span>手续费</span><strong>${paperMoney(metrics.fees_paid)}</strong><small>${metrics.filled_orders} 笔成交</small></div><div class="metric-cell"><span>最大回撤</span><strong class="negative">${fmtPct(metrics.max_drawdown)}</strong><small>${metrics.pending_orders || 0} 笔待成交</small></div></div>${paperOrderPanel(account, position, quantityDigits)}<div class="paper-main-grid"><section class="chart-panel"><div class="chart-header"><div><h3>模拟账户净值</h3><span>逐日权益</span></div></div><div class="chart-wrap paper-chart" id="paperEquityChart"></div></section><section class="content-panel paper-position"><div class="section-heading"><div><h3>当前持仓</h3><span>${position.quantity > 0 ? '持仓中' : '空仓'}</span></div></div><div class="position-symbol"><strong>${escapeHtml(account.label)}</strong><span>${escapeHtml(account.symbol)}</span></div><dl><div><dt>数量</dt><dd>${fmtNum(position.quantity, quantityDigits)}</dd></div><div><dt>平均成本</dt><dd>${paperMoney(position.average_cost)}</dd></div><div><dt>最新价格</dt><dd>${paperMoney(position.last_price)}</dd></div><div><dt>市值</dt><dd>${paperMoney(position.market_value)}</dd></div></dl></section></div><section class="table-page paper-orders"><div class="table-page-header"><h2>模拟订单</h2><span>${account.orders.length} 条记录，含信号来源和拒单原因</span></div><div class="table-scroll paper-order-scroll"><table><thead><tr><th>日期</th><th>方向</th><th>状态</th><th>价格</th><th>数量</th><th>金额</th><th>费用</th><th>信号来源</th><th>原因</th><th>操作</th></tr></thead><tbody>${orders.map((order) => `<tr><td class="mono">${escapeHtml(order.date)}</td><td class="${order.side === 'buy' ? 'positive' : 'negative'}">${order.side === 'buy' ? '买入' : '卖出'}</td><td><span class="order-status ${order.status}">${({filled:'已成交',partial:'部分成交',pending:'待成交',cancelled:'已撤单',rejected:'已拒单',blocked:'受限'})[order.status] || order.status}</span></td><td class="mono">${paperMoney(order.price)}</td><td class="mono">${fmtNum(order.quantity, quantityDigits)} / ${fmtNum(order.requested_quantity, quantityDigits)}</td><td class="mono">${paperMoney(order.notional)}</td><td class="mono">${paperMoney(order.fee)}</td><td>${escapeHtml(order.signal_source || 'strategy')}</td><td>${escapeHtml(order.rejection_reason || order.reason || '')}</td><td>${order.status === 'pending' ? `<button class="secondary-button" data-paper-cancel="${order.id}">撤单</button>` : '—'}</td></tr>`).join('') || '<tr><td colspan="10">推进回放后将显示模拟订单</td></tr>'}</tbody></table></div></section></div>`;
  mountBrokerPlatformBar(host);
  $$('[data-paper-steps]').forEach((button) => button.addEventListener('click', () => advancePaper(Number(button.dataset.paperSteps))));
  $('#resetPaperButton').addEventListener('click', resetPaper);
  $('#restartPaperButton').addEventListener('click', restartPaper);
  $('#downloadPaperOrders').addEventListener('click', () => { window.location.href = '/api/paper/orders.csv'; });
  $('#submitPaperOrder').addEventListener('click', submitPaperOrder);
  $$('[data-paper-cancel]').forEach((button) => button.addEventListener('click', () => cancelPaperOrder(Number(button.dataset.paperCancel))));
  drawPaperChart(account.equity_history || []);
}

function paperOrderPanel(account, position, quantityDigits) {
  return `<section class="paper-order-entry content-panel"><div class="section-heading"><div><h3>手动模拟订单</h3><span>当前回放日期 · A 股遵守 T+1/100股整手，虚拟货币支持小数仓位</span></div><span class="paper-demo-badge">模拟环境 · 不会实盘</span></div><div class="paper-order-form"><label><span>方向</span><select id="paperOrderSide"><option value="buy">买入</option><option value="sell">卖出</option></select></label><label><span>订单类型</span><select id="paperOrderType"><option value="market">市价</option><option value="limit">限价（待成交可撤）</option></select></label><label><span>数量</span><input id="paperOrderQuantity" type="number" min="0.000001" step="any" value="${position.quantity > 0 ? position.quantity : account.market_type === 'crypto' ? 0.01 : 100}"></label><label><span>价格（限价单）</span><input id="paperOrderPrice" type="number" min="0" step="any" value="${escapeHtml(position.last_price || '')}"></label><button class="primary-button" id="submitPaperOrder">提交模拟订单</button></div></section>`;
}

async function submitPaperOrder() {
  const button = $('#submitPaperOrder'); button.disabled = true;
  try {
    state.paper = await api('/api/paper/order', { method: 'POST', body: JSON.stringify({ side: $('#paperOrderSide').value, order_type: $('#paperOrderType').value, quantity: Number($('#paperOrderQuantity').value), price: Number($('#paperOrderPrice').value) }) });
    renderPaper(); toast('模拟订单已处理');
  } catch (error) { toast(error.message, true); button.disabled = false; }
}

async function cancelPaperOrder(orderId) {
  if (!window.confirm('确定撤销这笔待成交模拟订单吗？')) return;
  try { state.paper = await api('/api/paper/cancel', { method: 'POST', body: JSON.stringify({ order_id: orderId }) }); renderPaper(); toast('模拟订单已撤销'); } catch (error) { toast(error.message, true); }
}

async function restartPaper() {
  if (!window.confirm('确定从留出样本起点重新开始回放吗？当前订单和盈亏记录将清空。')) return;
  try { state.paper = await api('/api/paper/restart', { method: 'POST', body: '{}' }); renderPaper(); toast('已重新开始模拟回放'); } catch (error) { toast(error.message, true); }
}

async function loadBrokerCatalog() {
  try {
    state.brokers = await api('/api/brokers');
    renderPaper();
  } catch (error) {
    $('#paperContent').innerHTML = `<div class="terminal-error">${escapeHtml(error.message)}</div>`;
  }
}

function brokerPlatformBar() {
  const items = state.brokers?.items || [];
  return `<section class="broker-bar"><div><strong>交易账户</strong><span>miniQMT 只读；OKX Demo 支持需确认的模拟订单，绝不发送实盘</span></div><div class="broker-tabs">${items.map((item) => `<button class="${state.brokerProvider === item.id ? 'active' : ''}" data-broker-provider="${item.id}"><b>${escapeHtml(item.name)}</b><small>${escapeHtml(item.market)}</small><i class="${item.configured ? 'configured' : ''}">${item.stored_locally ? '本机已保存' : item.configured ? '本次已配置' : '待配置'}</i></button>`).join('')}</div></section>`;
}

function mountBrokerPlatformBar(host) {
  host.insertAdjacentHTML('afterbegin', brokerPlatformBar());
  bindBrokerPlatformBar();
}

function bindBrokerPlatformBar() {
  $$('[data-broker-provider]').forEach((button) => button.addEventListener('click', () => {
    state.brokerProvider = button.dataset.brokerProvider;
    state.brokerSnapshot = null;
    renderPaper();
  }));
}

function renderExternalBroker() {
  const host = $('#paperContent');
  const provider = (state.brokers?.items || []).find((item) => item.id === state.brokerProvider);
  if (!provider) { state.brokerProvider = 'local'; renderPaper(); return; }
  const snapshot = state.brokerSnapshot;
  const storageText = provider.stored_locally
    ? '配置已使用 Windows 当前用户加密保存在本机，下次打开可直接使用'
    : provider.configured
      ? '配置仅在本次面板运行期间保留，关闭后自动清除'
      : '直接填写所需信息，并自行选择是否加密保存到本机';
  const tradingWorkspace = provider.id === 'okx_demo' && provider.configured ? okxDemoWorkspace() : '';
  const accountSnapshot = snapshot ? brokerSnapshotHtml(snapshot) : provider.configured ? '<div class="terminal-empty">点击“同步账户”读取资金、持仓、委托和成交。</div>' : '';
  host.innerHTML = `${brokerPlatformBar()}<section class="broker-account terminal-panel"><div class="paper-account-head"><div><div class="paper-status-line"><span class="paper-status ${snapshot?.connected ? 'running' : 'ready'}">${snapshot?.connected ? '已连接' : provider.configured ? '已配置' : '待配置'}</span><strong>${escapeHtml(provider.name)}</strong><small>${escapeHtml(provider.mode)}</small></div><h2>${escapeHtml(provider.market)} 模拟账户</h2><p>${snapshot ? `同步于 ${escapeHtml(snapshot.synced_at)}；${storageText}` : storageText}</p></div><div class="paper-controls">${provider.configured ? '<button class="secondary-button" id="clearBrokerButton">清空配置</button><button class="primary-button" id="syncBrokerButton">↻ 同步账户</button>' : ''}</div></div>${provider.configured ? '' : brokerConfigForm(provider)}${tradingWorkspace}${accountSnapshot}</section>`;
  bindBrokerPlatformBar();
  const button = $('#syncBrokerButton');
  if (button) button.addEventListener('click', syncExternalBroker);
  const saveButton = $('#saveBrokerConfig');
  if (saveButton) saveButton.addEventListener('click', saveBrokerConfig);
  const clearButton = $('#clearBrokerButton');
  if (clearButton) clearButton.addEventListener('click', clearBrokerConfig);
  bindOkxDemoControls();
}

function okxDemoWorkspace() {
  const draft = state.okxStrategyDraft;
  const preview = state.okxStrategyPreview;
  const parameterFields = draft ? Object.entries(draft.parameters || {}).map(([key, value]) => `<label><span>${escapeHtml(key)}</span><input type="number" step="any" data-okx-param="${escapeHtml(key)}" value="${escapeHtml(value)}"></label>`).join('') : '';
  const actionLabel = preview?.action === 'buy' ? '买入信号' : preview?.action === 'sell' ? '卖出信号' : '维持当前目标';
  const previewHtml = preview ? `<div class="okx-signal ${preview.action}"><div><span>最新已完成日线</span><b>${escapeHtml(String(preview.bar_time).slice(0, 16).replace('T', ' '))}</b></div><div><span>收盘价</span><b>${paperMoney(preview.close)}</b></div><div><span>前值 → 目标仓位</span><b>${fmtPct(preview.previous_target, 0)} → ${fmtPct(preview.target_fraction, 0)}</b></div><strong>${actionLabel}</strong></div>${preview.action === 'hold' ? '' : '<button class="secondary-button okx-apply-signal" id="applyOkxSignal">把信号填入左侧订单</button>'}` : '';
  return `<section class="okx-trading-workspace"><div class="okx-demo-warning"><strong>OKX Demo · 模拟环境</strong><span>所有订单强制发送模拟交易标记，不会进入实盘账户。</span></div><div class="section-heading"><div><h2>OKX Demo 模拟交易</h2><span>① 选择策略　② 调整参数并计算信号　③ 检查订单后确认提交</span></div><button class="secondary-button" id="goCryptoStrategy">选择/更换策略</button></div><div class="okx-workspace-grid"><article class="content-panel"><h3>手动模拟订单</h3><div class="okx-order-form"><label><span>现货交易对</span><input id="okxOrderInstrument" value="${escapeHtml(draft?.inst_id || 'BTC-USDT')}" placeholder="BTC-USDT"></label><label><span>方向</span><select id="okxOrderSide"><option value="buy">买入（数量按 USDT）</option><option value="sell">卖出（数量按币）</option></select></label><label><span>数量</span><input id="okxOrderSize" type="number" min="0.000001" step="any" value="${escapeHtml(draft?.quote_size || 100)}"></label><button class="primary-button" id="submitOkxDemoOrder">检查并确认模拟下单</button></div><p>买入数量表示花费的 USDT；卖出数量表示卖出的币。只提交市价现货模拟单，点击后仍会二次确认。</p></article><article class="content-panel okx-strategy-editor"><h3>策略与参数</h3>${draft ? `<div class="okx-strategy-title"><div><b>${escapeHtml(draft.strategy_name)}</b><span>${escapeHtml(draft.strategy_family)} · ${escapeHtml(draft.inst_id)} · 参数自动保存在当前浏览器</span></div><button class="secondary-button" id="clearOkxDraft">移除策略</button></div><div class="okx-parameter-grid">${parameterFields}</div><div class="okx-strategy-actions"><label><span>单次买入预算 USDT</span><input id="okxQuoteSize" type="number" min="5" max="100000" value="${escapeHtml(draft.quote_size || 100)}"></label><button class="primary-button" id="previewOkxStrategy">保存参数并计算信号</button></div>${previewHtml}<p>参数修改只影响下一次信号计算；信号只用于辅助填写订单，不会自动下单。</p>` : '<div class="terminal-empty">尚未选择策略。点击右上角“选择/更换策略”，选择 Gate.io 虚拟货币、生成候选，再在策略详情中点击“部署到 OKX Demo”。</div>'}</article></div></section>`;
}

function bindOkxDemoControls() {
  const go = $('#goCryptoStrategy');
  if (go) go.addEventListener('click', () => { switchView('factory'); setSource('gate'); });
  const clear = $('#clearOkxDraft');
  if (clear) clear.addEventListener('click', () => { state.okxStrategyDraft = null; state.okxStrategyPreview = null; persistOkxStrategyDraft(); renderExternalBroker(); });
  const preview = $('#previewOkxStrategy');
  if (preview) preview.addEventListener('click', previewOkxStrategy);
  const submit = $('#submitOkxDemoOrder');
  if (submit) submit.addEventListener('click', submitOkxDemoOrder);
  const apply = $('#applyOkxSignal');
  if (apply) apply.addEventListener('click', applyOkxSignalToOrder);
  $$('[data-okx-param], #okxQuoteSize').forEach((input) => input.addEventListener('change', saveOkxDraftInputs));
}

function saveOkxDraftInputs() {
  const draft = state.okxStrategyDraft;
  if (!draft) return;
  $$('[data-okx-param]').forEach((input) => {
    const value = Number(input.value);
    if (Number.isFinite(value)) draft.parameters[input.dataset.okxParam] = value;
  });
  const quoteSize = Number($('#okxQuoteSize')?.value);
  if (Number.isFinite(quoteSize) && quoteSize > 0) draft.quote_size = quoteSize;
  state.okxStrategyPreview = null;
  persistOkxStrategyDraft();
  $('.okx-signal')?.remove();
  $('.okx-apply-signal')?.remove();
}

function applyOkxSignalToOrder() {
  const draft = state.okxStrategyDraft;
  const preview = state.okxStrategyPreview;
  if (!draft || !preview || preview.action === 'hold') return;
  $('#okxOrderInstrument').value = draft.inst_id;
  $('#okxOrderSide').value = preview.action;
  if (preview.action === 'buy') {
    $('#okxOrderSize').value = draft.quote_size;
    toast('已填入买入方向和预算，请检查后确认模拟下单');
  } else {
    $('#okxOrderSize').value = '';
    toast('已填入卖出方向，请输入要卖出的币数量后确认');
  }
  $('#okxOrderSize').focus();
}

async function previewOkxStrategy() {
  const draft = state.okxStrategyDraft;
  if (!draft) return;
  const parameters = {};
  $$('[data-okx-param]').forEach((input) => { parameters[input.dataset.okxParam] = Number(input.value); });
  draft.parameters = parameters;
  draft.quote_size = Number($('#okxQuoteSize').value);
  persistOkxStrategyDraft();
  const button = $('#previewOkxStrategy'); button.disabled = true; button.textContent = '正在计算…';
  try {
    state.okxStrategyPreview = await api('/api/brokers/okx-demo/strategy-preview', { method: 'POST', body: JSON.stringify({ inst_id: draft.inst_id, strategy_id: draft.strategy_id, parameters }) });
    renderExternalBroker();
    toast('策略信号计算完成，未提交订单');
  } catch (error) { toast(error.message, true); button.disabled = false; button.textContent = '计算最新信号'; }
}

async function submitOkxDemoOrder() {
  const instId = $('#okxOrderInstrument').value.trim().toUpperCase();
  const side = $('#okxOrderSide').value;
  const size = Number($('#okxOrderSize').value);
  if (!/^[A-Z0-9]{2,12}-USDT$/.test(instId)) { toast('请输入正确的 USDT 现货交易对，例如 BTC-USDT', true); return; }
  if (!Number.isFinite(size) || size <= 0 || size > 100000) { toast('请输入大于 0 且不超过 100000 的下单数量', true); return; }
  const description = side === 'buy' ? `使用 ${size} USDT 买入 ${instId}` : `卖出 ${size} ${instId.split('-')[0]}`;
  if (!window.confirm(`确认向 OKX Demo 提交模拟市价单？\n\n${description}\n\n不会发送到实盘。`)) return;
  const button = $('#submitOkxDemoOrder'); button.disabled = true; button.textContent = '提交中…';
  try {
    const result = await api('/api/brokers/okx-demo/order', { method: 'POST', body: JSON.stringify({ inst_id: instId, side, size, confirmation: 'OKX_DEMO_ONLY' }) });
    toast(`OKX Demo 模拟订单已提交：${result.order_id || '已受理'}`);
    state.brokerSnapshot = await api('/api/brokers/sync', { method: 'POST', body: JSON.stringify({ provider: 'okx_demo' }) });
    renderExternalBroker();
  } catch (error) { toast(error.message, true); button.disabled = false; button.textContent = '确认模拟下单'; }
}

function brokerConfigForm(provider) {
  return `<div class="broker-config"><div class="broker-config-fields">${(provider.fields || []).map((field) => `<label><span>${escapeHtml(field.label)}</span><input id="brokerField_${field.id}" type="${field.type === 'password' ? 'password' : 'text'}" autocomplete="off" spellcheck="false" placeholder="${escapeHtml(field.placeholder)}"></label>`).join('')}</div><div class="broker-config-actions"><div><label class="broker-persist"><input id="persistBrokerConfig" type="checkbox" checked><span><b>保存到本机</b><small>使用 Windows 当前用户加密，下次打开自动读取</small></span></label><p>取消勾选则只在本次面板运行期间使用，并删除该平台以前保存的本地配置。</p></div><button class="primary-button" id="saveBrokerConfig">保存并同步</button></div></div>`;
}

async function saveBrokerConfig() {
  const provider = (state.brokers?.items || []).find((item) => item.id === state.brokerProvider);
  const button = $('#saveBrokerConfig');
  const payload = { provider: state.brokerProvider, persist: $('#persistBrokerConfig').checked };
  for (const field of provider.fields || []) payload[field.id] = $(`#brokerField_${field.id}`).value;
  button.disabled = true;
  button.textContent = '正在连接…';
  try {
    await api('/api/brokers/configure', { method: 'POST', body: JSON.stringify(payload) });
    state.brokers = await api('/api/brokers');
    renderExternalBroker();
    state.brokerSnapshot = await api('/api/brokers/sync', { method: 'POST', body: JSON.stringify({ provider: state.brokerProvider }) });
    renderExternalBroker();
    toast(payload.persist ? '配置已加密保存到本机并完成同步' : '配置仅用于本次运行并完成同步');
  } catch (error) {
    toast(error.message, true);
    renderExternalBroker();
  }
}

async function clearBrokerConfig() {
  try {
    await api('/api/brokers/configure', { method: 'POST', body: JSON.stringify({ provider: state.brokerProvider, action: 'clear' }) });
    state.brokers = await api('/api/brokers');
    state.brokerSnapshot = null;
    renderExternalBroker();
    toast('内存和本机保存的配置已清除');
  } catch (error) { toast(error.message, true); }
}

async function syncExternalBroker() {
  const button = $('#syncBrokerButton');
  button.disabled = true;
  button.textContent = '正在同步…';
  try {
    state.brokerSnapshot = await api('/api/brokers/sync', { method: 'POST', body: JSON.stringify({ provider: state.brokerProvider }) });
    renderExternalBroker();
    toast('模拟账户同步完成');
  } catch (error) {
    toast(error.message, true);
    renderExternalBroker();
  }
}

function brokerSnapshotHtml(snapshot) {
  const summary = snapshot.summary || {};
  const positions = snapshot.positions || [];
  const orders = snapshot.orders || [];
  const fills = snapshot.fills || [];
  const metrics = snapshot.provider === 'okx_demo'
    ? [['账户权益 USD', summary.equity_usd], ['稳定币可用', summary.available_usd], ['浮动盈亏', summary.unrealized_pnl]]
    : [['账户权益', summary.equity], ['可用资金', summary.cash], ['持仓市值', summary.market_value]];
  return `<div class="metrics-grid paper-metrics broker-metrics">${metrics.map(([label, value]) => `<div class="metric-cell"><span>${label}</span><strong>${paperMoney(value)}</strong></div>`).join('')}<div class="metric-cell"><span>持仓 / 委托 / 成交</span><strong>${positions.length} / ${orders.length} / ${fills.length}</strong></div></div><div class="terminal-warning">${escapeHtml(snapshot.notice)}</div><div class="broker-data-grid">${brokerDataTable('持仓', positions)}${brokerDataTable('当前委托', orders)}${brokerDataTable('最近成交', fills)}</div>`;
}

function brokerDataTable(title, rows) {
  const visible = rows.slice(0, 20);
  const preferred = ['instId', 'stock_code', 'symbol', 'pos', 'volume', 'available', 'avgPx', 'price', 'side', 'order_status', 'state', 'fillPx', 'traded_volume', 'fillSz'];
  const keys = [...new Set(visible.flatMap((row) => preferred.filter((key) => row[key] !== undefined)))].slice(0, 6);
  return `<section class="table-page"><div class="table-page-header"><h2>${title}</h2><span>${rows.length} 条</span></div><div class="table-scroll"><table><thead><tr>${keys.map((key) => `<th>${escapeHtml(key)}</th>`).join('')}</tr></thead><tbody>${visible.map((row) => `<tr>${keys.map((key) => `<td class="mono">${escapeHtml(row[key] ?? '—')}</td>`).join('')}</tr>`).join('') || `<tr><td colspan="${Math.max(keys.length, 1)}">暂无数据</td></tr>`}</tbody></table></div></section>`;
}

function drawPaperChart(history) {
  const host = $('#paperEquityChart');
  if (!host || !history.length) return;
  const width = Math.max(520, host.clientWidth || 760), height = 300;
  const pad = { left: 48, right: 14, top: 14, bottom: 24 };
  const values = history.map((point) => Number(point.equity));
  let min = Math.min(...values), max = Math.max(...values);
  if (min === max) { min *= .99; max *= 1.01; }
  const x = (index) => pad.left + index * (width - pad.left - pad.right) / Math.max(1, values.length - 1);
  const y = (value) => pad.top + (max - value) * (height - pad.top - pad.bottom) / (max - min);
  const line = values.map((value, index) => `${index ? 'L' : 'M'} ${x(index).toFixed(1)} ${y(value).toFixed(1)}`).join(' ');
  const grid = [0, .5, 1].map((ratio) => { const yy = pad.top + ratio * (height - pad.top - pad.bottom); const value = max - ratio * (max - min); return `<line class="chart-grid" x1="${pad.left}" x2="${width - pad.right}" y1="${yy}" y2="${yy}"/><text class="chart-label" x="2" y="${yy + 3}">${fmtNum(value, 0)}</text>`; }).join('');
  const area = `${line} L ${x(values.length - 1)} ${height - pad.bottom} L ${x(0)} ${height - pad.bottom} Z`;
  host.innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none"><defs><linearGradient id="paperArea" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#2dc78d" stop-opacity=".45"/><stop offset="1" stop-color="#2dc78d" stop-opacity="0"/></linearGradient></defs>${grid}<path d="${area}" fill="url(#paperArea)"/><path d="${line}" fill="none" stroke="#2dc78d" stroke-width="2.2"/><text class="chart-label" x="${pad.left}" y="${height - 5}">${escapeHtml(history[0].date)}</text><text class="chart-label" x="${width - pad.right}" y="${height - 5}" text-anchor="end">${escapeHtml(history[history.length - 1].date)}</text></svg>`;
}

async function advancePaper(steps) {
  $$('[data-paper-steps]').forEach((button) => { button.disabled = true; });
  try {
    state.paper = await api('/api/paper/advance', { method: 'POST', body: JSON.stringify({ steps }) });
    renderPaper();
  } catch (error) { toast(error.message, true); renderPaper(); }
}

async function resetPaper() {
  if (!window.confirm('确定重置当前模拟账户和全部模拟订单吗？')) return;
  try {
    state.paper = await api('/api/paper/reset', { method: 'POST', body: '{}' });
    state.paperDraft = null;
    renderPaper();
    toast('模拟账户已重置');
  } catch (error) { toast(error.message, true); }
}

async function renderTheme() {
  try {
    const options = await api('/api/theme-options');
    const first = options.items[0];
    $('#themeContent').innerHTML = `<div class="theme-toolbar"><div class="theme-option-grid">${options.items.map((item, index) => `<button class="theme-option ${index === 0 ? 'active' : ''}" data-theme="${item.id}"><span>${escapeHtml(item.name)}</span><small>${escapeHtml(item.focus)}</small><b>${escapeHtml(item.risk)}</b></button>`).join('')}</div></div><div id="themeCandidates"></div>`;
    $$('.theme-option').forEach((button) => button.addEventListener('click', async () => {
      $$('.theme-option').forEach((item) => item.classList.toggle('active', item === button));
      await loadThemeCandidates(button.dataset.theme);
    }));
    await loadThemeCandidates(first.id);
  } catch (error) { $('#themeContent').innerHTML = `<div class="page-loading">${escapeHtml(error.message)}</div>`; }
}

async function renderIndustry(force = false) {
  const host = $('#industryContent');
  host.innerHTML = '<div class="page-loading">正在读取行业统计…</div>';
  try {
    let timeoutId;
    const result = await Promise.race([
      api(`/api/terminal/industry${force ? '?refresh=1' : ''}`),
      new Promise((_, reject) => { timeoutId = window.setTimeout(() => reject(new Error('行业数据请求超时，请稍后重试')), 8000); }),
    ]);
    window.clearTimeout(timeoutId);
    const industries = result.industries || [];
    host.innerHTML = `<section class="terminal-panel"><div class="section-heading"><div><h2>行业热度</h2><span>${escapeHtml(result.source || '')} · ${escapeHtml(result.as_of || '')} · ${escapeHtml(result.source_scope || '')}</span>${dataStateBadge(result.stale ? 'cached' : 'live', result.stale ? '缓存快照' : '项目观察池')}</div><button class="secondary-button" id="refreshIndustry">↻ 刷新</button></div>${result.warning ? `<div class="terminal-warning">${escapeHtml(result.warning)}</div>` : ''}${industries.length ? `<div class="industry-grid">${industries.map((industry) => `<article class="content-panel"><div><h3>${escapeHtml(industry.name)}</h3><strong class="${metricClass(industry.change)}">${fmtPct(industry.change)}</strong></div><p>${industry.member_count} 个观察标的 · 成交额 ${fmtNum(industry.amount / 100000000, 2)} 亿</p><div>${(industry.members || []).map((member) => `<div class="industry-member"><span>${escapeHtml(member.name)} <small>${escapeHtml(member.symbol)}</small></span><b class="${metricClass(member.change)}">${fmtPct(member.change)}</b></div>`).join('')}</div></article>`).join('')}</div>` : '<div class="terminal-empty">当前观察池没有可用行业行情。</div>'}</section>`;
    $('#refreshIndustry').addEventListener('click', () => renderIndustry(true));
    return true;
  } catch (error) {
    host.innerHTML = `<div class="terminal-error">行业分析加载失败：${escapeHtml(error.message)}<button class="secondary-button" id="retryIndustry">重新加载</button></div>`;
    $('#retryIndustry').addEventListener('click', () => renderIndustry());
    return false;
  }
}

async function loadThemeCandidates(themeId) {
  const host = $('#themeCandidates');
  host.innerHTML = '<div class="page-loading">正在生成主题候选…</div>';
  try {
    const result = await api(`/api/theme-candidates/${themeId}`);
    const items = result.items || [];
    host.innerHTML = `<div class="table-page theme-table"><div class="table-page-header"><h2>${escapeHtml(result.theme.name)}候选</h2><span>${items.length} 个标的 · 可加入研究篮</span><div class="selection-count">已选 <b id="themeSelectedCount">0</b></div></div><div style="overflow:auto"><table><thead><tr><th><input class="row-check" type="checkbox" id="selectAllTheme" aria-label="全选候选标的"></th><th>标的</th><th>细分方向</th><th>研究逻辑</th><th>重点风险</th></tr></thead><tbody>${items.map((item) => `<tr class="theme-member-row" data-theme-member-row><td><input class="row-check theme-member-check" type="checkbox" value="${escapeHtml(item.symbol)}" aria-label="选择 ${escapeHtml(item.name)}"></td><td><strong>${escapeHtml(item.name)}</strong><br><small class="mono">${escapeHtml(item.symbol)}</small></td><td><span class="tag">${escapeHtml(item.segment)}</span></td><td>${escapeHtml(item.logic)}</td><td class="risk-text">${escapeHtml(item.risk)}</td></tr>`).join('')}</tbody></table></div></div>`;
    const memberBoxes = () => [...host.querySelectorAll('.theme-member-check')];
    const update = () => {
      const boxes = memberBoxes();
      const selected = boxes.filter((box) => box.checked).length;
      host.querySelector('#themeSelectedCount').textContent = selected;
      const selectAll = host.querySelector('#selectAllTheme');
      selectAll.checked = boxes.length > 0 && selected === boxes.length;
      selectAll.indeterminate = selected > 0 && selected < boxes.length;
      boxes.forEach((box) => box.closest('tr').classList.toggle('selected', box.checked));
    };
    host.onchange = (event) => {
      if (event.target.id === 'selectAllTheme') memberBoxes().forEach((box) => { box.checked = event.target.checked; });
      if (event.target.matches('.row-check')) update();
    };
    host.onclick = (event) => {
      const row = event.target.closest('[data-theme-member-row]');
      if (!row || event.target.matches('input, label')) return;
      const box = row.querySelector('.theme-member-check');
      box.checked = !box.checked;
      update();
    };
  } catch (error) { host.innerHTML = `<div class="page-loading">${escapeHtml(error.message)}</div>`; }
}

async function renderData(force = false) {
  const host = $('#dataContent'), items = state.datasets;
  if (!state.dataHealth || force) host.innerHTML = '<div class="page-loading">正在检查数据源状态…</div>';
  try {
    state.dataHealth = await api(`/api/data-health${force ? '?refresh=1' : ''}`);
    const health = state.dataHealth, summary = health.summary || {};
    host.innerHTML = `<section class="data-health"><div class="data-health-summary"><div><h2>数据源健康中心</h2><p>检测时间 ${escapeHtml(String(health.checked_at || '').replace('T', ' '))} · 可用 ${summary.healthy || 0} · 缓存 ${summary.cached || 0} · 不可用 ${summary.unavailable || 0} · 未检测 ${summary.unchecked || 0}</p></div><button class="primary-button" id="refreshDataHealth">检测全部数据源</button></div><div class="data-health-grid">${health.sources.map((source) => `<article class="data-health-card"><div class="data-health-card-head"><h3>${escapeHtml(source.name)}</h3>${dataStateBadge(source.status)}</div><dl><div><dt>数据模式</dt><dd>${escapeHtml(source.mode || '—')}</dd></div><div><dt>覆盖范围</dt><dd>${escapeHtml(source.scope || '—')}</dd></div><div><dt>交易日期</dt><dd>${escapeHtml(source.trade_date || '—')}</dd></div><div><dt>更新时间</dt><dd>${escapeHtml(String(source.as_of || '—').replace('T', ' ').slice(0, 19))}</dd></div><div><dt>记录数</dt><dd>${escapeHtml(source.records ?? '—')}</dd></div></dl><p class="data-health-message">${escapeHtml(source.message || '')}</p></article>`).join('')}</div></section><div class="table-page"><div class="table-page-header"><h2>本地数据资产</h2><span>${items.length} 个快照 · 原始数据保持不变</span></div><div style="overflow:auto"><table><thead><tr><th>标的</th><th>文件</th><th>周期</th><th>来源</th><th>区间</th><th>条数</th><th>大小</th><th>复权</th></tr></thead><tbody>${items.map((item) => `<tr><td><strong>${escapeHtml(item.symbol)}</strong></td><td class="mono">${escapeHtml(item.name)}</td><td>${escapeHtml(item.interval)}</td><td>${escapeHtml(item.source)}</td><td class="mono">${escapeHtml(item.first_date || '—')} → ${escapeHtml(item.last_date || '—')}</td><td class="mono">${escapeHtml(item.rows)}</td><td class="mono">${item.size_kb} KB</td><td>${escapeHtml(item.adjust)}</td></tr>`).join('')}</tbody></table></div></div>`;
    $('#refreshDataHealth').addEventListener('click', () => renderData(true));
  } catch (error) { host.innerHTML = `<div class="terminal-error">数据源状态检查失败：${escapeHtml(error.message)}<button class="secondary-button" id="retryDataHealth">重新检测</button></div>`; $('#retryDataHealth').onclick = () => renderData(true); }
}

async function runEnvironmentCheck() {
  const button = $('#checkEnvironment');
  const consoleEl = $('#environmentConsole');
  button.disabled = true; consoleEl.textContent = '$ 正在执行自检…';
  try {
    const result = await api('/api/environment-check', { method: 'POST', body: JSON.stringify({ network: $('#networkToggle').checked }) });
    consoleEl.innerHTML = `<span>$</span> ${result.ok ? '自检通过' : '自检未通过'} · ${result.duration}s\n\n${escapeHtml(result.output)}`;
    toast(result.ok ? '环境自检通过' : '环境自检发现问题', !result.ok);
  } catch (error) { consoleEl.textContent = `$ 自检失败\n\n${error.message}`; toast(error.message, true); }
  finally { button.disabled = false; }
}

function switchView(view) {
  closeSidebar();
  $$('.nav-item').forEach((item) => item.classList.toggle('active', item.dataset.view === view));
  $$('.view').forEach((item) => item.classList.toggle('active', item.id === `view-${view}`));
  const labels = {
    market: ['市场看板', '公开市场快照、指数趋势与研究标的池'],
    watchlist: ['自选', '本地保存的观察标的'],
    factory: ['策略', '策略池扫描与单股候选生成'],
    backtest: ['回测工作台', '多标的组合回测、净值与交易明细'],
    monitor: ['监控中心', '本地规则、市场快照评估与触发记录'],
    ladder: ['连板梯队', '涨停候选与连续涨停近似统计'],
    concepts: ['概念分析', '配置板块强弱、领涨领跌与成分股'],
    industry: ['行业分析', '行业热度、成交与内部结构'],
    stock: ['个股分析', '日线趋势、指标与策略候选'],
    finance: ['财务', '数据覆盖边界与待接入财务源'],
    indices: ['指数', '主要指数趋势与均线状态'],
    paper: ['交易', '本地模拟账户、持仓、订单与历史回放'],
    theme: ['主题候选', '选择研究方向并建立候选标的篮'],
    data: ['数据', '原始快照、来源与样本区间'],
    environment: ['环境状态', 'Python 运行时、策略引擎与行情接口检查'],
  };
  if (!labels[view]) return;
  $('#pageTitle').textContent = labels[view][0]; $('#pageSubtitle').textContent = labels[view][1];
  if (view === 'paper') renderPaper();
  if (view === 'theme' && !state.loadedViews.has(view)) { renderTheme(); state.loadedViews.add(view); }
  if (view === 'industry' && !state.loadedViews.has(view)) { renderIndustry().then((ok) => { if (ok) state.loadedViews.add(view); }); }
  if (view === 'data' && !state.loadedViews.has(view)) { renderData(); state.loadedViews.add(view); }
  closeSidebar();
}

function bindEvents() {
  $$('.nav-item').forEach((button) => button.addEventListener('click', () => switchView(button.dataset.view)));
  $('#dataSourceSelect').addEventListener('change', (event) => setSource(event.target.value));
  $('#groupSelect').addEventListener('change', renderAssetOptions);
  $('#assetSelect').addEventListener('change', () => {
    $('#customSymbolInput').value = '';
    $('#assetSelect').classList.remove('overridden');
    const type = currentAssetType();
    const groups = state.universe?.groups?.[type] || [];
    const group = groups.find((item) => item.id === $('#groupSelect').value) || groups[0];
    const selected = (group?.assets || []).find((asset) => asset.symbol === $('#assetSelect').value);
    $('#customAssetNameInput').value = selected?.name || '';
  });
  $('#customSymbolInput').addEventListener('input', (event) => {
    const custom = Boolean(event.target.value.trim());
    if (custom && !$('#assetSelect').classList.contains('overridden')) $('#customAssetNameInput').value = '';
    if (!custom) {
      const type = currentAssetType();
      const groups = state.universe?.groups?.[type] || [];
      const group = groups.find((item) => item.id === $('#groupSelect').value) || groups[0];
      const selected = (group?.assets || []).find((asset) => asset.symbol === $('#assetSelect').value);
      $('#customAssetNameInput').value = selected?.name || '';
    }
    $('#assetSelect').classList.toggle('overridden', custom);
  });
  $('#customSymbolInput').addEventListener('keydown', (event) => { if (event.key === 'Enter') generateCandidates(); });
  $('#generateButton').addEventListener('click', generateCandidates);
  $('#paperDraftButton').addEventListener('click', stagePaperStrategy);
  $('#okxDraftButton').addEventListener('click', stageOkxDemoStrategy);
  $('#recalculateStrategyButton').addEventListener('click', () => recalculateStrategy());
  $('#resetStrategyParametersButton').addEventListener('click', resetStrategyParameters);
  $('#saveStrategyVersionButton').addEventListener('click', saveStrategyVersion);
  $('#exportCurrentStrategyButton').addEventListener('click', exportCurrentStrategy);
  $('#importStrategyButton').addEventListener('click', () => $('#strategyImportInput').click());
  $('#strategyImportInput').addEventListener('change', (event) => importStrategyFile(event.target.files?.[0]));
  $('#refreshButton').addEventListener('click', () => window.location.reload());
  $('#menuButton').addEventListener('click', () => {
    const sidebar = $('#sidebar');
    sidebar.classList.toggle('open');
    if (sidebar.classList.contains('open')) sidebar.style.transform = '';
  });
  $('#checkEnvironment').addEventListener('click', runEnvironmentCheck);
  $$('.chart-tabs button').forEach((button) => button.addEventListener('click', () => { state.chart = button.dataset.chart; $$('.chart-tabs button').forEach((item) => item.classList.toggle('active', item === button)); if (state.candidates && state.selectedCandidate) renderCandidateDetail(state.candidates.candidates.find((item) => item.id === state.selectedCandidate)); }));
  window.addEventListener('resize', () => { if (state.candidates && state.selectedCandidate) renderCandidateDetail(state.candidates.candidates.find((item) => item.id === state.selectedCandidate)); });
  window.addEventListener('quantpilot:languagechange', () => {
    updateClock();
    window.I18n?.translateDom?.();
  });
}

async function init() {
  restoreOkxStrategyDraft();
  restoreStrategyVersions(); renderStrategyVersions();
  updateClock(); window.setInterval(updateClock, 30000); bindEvents();
  try {
    [state.overview, state.universe, state.paper] = await Promise.all([api('/api/overview'), api('/api/asset-universe'), api('/api/paper/account')]);
    state.datasets = state.overview.datasets || [];
    renderDatasetOptions();
    renderSourceOptions();
    const requestedView = new URLSearchParams(window.location.search).get('view');
    const views = ['market', 'watchlist', 'factory', 'backtest', 'monitor', 'ladder', 'concepts', 'industry', 'stock', 'finance', 'indices', 'paper', 'theme', 'data', 'environment'];
    if (views.includes(requestedView)) switchView(requestedView);
    else switchView('market');
  } catch (error) { toast(`项目读取失败：${error.message}`, true); }
}

init();

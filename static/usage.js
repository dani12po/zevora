import {$, api, escapeHtml, exposeHandlers, pageWrap, setPanel} from './core.js?v=20260818-10';

function usageRows(rows) {
  if (!rows.length) return '<tr><td colspan="8" class="table-empty">No usage data for this period.</td></tr>';
  return rows.map(row => `<tr><td><span class="table-date">${escapeHtml(row.day)}</span></td><td><span class="provider-mark">${escapeHtml(row.provider)}</span></td><td><code class="model-name">${escapeHtml(row.model || 'Not reported')}</code></td><td class="numeric-cell">${Number(row.requests || 0).toLocaleString()}</td><td class="numeric-cell">${Number(row.cache_hits || 0).toLocaleString()}</td><td class="numeric-cell">${Number(row.input_tokens || 0).toLocaleString()}</td><td class="numeric-cell">${Number(row.output_tokens || 0).toLocaleString()}</td><td class="numeric-cell cost-cell">$${Number(row.estimated_cost || 0).toFixed(6)}</td></tr>`).join('');
}

export async function renderUsage() {
  const [stats, history] = await Promise.all([api('/api/stats'), api('/api/usage/history?days=30')]);
  const today = stats.today || {};
  const requests = Number(today.requests || 0);
  const cacheHits = Number(today.cache_hits || 0);
  const cacheRate = requests ? Math.round((cacheHits / requests) * 100) : 0;
  const metrics = `<div class="metric-card"><div class="metric-icon requests-icon">R</div><div><div class="card-lbl">Requests today</div><div class="card-val">${requests.toLocaleString()}</div></div></div><div class="metric-card"><div class="metric-icon cache-icon">C</div><div><div class="card-lbl">Cache hits</div><div class="card-val">${cacheHits.toLocaleString()}</div></div></div><div class="metric-card"><div class="metric-icon rate-icon">%</div><div><div class="card-lbl">Cache hit rate</div><div class="card-val">${cacheRate}%</div></div></div><div class="metric-card"><div class="metric-icon cost-icon">$</div><div><div class="card-lbl">Estimated cost</div><div class="card-val cost-value">$${Number(today.estimated_cost || 0).toFixed(4)}</div></div></div>`;
  setPanel('Usage', pageWrap('<h2>Usage</h2>', `<section class="metrics-grid" aria-label="Today usage summary">${metrics}</section><section class="data-panel"><div class="panel-toolbar"><div><h3>Usage history</h3><p>Provider activity during the last 30 days</p></div><label class="filter-field"><span>Provider</span><select id="usage-provider-filter" onchange="filterUsage()"><option value="">All providers</option><option>local</option><option>openai</option><option>anthropic</option><option>gemini</option><option>deepseek</option><option>xai</option><option>nvidia</option></select></label></div><div class="tbl-wrap"><table class="tbl usage-table"><thead><tr><th>Date</th><th>Provider</th><th>Model</th><th>Requests</th><th>Cache hits</th><th>Input tokens</th><th>Output tokens</th><th>Est. cost</th></tr></thead><tbody id="usage-body">${usageRows(history.rows || [])}</tbody></table></div></section>`, 'Monitor requests, cache efficiency, token volume, and provider cost.'));
}

export async function filterUsage() {
  const provider = $('usage-provider-filter').value;
  const history = await api(`/api/usage/history?days=30${provider ? `&provider=${encodeURIComponent(provider)}` : ''}`);
  const body = $('usage-body');
  if (body) body.innerHTML = usageRows(history.rows || []);
}

exposeHandlers({filterUsage});

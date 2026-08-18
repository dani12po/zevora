import {$, api, badge, escapeHtml, exposeHandlers, fmtBytes, pageWrap, setPanel, stateIndicator} from './core.js?v=20260818-8';

const CATEGORY_LABELS = {raw:'RAW',processed:'PROC',curated:'CUR',memory:'MEM',cache:'CACHE',embeddings:'EMB',datasets:'DATA',archive:'ARC',evaluation:'EVAL',logs:'LOG',models:'MODEL'};

export async function renderCache() {
  const storage = await api('/api/storage');
  const budgetPercent = storage.budget_bytes > 0 ? Math.min(100, (storage.managed_bytes / storage.budget_bytes) * 100) : 0;
  const diskPercent = storage.disk_total_bytes > 0 ? Math.min(100, ((storage.disk_total_bytes - storage.disk_free_bytes) / storage.disk_total_bytes) * 100) : 0;
  const barColor = storage.state === 'critical' ? 'red' : storage.state === 'warning' ? 'yellow' : 'green';
  const status = storage.state === 'critical' ? badge('critical','red') : storage.state === 'warning' ? badge('warning','yellow') : badge('normal','green');
  const categories = Object.entries(storage.categories || {}).map(([name, value]) => `<div class="card card-sm"><div class="card-lbl"><span class="category-mark">${CATEGORY_LABELS[name] || 'FILE'}</span>${escapeHtml(name)}</div><div class="card-val">${fmtBytes(value)}</div></div>`).join('');
  setPanel('Cache', pageWrap(`<h2>Storage</h2>${status}`, `<div class="card"><div class="storage-heading"><b>Managed data</b><span class="technical-text">${fmtBytes(storage.managed_bytes)} / ${fmtBytes(storage.budget_bytes)}</span></div><div class="progress-wrap"><div class="progress-bar ${barColor}" style="width:${budgetPercent.toFixed(1)}%"></div></div><div class="storage-summary"><span>Free: ${fmtBytes(storage.disk_free_bytes)}</span><span>Total: ${fmtBytes(storage.disk_total_bytes)}</span><span>Used: ${diskPercent.toFixed(1)}%</span></div></div><div class="card-grid">${categories}</div><div class="card"><div class="state-context">${stateIndicator('local', 'Local managed storage')}<b>Maintenance</b></div><div class="maintenance-actions"><button class="btn-sm" id="btn-cleanup" onclick="runCleanup()">Clear expired files</button><span id="cleanup-msg" class="inline-status"></span></div></div>`));
}

export async function runCleanup() {
  const button = $('btn-cleanup');
  const message = $('cleanup-msg');
  button.classList.add('btn-loading');
  button.textContent = 'Running...';
  try {
    const result = await api('/api/maintenance/cleanup-plan', {method:'POST'});
    const count = result.would_delete?.length || 0;
    const savings = fmtBytes(result.estimated_bytes_saved || 0);
    message.textContent = count > 0 ? `${count} file(s) eligible - ${savings} recoverable (dry-run)` : 'Nothing to clean up.';
  } catch (error) {
    message.textContent = `Error: ${error.message}`;
  } finally {
    button.classList.remove('btn-loading');
    button.textContent = 'Clear expired files';
  }
}

exposeHandlers({runCleanup});

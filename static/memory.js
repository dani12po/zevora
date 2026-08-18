import {$, api, badge, escapeHtml, exposeHandlers, pageWrap, setPanel} from './core.js?v=20260818-9';

export async function renderMemory() {
  const memory = await api('/api/memory');
  const categories = memory.categories || {};
  const total = Object.values(categories).reduce((sum, value) => sum + value, 0);
  const cards = Object.entries(categories).map(([name, value]) => `<div class="card card-sm"><div class="card-lbl">${escapeHtml(name)}</div><div class="card-val">${value}</div></div>`).join('');
  setPanel('Memory', pageWrap(`<h2>Memory</h2>${badge(`${total} total`, 'grey')}`, `<div class="mem-grid">${cards || '<div class="muted-copy">No memory entries yet.</div>'}</div><div class="card"><b>Intelligence retention</b><p class="muted-copy">Preview expired operational records and low-value knowledge before deleting them.</p><div class="maintenance-actions"><button class="btn-sm" onclick="runIntelligenceMaintenance(false)">Preview cleanup</button><button class="btn-sm danger" onclick="runIntelligenceMaintenance(true)">Delete candidates</button><span id="intelligence-maintenance-msg" class="inline-status"></span></div></div>`));
}

export async function runIntelligenceMaintenance(execute) {
  if (execute && !confirm('Delete the retention candidates shown by the current policy?')) return;
  const message = $('intelligence-maintenance-msg');
  message.textContent = execute ? 'Deleting...' : 'Calculating...';
  try {
    const result = await api(`/api/maintenance/intelligence?execute=${execute ? 'true' : 'false'}`, {method:'POST'});
    const entries = Object.entries(result).filter(([key, value]) => !['ok','executed'].includes(key) && Number.isFinite(value));
    message.textContent = `${execute ? 'Deleted' : 'Candidates'} - ${entries.map(([key, value]) => `${key.replaceAll('_', ' ')}: ${value}`).join(' - ') || 'none'}`;
  } catch (error) {
    message.textContent = `Error: ${error.message}`;
  }
}

exposeHandlers({runIntelligenceMaintenance});

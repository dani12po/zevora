import {api, badge, escapeHtml, fmtBytes, pageWrap, setPanel, stateIndicator} from './core.js?v=20260818-10';

export async function renderLocalAI() {
  const [health, storage, memory, stats, intelligence, evolution] = await Promise.all([
    api('/api/health'), api('/api/storage'), api('/api/memory'), api('/api/stats'),
    api('/api/intelligence').catch(() => ({})), api('/api/evolution/status').catch(() => ({})),
  ]);
  const resources = health.local_resource || {};
  const categories = memory.categories || {};
  const today = stats.today || {};
  const cacheHits = intelligence.api_calls_avoided ?? (today.cache_hits || 0);
  const totalRequests = intelligence.total_api_calls ?? (today.requests || 0);
  const hitRate = intelligence.cache_hit_rate ?? (totalRequests > 0 ? Math.round((cacheHits / totalRequests) * 100) : 0);
  const providers = (health.providers_configured || []).map(escapeHtml).join(', ') || 'None configured';
  const categoryCards = Object.entries(categories).map(([name, value]) => `<div class="card card-sm"><div class="card-lbl">${escapeHtml(name)}</div><div class="card-val">${value}</div></div>`).join('') || '<span class="muted-copy">No memory entries yet.</span>';

  setPanel('Local Intelligence', pageWrap(
    `<h2>Local Intelligence</h2>${badge('Local active','green')}`,
    `<div class="card local-overview"><div class="state-context">${stateIndicator('local', 'On-device intelligence')}<p>ZEVORA keeps memory, experience, project context, and cache on this machine. Zevora Local AI handles eligible generation privately through llama.cpp, while configured cloud providers handle complex, vision, and fallback work.</p></div>
      <div class="card-grid">
        <div class="card-sm card"><div class="card-lbl">Memory</div><div class="card-val">${fmtBytes(storage.categories?.memory || 0)}</div></div>
        <div class="card-sm card"><div class="card-lbl">Knowledge Patterns</div><div class="card-val">${intelligence.knowledge_count || 0}</div></div>
        <div class="card-sm card"><div class="card-lbl">Cache</div><div class="card-val">${fmtBytes(storage.categories?.cache || 0)}</div></div>
        <div class="card-sm card"><div class="card-lbl">Experience</div><div class="card-val">${fmtBytes(storage.categories?.experience || 0)}</div></div>
        <div class="card-sm card"><div class="card-lbl">Cache hit rate</div><div class="card-val">${hitRate}%</div></div>
        <div class="card-sm card"><div class="card-lbl">API calls avoided</div><div class="card-val">${cacheHits}</div></div>
        <div class="card-sm card"><div class="card-lbl">RAM available</div><div class="card-val">${resources.ram_available_mb ? `${resources.ram_available_mb} MB` : '-'}</div></div>
      </div></div>
    <div class="card"><b>Memory categories</b><div class="mem-grid section-grid">${categoryCards}</div></div>
    <div class="card"><b>Local model and evolution</b><div class="card-grid section-grid">
      <div class="card-sm card"><div class="card-lbl">Runtime</div><div class="card-val technical-text compact-value">${escapeHtml(evolution.local_intelligence?.runtime || 'unknown')}</div></div>
      <div class="card-sm card"><div class="card-lbl">Installed packages</div><div class="card-val">${evolution.local_intelligence?.installed_packages?.length || 0}</div></div>
      <div class="card-sm card"><div class="card-lbl">Registered skills</div><div class="card-val">${evolution.skills?.length || 0}</div></div>
      <div class="card-sm card"><div class="card-lbl">Validated patterns</div><div class="card-val">${evolution.evolution?.validated_patterns || 0}</div></div>
      <div class="card-sm card"><div class="card-lbl">Collective learning</div><div class="card-val compact-value">${evolution.collective_learning?.enabled ? 'Enabled' : 'Disabled'}</div></div>
      <div class="card-sm card"><div class="card-lbl">Update verification</div><div class="card-val compact-value">${escapeHtml(evolution.updates?.verification || 'unknown')}</div></div>
    </div></div>
    <div class="card"><b>Active providers</b><p class="muted-copy technical-text">${providers}</p><p class="muted-copy">Configure provider API keys in <a href="/providers" data-route class="accent-link">Providers</a>.</p></div>`,
  ));
}

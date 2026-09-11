import {$, api, badge, escapeHtml, fmtBytes, pageWrap, setPanel, stateIndicator, userErrorMessage} from './core.js?v=20260819-3';

export async function renderLocalAI() {
  const [health, storage, memory, stats, intelligence, evolution, lexi] = await Promise.all([
    api('/api/health'), api('/api/storage'), api('/api/memory'), api('/api/stats'),
    api('/api/intelligence').catch(() => ({})), api('/api/evolution/status').catch(() => ({})),
    api('/api/local-model/status').catch(() => null),
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
    <div class="card"><b>Lexi local model</b><div class="card-grid section-grid">
      <div class="card-sm card"><div class="card-lbl">Embedded</div><div class="card-val compact-value">${lexi?.embedded ? `${escapeHtml(lexi.embedded.display_name || '')} - ${escapeHtml(lexi.embedded.state || '')}` : 'Unavailable'}</div></div>
      <div class="card-sm card"><div class="card-lbl">GGUF size</div><div class="card-val">${lexi?.embedded?.model_size_mb ? `${lexi.embedded.model_size_mb} MB` : '-'}</div></div>
      <div class="card-sm card"><div class="card-lbl">Remote</div><div class="card-val compact-value">${lexi?.remote?.base_url ? escapeHtml(lexi.remote.base_url) : 'Not configured'}</div></div>
      <div class="card-sm card"><div class="card-lbl">Remote latency</div><div class="card-val">${lexi?.remote?.last_latency_ms != null ? `${lexi.remote.last_latency_ms} ms` : '-'}</div></div>
    </div><div class="provider-save"><span class="save-msg" id="lexi-manage-msg"></span><button class="btn-sm" id="lexi-unload">Unload</button><button class="btn-sm" id="lexi-restart">Restart</button></div>
    <p class="muted-copy">Managed GGUF files are never deleted automatically; removal requires explicit approval in Providers. Configure the remote endpoint in <a href="/providers" data-route class="accent-link">Providers</a>.</p></div>
    <div class="card"><b>Active providers</b><p class="muted-copy technical-text">${providers}</p><p class="muted-copy">Configure provider API keys in <a href="/providers" data-route class="accent-link">Providers</a>.</p></div>`,
  ));
  const manageMsg = (text, isError) => { const el = $('lexi-manage-msg'); if (!el) return; el.textContent = text; el.classList.toggle('error-text', !!isError); el.classList.add('show'); setTimeout(() => el.classList.remove('show'), 3000); };
  const manage = async (action) => {
    try { const result = await api(`/api/local-model/${action}`, {method: 'POST'}); manageMsg(`${action}: ${result.released !== undefined ? (result.released ? 'released' : 'already idle') : 'ok'}`); }
    catch (error) { manageMsg(userErrorMessage(error), true); }
  };
  if ($('lexi-unload')) $('lexi-unload').onclick = () => manage('unload');
  if ($('lexi-restart')) $('lexi-restart').onclick = () => manage('restart');
}

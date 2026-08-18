import {api, escapeHtml, pageWrap, setPanel, stateIndicator} from './core.js?v=20260818-8';

export async function renderModelRouter() {
  const settings = await api('/api/routing/settings');
  const mode = settings.mode || 'AUTO';
  const steps = [
    {label:'Local context', description:'Cache - Memory - Project', kind:'local'},
    {label:'Hybrid scoring', description:'Capability - Complexity - History', kind:'hybrid'},
    {label:'Local or cloud', description:'Zevora Local AI - Cloud providers', kind:'cloud'},
  ];
  const flow = steps.map((step, index) => `${index ? '<span class="route-arrow">&#8594;</span>' : ''}<div class="route-step active-step"><div>${step.label}</div><div class="route-description">${step.description}</div></div>`).join('');
  setPanel('Model Router', pageWrap('<h2>Model Router</h2>', `
    <div class="card"><div class="router-heading"><b>Request flow</b><div>${stateIndicator('local', 'Local first')}${stateIndicator('cloud', 'Cloud fallback')}</div></div>
      <div class="route-flow">${flow}</div><div class="card-grid">
        <div class="card-sm card"><div class="card-lbl">Mode</div><div class="card-val compact-value technical-text">${escapeHtml(mode)}</div></div>
        <div class="card-sm card"><div class="card-lbl">Cloud fallback</div><div class="card-val compact-value">${settings.cloud_fallback ? 'Yes' : 'No'}</div></div>
        <div class="card-sm card"><div class="card-lbl">Cost optimized</div><div class="card-val compact-value">${settings.cost_optimization ? 'Yes' : 'No'}</div></div>
        <div class="card-sm card"><div class="card-lbl">Repair attempts</div><div class="card-val">${settings.max_repair_attempts}</div></div>
      </div></div>
    <div class="card"><b>How routing works</b><ol class="routing-steps">
      <li>Check exact cache; return immediately on a hit with zero API cost.</li><li>Classify task type and required capabilities.</li><li>Score configured providers by capability, cost, and history.</li><li>Execute on the best-scoring provider.</li><li>Fallback between local and cloud candidates after failure or quality rejection.</li><li>Store the result in cache and update routing experience.</li>
    </ol></div><p class="muted-copy">Change routing mode in <a href="/settings" data-route class="accent-link">Settings</a>. Configure providers in <a href="/providers" data-route class="accent-link">Providers</a>.</p>`));
}

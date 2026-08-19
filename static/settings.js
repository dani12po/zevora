import {$, api, escapeHtml, pageWrap, setPanel, userErrorMessage} from './core.js?v=20260819-2';

export async function renderSettings() {
  const settings = await api('/api/settings');
  setPanel('Settings', pageWrap('<h2>Settings</h2>', `<form id="settings-form"><div class="card settings-card"><div class="settings-section"><h3>Routing</h3><div class="settings-row"><label for="s-routing-mode">Routing mode</label><select id="s-routing-mode"><option value="AUTO" ${settings.routing_mode === 'AUTO' ? 'selected' : ''}>AUTO - local-first or cloud-first by task</option><option value="LOCAL_ONLY" ${settings.routing_mode === 'LOCAL_ONLY' ? 'selected' : ''}>LOCAL ONLY - never call cloud providers</option><option value="CLOUD_ONLY" ${settings.routing_mode === 'CLOUD_ONLY' ? 'selected' : ''}>CLOUD ONLY - never load the local model</option></select></div><div class="toggle-row"><label>Cloud fallback (retry with another provider on failure)</label><label class="toggle"><input type="checkbox" id="s-cloud-fallback" ${settings.cloud_fallback ? 'checked' : ''}><span class="toggle-slider"></span></label></div><div class="toggle-row"><label>Cost optimization (prefer cheaper capable providers)</label><label class="toggle"><input type="checkbox" id="s-cost-opt" ${settings.cost_optimization ? 'checked' : ''}><span class="toggle-slider"></span></label></div></div></div><div class="card settings-card"><div class="settings-section"><h3>Gateway</h3><div class="settings-row"><label>Gateway URL</label><input class="technical-text" value="${escapeHtml(settings.gateway_url)}" disabled></div></div></div><div class="settings-actions"><button type="submit" class="primary">Save changes</button><span id="settings-save-msg" class="save-msg"></span></div></form>`));
  $('settings-form').onsubmit = saveSettings;
}

async function saveSettings(event) {
  event.preventDefault();
  try {
    await api('/api/settings',{method:'POST',body:JSON.stringify({routing_mode:$('s-routing-mode').value,cloud_fallback:$('s-cloud-fallback').checked,cost_optimization:$('s-cost-opt').checked})});
    const message = $('settings-save-msg'); message.textContent = 'Saved'; message.classList.remove('error-text'); message.classList.add('show'); setTimeout(() => message.classList.remove('show'), 2500);
  } catch (error) {
    const message = $('settings-save-msg'); message.textContent = userErrorMessage(error); message.classList.add('show','error-text');
  }
}

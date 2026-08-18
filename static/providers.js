import {$, api, badge, emptyState, escapeHtml, exposeHandlers, pageWrap, setPanel, userErrorMessage} from './core.js?v=20260818-10';

const customManifestCache = new Map();
const providerHealthCache = new Map();

const LABELS = {local:'Zevora Local AI',openai:'OpenAI',xai:'xAI (Grok)',nvidia:'NVIDIA NIM',deepseek:'DeepSeek',gemini:'Google Gemini',anthropic:'Anthropic'};
const DESCRIPTIONS = {
  local:'Private on-device GGUF runtime - llama.cpp - no API key required',
  openai:'GPT-4o family - OpenAI-compatible API', xai:'Grok family - xAI API',
  nvidia:'NIM inference - NVIDIA API', deepseek:'DeepSeek family - reasoning-capable',
  gemini:'Gemini family - Google AI', anthropic:'Claude family - Anthropic API',
};

function providerHealth(provider, modelCount) {
  const health = provider.health_status || provider.state?.toLowerCase() || 'unconfigured';
  if (health === 'healthy' && modelCount > 0) return badge('healthy','green');
  if (health === 'trusted_runtime') return badge('trusted runtime','green');
  if (health === 'testing') return badge('testing','yellow');
  if (health === 'failed' || health === 'unavailable') return badge('unavailable','red');
  if (!provider.key_set && provider.provider !== 'local') return badge('not configured','grey');
  return badge(health === 'healthy' ? 'no models' : health, 'yellow');
}

function healthDotState(provider, health = null) {
  const local = provider.provider === 'local';
  if (local) {
    const runtime = provider.runtime_status || {};
    return runtime.loaded || (runtime.configured && runtime.model_exists) ? 'healthy' : runtime.configured ? 'unavailable' : 'unconfigured';
  }
  const normalized = String(health || provider.health_status || provider.state || '').toLowerCase();
  if (!provider.key_set && !provider.credential?.configured) return 'unconfigured';
  if (normalized === 'healthy' || normalized === 'trusted_runtime' || normalized === 'loaded' || normalized === 'ready') return 'healthy';
  if (normalized === 'testing') return 'testing';
  if (normalized === 'failed' || normalized === 'unavailable') return 'unavailable';
  return 'unconfigured';
}

function healthDot(id, provider, health = null) {
  const state = healthDotState(provider, health);
  const label = state === 'healthy' ? 'Healthy' : state === 'unavailable' ? 'Unavailable' : state === 'testing' ? 'Checking' : 'Not checked';
  return `<span id="health-dot-${id}" class="provider-health-dot provider-health-dot-${state}" data-health-state="${state}" title="API health: ${label}" aria-label="API health: ${label}"></span>`;
}

function healthRefreshButton(id, custom = false, local = false, isRuntime = false) {
  return `<button class="provider-health-refresh" type="button" title="Refresh API health" aria-label="Refresh API health" onclick="refreshProviderHealth('${id}', ${custom}, ${local}, ${isRuntime}, this)">↻</button>`;
}

function updateHealthIndicator(id, provider, health, modelCount = 0) {
  const dot = $(`health-dot-${id}`);
  if (!dot) return;
  const state = healthDotState(provider, health);
  dot.className = `provider-health-dot provider-health-dot-${state}`;
  dot.dataset.healthState = state;
  const label = state === 'healthy' ? 'Healthy' : state === 'unavailable' ? 'Unavailable' : state === 'testing' ? 'Checking' : 'Not checked';
  dot.title = `API health: ${label}`;
  dot.setAttribute('aria-label', `API health: ${label}`);
  const badgeTarget = $(`health-badge-${id}`);
  if (!badgeTarget) return;
  if (provider.provider === 'local') {
    const runtime = provider.runtime_status || {};
    const localState = runtime.loaded ? 'loaded' : runtime.configured ? 'ready' : 'unavailable';
    badgeTarget.innerHTML = localState === 'loaded' || localState === 'ready' ? badge(`local ${localState}`, 'green') : badge('local unavailable', 'red');
  } else {
    badgeTarget.innerHTML = providerHealth({...provider, health_status: health || state}, modelCount);
  }
}

function normalizeCustomProvider(manifest, modelCounts) {
  return {
    ...manifest,
    provider: manifest.provider_id,
    provider_id: manifest.provider_id,
    key_set: Boolean(manifest.credential?.configured),
    key_masked: manifest.credential?.masked || '',
    supports_vision: manifest.capabilities?.vision ?? false,
    health_status: manifest.state,
    model_count: modelCounts[manifest.provider_id] || 0,
    isCustom: true,
  };
}

function customBadge() { return badge('custom','purple'); }

function providerCard(provider, statusMap, modelCounts) {
  const custom = provider.isCustom;
  const modelCount = provider.model_count ?? modelCounts[provider.provider] ?? 0;
  const health = statusMap[provider.provider] || provider.health_status || (provider.provider === 'local' && provider.runtime_status?.configured ? 'healthy' : 'unconfigured');
  if (provider.provider === 'local') {
    const runtime = provider.runtime_status || {};
    const state = runtime.loaded ? 'loaded' : runtime.configured ? 'ready' : 'unavailable';
    const stateBadge = state === 'loaded' || state === 'ready' ? badge(`local ${state}`, 'green') : badge('local unavailable', 'red');
    return `<div class="card provider-shell"><div class="provider-card">
      <div class="provider-card-name"><span>${LABELS.local}</span>${healthDot('local', provider)}${healthRefreshButton('local', false, true)} <span id="health-badge-local">${stateBadge}</span></div><div class="technical-text">${runtime.runtime || 'llamacpp'}</div>
      <div class="provider-description">${DESCRIPTIONS.local}</div><div class="card-grid provider-stats">
        <div class="card-sm card"><div class="card-lbl">Model</div><div class="card-val technical-text">${escapeHtml(runtime.model_id || provider.default_model || 'zevora')}</div></div>
        <div class="card-sm card"><div class="card-lbl">GGUF</div><div class="card-val">${runtime.model_exists ? `${runtime.model_size_mb} MB` : 'Missing'}</div></div>
        <div class="card-sm card"><div class="card-lbl">Context</div><div class="card-val">${runtime.context_length || '-'}</div></div>
        <div class="card-sm card"><div class="card-lbl">Process RSS</div><div class="card-val">${runtime.process_rss_mb ? `${runtime.process_rss_mb} MB` : '-'}</div></div>
        <div class="card-sm card"><div class="card-lbl">Load delta</div><div class="card-val">${runtime.load_delta_mb ? `${runtime.load_delta_mb} MB` : 'Not loaded'}</div></div>
      </div><div class="provider-path technical-text">${escapeHtml(runtime.model_path || '')}</div>
    </div></div>`;
  }
  const id = escapeHtml(provider.provider);
  const name = escapeHtml(provider.name || LABELS[provider.provider] || provider.provider);
  const description = escapeHtml(provider.description || DESCRIPTIONS[provider.provider] || 'Custom AI provider');
  const runtimeDetails = custom && provider.protocol === 'custom-runtime' ? `<details class="provider-runtime-details"><summary>Runtime source and trust</summary><div class="runtime-source-row"><button class="btn-sm" onclick="loadRuntimeSource('${id}', this)">Load source</button><button class="btn-sm" onclick="trustCustomProvider('${id}')" ${provider.runtime?.trusted ? 'disabled' : ''}>${provider.runtime?.trusted ? 'Trusted' : 'Trust runtime'}</button></div><textarea id="runtime-source-${id}" class="runtime-source hidden" rows="8" placeholder="Load the stored runtime source before editing"></textarea></details>` : '';
  const reportedHealth = statusMap[provider.provider] || provider.health_status;
  const resolvedHealth = reportedHealth === 'disabled' ? providerHealthCache.get(provider.provider) : reportedHealth;
  return `<div class="card provider-shell ${custom ? 'provider-custom' : ''}"><div class="provider-card">
    <div class="provider-card-name"><span>${name}</span>${healthDot(id, {...provider, health_status: resolvedHealth})}${healthRefreshButton(id, custom, false, provider.protocol === 'custom-runtime')} ${custom ? customBadge() : ''} <span id="health-badge-${id}">${providerHealth({...provider, health_status: resolvedHealth}, modelCount)}</span></div>
    <div class="provider-summary"><span>${modelCount} models</span><label class="toggle" title="Enabled"><input type="checkbox" id="toggle-${id}" ${provider.enabled ? 'checked' : ''} onchange="${custom ? `toggleCustomProvider('${id}', this.checked)` : `markProviderDirty('${id}')`}"><span class="toggle-slider"></span></label></div>
    <div class="provider-description">${description}</div>
    <div class="provider-fields"><div class="provider-field"><label>API Key</label><span class="key-display" id="key-display-${id}">${provider.key_set ? `********${escapeHtml(provider.key_masked.slice(-4))}` : 'Not set'}</span><button class="btn-sm" onclick="${custom ? `toggleCustomKeyEdit('${id}')` : `toggleKeyEdit('${id}')`}">Edit</button></div>
      <div class="provider-field" id="key-edit-${id}" style="display:none"><label>New key</label><input type="password" id="key-input-${id}" placeholder="sk-..." autocomplete="new-password"><button class="btn-sm" onclick="${custom ? `cancelCustomKeyEdit('${id}')` : `cancelKeyEdit('${id}')`}">Cancel</button></div>
      <div class="provider-field"><label>Base URL</label><input id="url-${id}" value="${escapeHtml(provider.base_url || '')}" oninput="markProviderDirty('${id}')"><span></span></div>
      <div class="provider-field"><label>Default Model</label><input id="model-${id}" value="${escapeHtml(provider.default_model || '')}" oninput="markProviderDirty('${id}')"><span></span></div>
      <div class="provider-field"><label>Image input</label><label class="toggle"><input type="checkbox" id="vision-${id}" ${provider.supports_vision ? 'checked' : ''} onchange="markProviderDirty('${id}')"><span class="toggle-slider"></span></label><span></span></div>
      <div class="provider-field"><label>Priority</label><input type="number" id="prio-${id}" value="${provider.routing_priority ?? 50}" min="0" max="999" oninput="markProviderDirty('${id}')"><span></span></div>
      ${custom ? `<div class="provider-field"><label for="provider-name-${id}">Name</label><input id="provider-name-${id}" value="${escapeHtml(provider.name || '')}" oninput="markProviderDirty('${id}')"><span></span></div><div class="provider-field"><label for="protocol-${id}">Protocol</label><select id="protocol-${id}" onchange="markProviderDirty('${id}')"><option ${provider.protocol === 'openai-compatible' ? 'selected' : ''}>openai-compatible</option><option ${provider.protocol === 'anthropic-compatible' ? 'selected' : ''}>anthropic-compatible</option><option ${provider.protocol === 'http-rest' ? 'selected' : ''}>http-rest</option><option ${provider.protocol === 'local-openai-compatible' ? 'selected' : ''}>local-openai-compatible</option><option ${provider.protocol === 'custom-runtime' ? 'selected' : ''}>custom-runtime</option><option ${provider.protocol === 'unknown' ? 'selected' : ''}>unknown</option></select><span></span></div><div class="provider-field"><label for="env-${id}">Credential env</label><input id="env-${id}" value="${escapeHtml(provider.credential?.name || '')}" oninput="markProviderDirty('${id}')" placeholder="PROVIDER_API_KEY"><span></span></div>` : ''}
    </div>${runtimeDetails}<div class="provider-save"><span class="save-msg" id="save-msg-${id}"></span><button class="btn-sm" onclick="${custom ? `testCustomProvider('${id}', ${provider.protocol === 'custom-runtime'})` : `testProvider('${id}', this)`}">Test connection</button><button class="btn-sm" id="save-btn-${id}" onclick="${custom ? `saveCustomProviderCard('${id}')` : `saveProvider('${id}')`}" disabled>Save</button>${custom ? `<button class="btn-sm danger" onclick="removeCustomProvider('${id}')">Delete</button>` : ''}</div>
  </div></div>`;
}

function addProviderCardHtml() {
  return `<button class="card provider-shell add-provider-card" type="button" onclick="toggleAddProviderForm()"><span class="add-provider-icon" aria-hidden="true">+</span><span><b>Add new provider</b><small>Connect a custom AI endpoint</small></span></button>`;
}

function providerFormHtml() {
  return `<section class="provider-manager hidden" id="custom-provider-form"><div class="panel-toolbar"><div><h3>Add new provider</h3><p>Connect your own AI API. Use the examples below to fill each field.</p><div class="provider-setup-guide"><b>Quick setup</b><ol><li>Copy the API key into <strong>Credential value</strong>.</li><li>Enter the API key variable name in <strong>Credential environment</strong>.</li><li>Enter the provider API URL, model name, and a simple ID.</li><li>Click <strong>Save provider</strong>, then <strong>Test</strong>.</li></ol></div><p id="provider-message" class="inline-status" aria-live="polite"></p></div><button class="btn-sm" type="button" onclick="toggleAddProviderForm()">Close</button></div><div class="provider-form-grid">
    <label>ID<span class="field-help">Short unique ID, not your API key</span><input id="custom-provider-id" placeholder="agentrouter"></label><label>Name<span class="field-help">Display name shown in ZEVORA</span><input id="custom-provider-name" placeholder="AgentRouter"></label><label>Protocol<span class="field-help">Choose the API format from the provider docs</span><select id="custom-provider-protocol"><option>openai-compatible</option><option>anthropic-compatible</option><option>http-rest</option><option>local-openai-compatible</option><option>custom-runtime</option><option>unknown</option></select></label><label>Base URL<span class="field-help">API base URL, for example https://provider.example/v1</span><input id="custom-provider-url" placeholder="https://provider.example/v1"></label><label>Default model<span class="field-help">Exact model ID from the provider</span><input id="custom-provider-model" placeholder="model-name"></label><label>Credential environment<span class="field-help">Variable name, for example AGENTROUTER_API_KEY</span><input id="custom-provider-env" placeholder="AGENTROUTER_API_KEY" autocomplete="off"></label><label>Credential value<span class="field-help">Paste the secret API key here</span><input id="custom-provider-key" type="password" placeholder="Paste API key" autocomplete="new-password"></label><label>Runtime language<span class="field-help">Used only with custom-runtime</span><select id="custom-provider-runtime"><option value="python">Python</option><option value="node">Node</option><option value="typescript">TypeScript</option><option value="shell">Shell</option></select></label>
    </div><label class="provider-source-label">Example or runtime source<span class="field-help">Leave empty for standard compatible APIs.</span><textarea id="custom-provider-source" rows="8" placeholder="Leave empty for a standard compatible API"></textarea></label><div class="provider-actions"><button class="btn-sm" onclick="analyzeProviderSource()">Analyze</button><button class="btn-sm" onclick="importProviderJson()">Import JSON</button><button class="btn-sm" onclick="saveCustomProvider()">Save provider</button></div><pre id="provider-analysis" class="analysis-preview hidden"></pre></section>`;
}

export function toggleAddProviderForm() { $('custom-provider-form')?.classList.toggle('hidden'); }

export async function renderProviders() {
  const [statuses, config, models, manifests] = await Promise.all([api('/api/providers'), api('/api/providers/config'), api('/api/models'), api('/api/provider-manifests').catch(() => ({providers:[]}))]);
  const counts = {}, statusMap = {};
  models.forEach(model => { counts[model.provider] = (counts[model.provider] || 0) + 1; });
  statuses.forEach(provider => {
    statusMap[provider.provider] = provider.health_status;
    if (provider.health_status && provider.health_status !== 'disabled') providerHealthCache.set(provider.provider, provider.health_status);
  });
  const custom = (manifests.providers || []).map(item => normalizeCustomProvider(item, counts));
  customManifestCache.clear();
  custom.forEach(provider => customManifestCache.set(provider.provider, provider));
  const cards = [...config.map(provider => providerCard(provider, statusMap, counts)), ...custom.map(provider => providerCard(provider, statusMap, counts)), addProviderCardHtml()].join('');
  setPanel('Providers', pageWrap('<h2>Providers</h2>', `<div class="provider-card-grid">${cards}</div>${providerFormHtml()}`));
}

export async function analyzeProviderSource() {
  const source = $('custom-provider-source').value.trim(); if (!source) return;
  await providerAction(async()=>{
    const {analysis} = await api('/api/provider-manifests/analyze',{method:'POST',body:JSON.stringify({source,language:'auto'})});
    $('provider-analysis').textContent = JSON.stringify(analysis,null,2); $('provider-analysis').classList.remove('hidden');
    if (analysis.protocol && analysis.protocol !== 'unknown') $('custom-provider-protocol').value = analysis.protocol;
    if (analysis.base_url) $('custom-provider-url').value = analysis.base_url;
    if (analysis.model) $('custom-provider-model').value = analysis.model;
    if (analysis.credential_env) $('custom-provider-env').value = analysis.credential_env;
  });
}

function showProviderMessage(message, error = false) { const status = $('provider-message'); if (!status) return; status.textContent = message; status.classList.toggle('error-text', error); }
async function providerAction(action, success = '') { try { const result = await action(); if (success) showProviderMessage(success); return result; } catch (error) { showProviderMessage(userErrorMessage(error), true); return null; } }
function customProviderPayload() { const protocol = $('custom-provider-protocol').value, language = $('custom-provider-runtime').value; return {provider_id:$('custom-provider-id').value.trim().toLowerCase(),name:$('custom-provider-name').value.trim(),protocol,base_url:$('custom-provider-url').value.trim(),default_model:$('custom-provider-model').value.trim(),credential:{source:'environment',name:$('custom-provider-env').value.trim().toUpperCase()},enabled:true,routing_priority:50,capabilities:{chat:true,streaming:null,reasoning:null,vision:null,tool_calling:null},runtime:protocol === 'custom-runtime' ? {runtime:language,entrypoint:language === 'python' ? 'provider.py' : language === 'shell' ? 'provider.sh' : 'provider.js',trusted:false,permissions:{network:true,filesystem:'temporary',workspace:false,allowed_hosts:[]}} : null}; }

export async function saveCustomProvider() { const manifest=customProviderPayload(); await providerAction(async()=>{await api('/api/provider-manifests',{method:'POST',body:JSON.stringify({manifest,credential_value:$('custom-provider-key').value||null,script:manifest.runtime?$('custom-provider-source').value:null})});await renderProviders();showProviderMessage('Provider saved.');}); }
export async function importProviderJson() { let manifest; try { manifest=JSON.parse($('custom-provider-source').value.trim()); } catch (_) { showProviderMessage('Paste a valid provider manifest JSON document.',true); return; } await providerAction(async()=>{await api('/api/provider-manifests/import',{method:'POST',body:JSON.stringify({manifest,credential_value:$('custom-provider-key').value||null})});await renderProviders();showProviderMessage('Provider imported.');}); }
export async function saveCustomProviderCard(id) {
  const original = customManifestCache.get(id);
  if (!original) return;
  const key = $(`key-input-${id}`);
  const payload = {
    ...original,
    provider_id: id,
    name: $(`provider-name-${id}`)?.value?.trim() || original.name,
    protocol: $(`protocol-${id}`)?.value || original.protocol,
    base_url: $(`url-${id}`)?.value?.trim() || '',
    default_model: $(`model-${id}`)?.value?.trim() || '',
    credential: {...(original.credential || {}), source: 'environment', name: ($(`env-${id}`)?.value || original.credential?.name || '').trim().toUpperCase()},
    enabled: $(`toggle-${id}`)?.checked ?? original.enabled,
    routing_priority: Number.parseInt($(`prio-${id}`)?.value, 10) || 50,
    capabilities: {...(original.capabilities || {}), chat: true, vision: $(`vision-${id}`)?.checked ?? false},
  };
  if (payload.protocol !== 'custom-runtime') payload.runtime = null;
  const source = $(`runtime-source-${id}`);
  const script = payload.protocol === 'custom-runtime' && source && !source.classList.contains('hidden') ? source.value : null;
  await providerAction(async()=>{await api('/api/provider-manifests',{method:'POST',body:JSON.stringify({manifest:payload,credential_value:key?.value?.trim() || null,script})});await renderProviders();});
}
export async function toggleCustomProvider(id, enabled) { await providerAction(async()=>{await api(`/api/provider-manifests/${id}/enabled`,{method:'POST',body:JSON.stringify({enabled})});await renderProviders();}); }
export async function testCustomProvider(id,isRuntime) {
  if (isRuntime && !confirm('Run this provider script once with its declared credential and permissions?')) return;
  const provider = customManifestCache.get(id) || {provider:id,key_set:true};
  try {
    const result = await api(`/api/provider-manifests/${id}/${isRuntime?'runtime-test':'test'}`,{method:'POST',body:JSON.stringify({runtime_approved:isRuntime})});
    const success = Boolean(result.result?.success);
    updateHealthIndicator(id, provider, success ? 'healthy' : 'unavailable', provider.model_count || 0);
    showProviderMessage(success ? 'Connection succeeded' : result.result?.message || 'Connection failed', !success);
  } catch (error) {
    updateHealthIndicator(id, provider, 'unavailable', provider.model_count || 0);
    showProviderMessage(userErrorMessage(error), true);
  }
}
export async function trustCustomProvider(id) { if(confirm('Trust this runtime for future provider requests?')) await providerAction(async()=>{await api(`/api/provider-manifests/${id}/trust`,{method:'POST',body:JSON.stringify({approved:true})});await renderProviders();}); }
export async function removeCustomProvider(id) { if(confirm(`Delete "${id}" and its stored runtime source?`)) await providerAction(async()=>{await api(`/api/provider-manifests/${id}`,{method:'DELETE'});await renderProviders();}); }
export async function loadRuntimeSource(id, button) { button.disabled=true; try { const data=await api(`/api/provider-manifests/${id}/source`); const source=$(`runtime-source-${id}`); source.value=data.source || ''; source.classList.remove('hidden'); source.addEventListener('input',()=>markProviderDirty(id),{once:true}); } catch (error) { showProviderMessage(userErrorMessage(error),true); } finally { button.disabled=false; } }
export async function exportCustomProvider(id) { await providerAction(async()=>{const data=await api(`/api/provider-manifests/${id}/export`), blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'}), link=document.createElement('a'); link.href=URL.createObjectURL(blob); link.download=`${id}.provider.json`; link.click(); URL.revokeObjectURL(link.href);}); }
export function markProviderDirty(id) { const button=$(`save-btn-${id}`); if(button) button.disabled=false; }
export function toggleKeyEdit(id) { $(`key-edit-${id}`).style.display='grid'; $(`key-display-${id}`).closest('.provider-field').style.display='none'; markProviderDirty(id); }
export function cancelKeyEdit(id) { $(`key-edit-${id}`).style.display='none'; $(`key-display-${id}`).closest('.provider-field').style.display='grid'; }
export function toggleCustomKeyEdit(id) { toggleKeyEdit(id); }
export function cancelCustomKeyEdit(id) { cancelKeyEdit(id); }
function showProviderSave(id, text, tone = 'success') { const message = $(`save-msg-${id}`); if (!message) return; message.textContent = text; message.classList.toggle('error-text', tone === 'error'); message.classList.toggle('warning-text', tone === 'warning'); message.classList.add('show'); }
function verificationMessage(result, action = 'save') { const saved = action === 'save'; if (result.status === 'healthy' && result.models_discovered > 0) return {text: `${saved ? 'Saved' : 'Test passed'} - ${result.models_discovered} models discovered`, tone: 'success'}; if (result.status === 'healthy' && result.models_discovered === 0) return {text: 'Provider connected, but no models were discovered.', tone: 'warning'}; if (result.status === 'unavailable') return {text: `${saved ? 'Key saved, but the provider could not be verified' : 'Connection test failed'}${result.failure_reason ? ` (${result.failure_reason})` : ''}. ${result.failure_message || 'Check the key and try again.'}`, tone: 'error'}; if (result.status === 'unconfigured') return {text: saved ? 'Key was not saved or the provider is not configured.' : 'Connection test could not run because the provider is not configured.', tone: 'warning'}; return {text: result.failure_message || `Provider status: ${result.status}`, tone: 'warning'}; }
export async function saveProvider(id) { const button=$(`save-btn-${id}`), key=$(`key-input-${id}`), priority=Number.parseInt($(`prio-${id}`)?.value,10); button.classList.add('btn-loading'); try { const result=await api('/api/providers/config',{method:'POST',body:JSON.stringify({provider:id,base_url:$(`url-${id}`)?.value||null,default_model:$(`model-${id}`)?.value?.trim()||null,routing_priority:Number.isNaN(priority)?null:priority,enabled:$(`toggle-${id}`)?.checked??null,supports_vision:$(`vision-${id}`)?.checked??null,api_key:key?.value?.trim()||null})}); await renderProviders(); const message=verificationMessage(result); showProviderSave(id,message.text,message.tone); button.disabled=true; if(key){key.value='';cancelKeyEdit(id);} } catch(error){showProviderSave(id,userErrorMessage(error),'error');} finally{button.classList.remove('btn-loading');} }
export async function testProvider(id, button = null) { if (button) button.classList.add('btn-loading'); try { const result = await api(`/api/providers/${id}/test`, {method:'POST'}); const provider = {provider:id, key_set:result.status !== 'unconfigured', health_status:result.status}; providerHealthCache.set(id, result.status); updateHealthIndicator(id, provider, result.status, result.models_discovered); const message = verificationMessage(result, 'test'); showProviderSave(id, message.text,message.tone); } catch (error) { providerHealthCache.set(id, 'unavailable'); updateHealthIndicator(id, {provider:id, key_set:true}, 'unavailable'); showProviderSave(id, userErrorMessage(error), 'error'); } finally { if (button) button.classList.remove('btn-loading'); } }

export async function refreshProviderHealth(id, custom = false, local = false, isRuntime = false, button = null) {
  if (button) { button.classList.add('is-loading'); button.disabled = true; }
  try {
    if (local) {
      const providers = await api('/api/providers');
      const provider = providers.find(item => item.provider === 'local') || {provider:'local'};
      updateHealthIndicator(id, provider, healthDotState(provider), provider.runtime_status?.loaded ? 1 : 0);
    } else if (custom) {
      await testCustomProvider(id, isRuntime);
    } else {
      await testProvider(id);
    }
  } finally {
    if (button) { button.classList.remove('is-loading'); button.disabled = false; }
  }
}

exposeHandlers({analyzeProviderSource,saveCustomProvider,saveCustomProviderCard,importProviderJson,toggleAddProviderForm,toggleCustomProvider,testCustomProvider,trustCustomProvider,removeCustomProvider,loadRuntimeSource,exportCustomProvider,testProvider,refreshProviderHealth,markProviderDirty,toggleKeyEdit,cancelKeyEdit,toggleCustomKeyEdit,cancelCustomKeyEdit,saveProvider});

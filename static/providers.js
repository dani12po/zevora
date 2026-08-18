import {$, api, badge, emptyState, escapeHtml, exposeHandlers, pageWrap, setPanel, userErrorMessage} from './core.js?v=20260818-8';

const LABELS = {local:'Zevora Local AI',openai:'OpenAI',xai:'xAI (Grok)',nvidia:'NVIDIA NIM',deepseek:'DeepSeek',gemini:'Google Gemini',anthropic:'Anthropic'};
const DESCRIPTIONS = {
  local:'Private on-device GGUF runtime - llama.cpp - no API key required',
  openai:'GPT-4o family - OpenAI-compatible API', xai:'Grok family - xAI API',
  nvidia:'NIM inference - NVIDIA API', deepseek:'DeepSeek family - reasoning-capable',
  gemini:'Gemini family - Google AI', anthropic:'Claude family - Anthropic API',
};

function providerCard(provider, statusMap, modelCounts) {
  const health = statusMap[provider.provider] || (provider.provider === 'local' && provider.runtime_status?.configured ? 'healthy' : 'unconfigured');
  if (provider.provider === 'local') {
    const runtime = provider.runtime_status || {};
    const state = runtime.loaded ? 'loaded' : runtime.configured ? 'ready' : 'unavailable';
    const stateBadge = state === 'loaded' || state === 'ready' ? badge(`local ${state}`, 'green') : badge('local unavailable', 'red');
    return `<div class="card provider-shell"><div class="provider-card">
      <div class="provider-card-name">${LABELS.local} ${stateBadge}</div><div class="technical-text">${runtime.runtime || 'llamacpp'}</div>
      <div class="provider-description">${DESCRIPTIONS.local}</div><div class="card-grid provider-stats">
        <div class="card-sm card"><div class="card-lbl">Model</div><div class="card-val technical-text">${escapeHtml(runtime.model_id || provider.default_model || 'zevora')}</div></div>
        <div class="card-sm card"><div class="card-lbl">GGUF</div><div class="card-val">${runtime.model_exists ? `${runtime.model_size_mb} MB` : 'Missing'}</div></div>
        <div class="card-sm card"><div class="card-lbl">Context</div><div class="card-val">${runtime.context_length || '-'}</div></div>
        <div class="card-sm card"><div class="card-lbl">Process RSS</div><div class="card-val">${runtime.process_rss_mb ? `${runtime.process_rss_mb} MB` : '-'}</div></div>
        <div class="card-sm card"><div class="card-lbl">Load delta</div><div class="card-val">${runtime.load_delta_mb ? `${runtime.load_delta_mb} MB` : 'Not loaded'}</div></div>
      </div><div class="provider-path technical-text">${escapeHtml(runtime.model_path || '')}</div>
    </div></div>`;
  }
  const modelCount = modelCounts[provider.provider] || 0;
  const healthBadge = health === 'healthy' && modelCount > 0 ? badge('healthy','green') : !provider.key_set ? badge('not configured','grey') : health === 'healthy' ? badge('no models','yellow') : health === 'unavailable' ? badge('unavailable','red') : badge('not configured','grey');
  const id = escapeHtml(provider.provider);
  return `<div class="card provider-shell"><div class="provider-card">
    <div class="provider-card-name">${escapeHtml(LABELS[provider.provider] || provider.provider)} ${healthBadge}</div>
    <div class="provider-summary"><span>${modelCount} models</span><label class="toggle" title="Enabled"><input type="checkbox" id="toggle-${id}" ${provider.enabled ? 'checked' : ''} onchange="markProviderDirty('${id}')"><span class="toggle-slider"></span></label></div>
    <div class="provider-description">${escapeHtml(DESCRIPTIONS[provider.provider] || 'Custom OpenAI-compatible provider')}</div>
    <div class="provider-fields"><div class="provider-field"><label>API Key</label><span class="key-display" id="key-display-${id}">${provider.key_set ? `********${provider.key_masked.slice(-4)}` : 'Not set'}</span><button class="btn-sm" onclick="toggleKeyEdit('${id}')">Edit</button></div>
      <div class="provider-field" id="key-edit-${id}" style="display:none"><label>New key</label><input type="password" id="key-input-${id}" placeholder="sk-..." autocomplete="new-password"><button class="btn-sm" onclick="cancelKeyEdit('${id}')">Cancel</button></div>
      <div class="provider-field"><label>Base URL</label><input id="url-${id}" value="${escapeHtml(provider.base_url)}" oninput="markProviderDirty('${id}')"><span></span></div>
      <div class="provider-field"><label>Default Model</label><input id="model-${id}" value="${escapeHtml(provider.default_model || '')}" oninput="markProviderDirty('${id}')"><span></span></div>
      <div class="provider-field"><label>Image input</label><label class="toggle"><input type="checkbox" id="vision-${id}" ${provider.supports_vision ? 'checked' : ''} onchange="markProviderDirty('${id}')"><span class="toggle-slider"></span></label><span></span></div>
      <div class="provider-field"><label>Priority</label><input type="number" id="prio-${id}" value="${provider.routing_priority}" min="0" max="999" oninput="markProviderDirty('${id}')"><span></span></div>
    </div><div class="provider-save"><span class="save-msg" id="save-msg-${id}"></span><button class="btn-sm" onclick="testProvider('${id}', this)">Test connection</button><button class="btn-sm" id="save-btn-${id}" onclick="saveProvider('${id}')" disabled>Save</button></div>
  </div></div>`;
}

function customPanel(manifests) {
  const rows = (manifests.providers || []).map(provider => `<div class="custom-provider-row"><div><b>${escapeHtml(provider.name)}</b> ${badge(provider.state, provider.state === 'HEALTHY' || provider.state === 'TRUSTED_RUNTIME' ? 'green' : 'grey')}<p>${escapeHtml(provider.protocol)} - ${escapeHtml(provider.default_model || 'model unresolved')} - ${provider.credential.configured ? escapeHtml(provider.credential.masked) : 'credential not set'}</p></div><div class="provider-actions"><button class="btn-sm" onclick="testCustomProvider('${provider.provider_id}',${provider.protocol === 'custom-runtime'})">Test</button><button class="btn-sm" onclick="exportCustomProvider('${provider.provider_id}')">Export</button>${provider.protocol === 'custom-runtime' && !provider.runtime?.trusted ? `<button class="btn-sm" onclick="trustCustomProvider('${provider.provider_id}')">Trust</button>` : ''}<button class="btn-sm danger" onclick="removeCustomProvider('${provider.provider_id}')">Delete</button></div></div>`).join('') || '<p class="muted-copy">No user-defined providers.</p>';
  return `<section class="provider-manager"><div class="panel-toolbar"><div><h3>Bring your own AI</h3><p>Configure a compatible endpoint or statically inspect an example script.</p><p id="provider-message" class="inline-status" aria-live="polite"></p></div></div><div class="provider-form-grid">
    <label>ID<input id="custom-provider-id" placeholder="my-provider"></label><label>Name<input id="custom-provider-name" placeholder="My Provider"></label><label>Protocol<select id="custom-provider-protocol"><option>openai-compatible</option><option>anthropic-compatible</option><option>http-rest</option><option>local-openai-compatible</option><option>custom-runtime</option><option>unknown</option></select></label><label>Base URL<input id="custom-provider-url"></label><label>Default model<input id="custom-provider-model"></label><label>Credential environment<input id="custom-provider-env"></label><label>Credential value<input id="custom-provider-key" type="password" autocomplete="new-password"></label><label>Runtime language<select id="custom-provider-runtime"><option value="python">Python</option><option value="node">Node</option><option value="typescript">TypeScript</option><option value="shell">Shell</option></select></label>
    </div><label class="provider-source-label">Example or runtime source<textarea id="custom-provider-source" rows="8"></textarea></label><div class="provider-actions"><button class="btn-sm" onclick="analyzeProviderSource()">Analyze</button><button class="btn-sm" onclick="importProviderJson()">Import JSON</button><button class="btn-sm" onclick="saveCustomProvider()">Save provider</button></div><pre id="provider-analysis" class="analysis-preview hidden"></pre><div class="custom-provider-list">${rows}</div></section>`;
}

export async function renderProviders() {
  const [statuses, config, models, manifests] = await Promise.all([api('/api/providers'), api('/api/providers/config'), api('/api/models'), api('/api/provider-manifests').catch(() => ({providers:[]}))]);
  const counts = {}, statusMap = {};
  models.forEach(model => { counts[model.provider] = (counts[model.provider] || 0) + 1; });
  statuses.forEach(provider => { statusMap[provider.provider] = provider.health_status; });
  const cards = config.length ? config.map(provider => providerCard(provider, statusMap, counts)).join('') : emptyState('No providers', 'Provider config could not be loaded.', {kind:'cloud'});
  setPanel('Providers', pageWrap('<h2>Providers</h2>', customPanel(manifests) + cards));
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

function showProviderMessage(message, error = false) {
  const status = $('provider-message');
  if (!status) return;
  status.textContent = message;
  status.classList.toggle('error-text', error);
}

async function providerAction(action, success = '') {
  try {
    const result = await action();
    if (success) showProviderMessage(success);
    return result;
  } catch (error) {
    showProviderMessage(userErrorMessage(error), true);
    return null;
  }
}

function customProviderPayload() {
  const protocol = $('custom-provider-protocol').value, language = $('custom-provider-runtime').value;
  return {provider_id:$('custom-provider-id').value.trim().toLowerCase(),name:$('custom-provider-name').value.trim(),protocol,base_url:$('custom-provider-url').value.trim(),default_model:$('custom-provider-model').value.trim(),credential:{source:'environment',name:$('custom-provider-env').value.trim().toUpperCase()},enabled:true,routing_priority:50,capabilities:{chat:true,streaming:null,reasoning:null,vision:null,tool_calling:null},runtime:protocol === 'custom-runtime' ? {runtime:language,entrypoint:language === 'python' ? 'provider.py' : language === 'shell' ? 'provider.sh' : 'provider.js',trusted:false,permissions:{network:true,filesystem:'temporary',workspace:false,allowed_hosts:[]}} : null};
}

export async function saveCustomProvider() { const manifest=customProviderPayload(); await providerAction(async()=>{await api('/api/provider-manifests',{method:'POST',body:JSON.stringify({manifest,credential_value:$('custom-provider-key').value||null,script:manifest.runtime?$('custom-provider-source').value:null})});await renderProviders();showProviderMessage('Provider saved.');}); }
export async function importProviderJson() { let manifest; try { manifest=JSON.parse($('custom-provider-source').value.trim()); } catch (_) { showProviderMessage('Paste a valid provider manifest JSON document.',true); return; } await providerAction(async()=>{await api('/api/provider-manifests/import',{method:'POST',body:JSON.stringify({manifest,credential_value:$('custom-provider-key').value||null})});await renderProviders();showProviderMessage('Provider imported.');}); }
export async function testCustomProvider(id,isRuntime) { if (isRuntime && !confirm('Run this provider script once with its declared credential and permissions?')) return; await providerAction(async()=>{const result=await api(`/api/provider-manifests/${id}/${isRuntime?'runtime-test':'test'}`,{method:'POST',body:JSON.stringify({runtime_approved:isRuntime})});showProviderMessage(result.result?.success?'Connection succeeded':result.result?.message||'Connection failed',!result.result?.success);}); }
export async function trustCustomProvider(id) { if(confirm('Trust this runtime for future provider requests?')) await providerAction(async()=>{await api(`/api/provider-manifests/${id}/trust`,{method:'POST',body:JSON.stringify({approved:true})});await renderProviders();showProviderMessage('Provider runtime trusted.');}); }
export async function removeCustomProvider(id) { if(confirm(`Delete provider ${id} and its stored runtime source?`)) await providerAction(async()=>{await api(`/api/provider-manifests/${id}`,{method:'DELETE'});await renderProviders();showProviderMessage('Provider deleted.');}); }
export async function exportCustomProvider(id) { await providerAction(async()=>{const data=await api(`/api/provider-manifests/${id}/export`), blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'}), link=document.createElement('a'); link.href=URL.createObjectURL(blob); link.download=`${id}.provider.json`; link.click(); URL.revokeObjectURL(link.href);showProviderMessage('Provider exported.');}); }
export function markProviderDirty(id) { const button=$(`save-btn-${id}`); if(button) button.disabled=false; }
export function toggleKeyEdit(id) { $(`key-edit-${id}`).style.display='grid'; $(`key-display-${id}`).closest('.provider-field').style.display='none'; markProviderDirty(id); }
export function cancelKeyEdit(id) { $(`key-edit-${id}`).style.display='none'; $(`key-display-${id}`).closest('.provider-field').style.display='grid'; }
function showProviderSave(id, text, tone = 'success') {
  const message = $(`save-msg-${id}`);
  if (!message) return;
  message.textContent = text;
  message.classList.toggle('error-text', tone === 'error');
  message.classList.toggle('warning-text', tone === 'warning');
  message.classList.add('show');
}

function verificationMessage(result, action = 'save') {
  const saved = action === 'save';
  if (result.status === 'healthy' && result.models_discovered > 0) {
    return {text: `${saved ? 'Saved' : 'Test passed'} - ${result.models_discovered} models discovered`, tone: 'success'};
  }
  if (result.status === 'unavailable') {
    const detail = result.failure_reason ? ` (${result.failure_reason})` : '';
    const prefix = saved ? 'Key saved, but the provider could not be verified' : 'Connection test failed';
    return {text: `${prefix}${detail}. ${result.failure_message || 'Check the key and try again.'}`, tone: 'error'};
  }
  if (result.status === 'unconfigured') {
    return {text: saved ? 'Key was not saved or the provider is not configured.' : 'Connection test could not run because the provider is not configured.', tone: 'warning'};
  }
  if (result.status === 'healthy' && result.models_discovered === 0) {
    return {text: `Provider is healthy, but no usable models were discovered${result.failure_reason ? ` (${result.failure_reason})` : ''}.`, tone: 'warning'};
  }
  return {text: result.failure_message || `Provider status: ${result.status}`, tone: 'warning'};
}

export async function saveProvider(id) { const button=$(`save-btn-${id}`), key=$(`key-input-${id}`), priority=Number.parseInt($(`prio-${id}`)?.value,10); button.classList.add('btn-loading'); try { const result=await api('/api/providers/config',{method:'POST',body:JSON.stringify({provider:id,base_url:$(`url-${id}`)?.value||null,default_model:$(`model-${id}`)?.value?.trim()||null,routing_priority:Number.isNaN(priority)?null:priority,enabled:$(`toggle-${id}`)?.checked??null,supports_vision:$(`vision-${id}`)?.checked??null,api_key:key?.value?.trim()||null})}); await renderProviders(); const message=verificationMessage(result); showProviderSave(id,message.text,message.tone); button.disabled=true; if(key){key.value='';cancelKeyEdit(id);} } catch(error){showProviderSave(id,userErrorMessage(error),'error');} finally{button.classList.remove('btn-loading');} }

export async function testProvider(id, button = null) { if (button) button.classList.add('btn-loading'); try { const result = await api(`/api/providers/${id}/test`, {method:'POST'}); await renderProviders(); const message = verificationMessage(result, 'test'); showProviderSave(id, message.text, message.tone); } catch (error) { showProviderSave(id, userErrorMessage(error), 'error'); } finally { if (button) button.classList.remove('btn-loading'); } }

exposeHandlers({analyzeProviderSource,saveCustomProvider,importProviderJson,testCustomProvider,testProvider,trustCustomProvider,removeCustomProvider,exportCustomProvider,markProviderDirty,toggleKeyEdit,cancelKeyEdit,saveProvider});

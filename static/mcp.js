import {$, api, badge, escapeHtml, exposeHandlers, pageWrap, setPanel} from './core.js';

export async function renderMCP() {
  const tools = await api('/api/tools');
  const permissionColors = {auto:'green', approval:'yellow', deny:'red'};
  const rows = tools.map(tool => `<tr><td><code class="technical-text">${escapeHtml(tool.name)}</code></td><td>${badge(tool.permission, permissionColors[tool.permission] || 'grey')}</td><td><label class="toggle" title="Enable ${escapeHtml(tool.name)}"><input type="checkbox" ${tool.enabled ? 'checked' : ''} onchange="setMCPToolEnabled('${escapeHtml(tool.name)}',this)"><span class="toggle-slider"></span></label></td><td><span class="inline-status technical-text" id="mcp-status-${escapeHtml(tool.name)}">${tool.enabled ? 'Enabled' : 'Disabled'}</span></td></tr>`).join('');
  setPanel('MCP', pageWrap('<h2>MCP Tools</h2>', `<div class="card"><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Tool</th><th>Permission</th><th>Enabled</th><th>Status</th></tr></thead><tbody>${rows || '<tr><td colspan="4" class="table-empty">No tools registered</td></tr>'}</tbody></table></div></div>`));
}

export async function setMCPToolEnabled(tool, input) {
  const previous = !input.checked;
  const status = $(`mcp-status-${tool}`);
  input.disabled = true;
  if (status) status.textContent = 'Saving...';
  try {
    const updated = await api(`/api/tools/${encodeURIComponent(tool)}`, {method:'PUT', body:JSON.stringify({enabled:input.checked})});
    input.checked = updated.enabled;
    if (status) status.textContent = updated.enabled ? 'Enabled' : 'Disabled';
  } catch (error) {
    input.checked = previous;
    if (status) status.textContent = error.message || 'Update failed';
  } finally {
    input.disabled = false;
  }
}

exposeHandlers({setMCPToolEnabled});

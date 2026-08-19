import {$, api} from './core.js?v=20260818-11';

const tabs = new Map();
let activeTabId = null;
let tabSequence = 0;

function activeTab() { return tabs.get(activeTabId) || null; }
function outputNode() { return $('workspace-terminal-output'); }

function commandTitle(command) {
  const first = command.trim().split(/\s+/, 1)[0] || 'Terminal';
  return first.length > 18 ? `${first.slice(0, 17)}...` : first;
}

function createTab() {
  const id = `local-${++tabSequence}`;
  tabs.set(id, {id, title:'Terminal', sessionId:null, cursor:0, status:'idle', output:[], timer:null});
  activateTab(id);
}

function renderTabs() {
  const host = $('workspace-terminal-tabs');
  if (!host) return;
  host.innerHTML = '';
  for (const tab of tabs.values()) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = `terminal-tab${tab.id === activeTabId ? ' active' : ''}`;
    button.textContent = tab.title; button.title = tab.title;
    button.onclick = () => activateTab(tab.id);
    host.append(button);
  }
}

function renderActiveOutput() {
  const tab = activeTab();
  const output = outputNode();
  if (!tab || !output) return;
  output.innerHTML = '';
  if (!tab.output.length) output.innerHTML = '<span class="muted-copy">Terminal ready for the selected workspace.</span>';
  for (const event of tab.output) {
    const node = document.createElement(event.type === 'status' ? 'div' : 'span');
    node.className = event.type === 'status' ? 'terminal-status' : `terminal-output-${event.stream || 'system'}`;
    node.textContent = event.data || '';
    output.append(node);
  }
  output.scrollTop = output.scrollHeight;
  syncControls();
}

function activateTab(id) {
  if (!tabs.has(id)) return;
  activeTabId = id;
  renderTabs(); renderActiveOutput();
  $('workspace-terminal-command')?.focus();
}

function appendEvent(tab, event) {
  tab.output.push(event);
  if (tab.output.length > 1000) tab.output.splice(0, tab.output.length - 1000);
  if (tab.id === activeTabId) renderActiveOutput();
}

function setStatus(tab, text) { appendEvent(tab, {type:'status', data:text}); }

function syncControls() {
  const tab = activeTab();
  const running = tab?.status === 'running';
  $('workspace-terminal-kill')?.classList.toggle('hidden', !running);
  const input = $('workspace-terminal-command');
  if (input) input.disabled = running;
}

async function pollSession(tabId) {
  const tab = tabs.get(tabId);
  if (!tab?.sessionId || tab.status !== 'running') return;
  try {
    const data = await api(`/api/terminal/sessions/${encodeURIComponent(tab.sessionId)}?after=${tab.cursor}`);
    for (const event of data.events || []) if (event.type === 'output') appendEvent(tab, event);
    tab.cursor = data.next || tab.cursor;
    if (data.status !== 'running') {
      tab.status = data.status;
      setStatus(tab, `Command ${data.status}${data.exit_code == null ? '' : ` (exit ${data.exit_code})`}`);
      syncControls(); renderTabs();
      return;
    }
    tab.timer = window.setTimeout(() => pollSession(tabId), 250);
  } catch (error) {
    tab.status = 'failed';
    setStatus(tab, `Terminal error: ${error.message}`);
    syncControls();
  }
}

async function runCommand(event) {
  event.preventDefault();
  const tab = activeTab();
  const projectId = $('project-select')?.value;
  const input = $('workspace-terminal-command');
  const command = input?.value.trim();
  if (!tab || tab.status === 'running') return;
  if (!projectId || !command) {
    setStatus(tab, projectId ? 'Enter a command.' : 'Open a project before running commands.');
    return;
  }
  tab.output = []; tab.title = commandTitle(command); renderTabs();
  try {
    const data = await api('/api/terminal/sessions', {
      method:'POST', body:JSON.stringify({project_id:Number(projectId), command}),
    });
    tab.sessionId = data.session_id; tab.cursor = 0; tab.status = 'running';
    appendEvent(tab, {type:'output', stream:'command', data:`> ${command}\n`});
    input.value = ''; syncControls(); pollSession(tab.id);
  } catch (error) {
    tab.status = 'failed';
    setStatus(tab, `Command rejected: ${error.message}`);
  }
}

async function killCommand() {
  const tab = activeTab();
  if (!tab?.sessionId || tab.status !== 'running') return;
  try { await api(`/api/terminal/sessions/${encodeURIComponent(tab.sessionId)}/kill`, {method:'POST'}); }
  catch (error) { setStatus(tab, `Unable to stop command: ${error.message}`); }
}

async function clearTerminal() {
  const tab = activeTab();
  if (!tab) return;
  if (tab.timer) window.clearTimeout(tab.timer);
  tab.timer = null;
  tab.output = [{type:'status', data:'Terminal cleared.'}];
  if (tab.status !== 'running') {
    if (tab.sessionId) await api(`/api/terminal/sessions/${encodeURIComponent(tab.sessionId)}`, {method:'DELETE'}).catch(() => {});
    tab.sessionId = null; tab.cursor = 0; tab.status = 'idle'; tab.title = 'Terminal';
  }
  renderTabs(); renderActiveOutput();
  if (tab.status === 'running') { tab.timer = window.setTimeout(() => pollSession(tab.id), 250); }
}

export function initTerminalWorkspace() {
  createTab();
  $('workspace-terminal-new')?.addEventListener('click', createTab);
  $('workspace-terminal-form')?.addEventListener('submit', runCommand);
  $('workspace-terminal-kill')?.addEventListener('click', killCommand);
  $('workspace-terminal-clear')?.addEventListener('click', clearTerminal);
}

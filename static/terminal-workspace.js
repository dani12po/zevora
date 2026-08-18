import {$, api, state} from './core.js?v=20260818-11';

let activeSession = null;
let pollTimer = null;
let eventCursor = 0;

function outputNode() {
  return $('workspace-terminal-output');
}

function appendOutput(event) {
  const output = outputNode();
  if (!output || event.type !== 'output') return;
  const line = document.createElement('span');
  line.className = `terminal-output-${event.stream || 'system'}`;
  line.textContent = event.data || '';
  output.append(line);
  output.scrollTop = output.scrollHeight;
}

function setStatus(text) {
  const output = outputNode();
  if (!output) return;
  const status = document.createElement('div');
  status.className = 'terminal-status';
  status.textContent = text;
  output.append(status);
  output.scrollTop = output.scrollHeight;
}

function setRunning(running) {
  $('workspace-terminal-kill')?.classList.toggle('hidden', !running);
  const input = $('workspace-terminal-command');
  if (input) input.disabled = running;
}

async function pollSession() {
  if (!activeSession) return;
  try {
    const data = await api(`/api/terminal/sessions/${encodeURIComponent(activeSession)}?after=${eventCursor}`);
    for (const event of data.events || []) appendOutput(event);
    eventCursor = data.next || eventCursor;
    if (data.status !== 'running') {
      setRunning(false);
      setStatus(`Command ${data.status}${data.exit_code == null ? '' : ` (exit ${data.exit_code})`}`);
      activeSession = null;
      return;
    }
    pollTimer = window.setTimeout(pollSession, 250);
  } catch (error) {
    setRunning(false);
    setStatus(`Terminal error: ${error.message}`);
    activeSession = null;
  }
}

async function runCommand(event) {
  event.preventDefault();
  if (activeSession) return;
  const projectId = $('project-select')?.value;
  const input = $('workspace-terminal-command');
  const command = input?.value.trim();
  if (!projectId || !command) {
    setStatus(projectId ? 'Enter a command.' : 'Open a project before running commands.');
    return;
  }
  const output = outputNode();
  if (output) output.innerHTML = '';
  try {
    const data = await api('/api/terminal/sessions', {
      method: 'POST',
      body: JSON.stringify({project_id: Number(projectId), command}),
    });
    activeSession = data.session_id;
    eventCursor = 0;
    setRunning(true);
    appendOutput({type: 'output', stream: 'command', data: `> ${command}\n`});
    input.value = '';
    pollSession();
  } catch (error) {
    setRunning(false);
    setStatus(`Command rejected: ${error.message}`);
  }
}

async function killCommand() {
  if (!activeSession) return;
  try {
    await api(`/api/terminal/sessions/${encodeURIComponent(activeSession)}/kill`, {method: 'POST'});
  } catch (error) {
    setStatus(`Unable to stop command: ${error.message}`);
  }
}

function clearTerminal() {
  if (pollTimer) window.clearTimeout(pollTimer);
  pollTimer = null;
  activeSession = null;
  eventCursor = 0;
  setRunning(false);
  const output = outputNode();
  if (output) output.innerHTML = '<span class="muted-copy">Terminal cleared.</span>';
}

export function initTerminalWorkspace() {
  $('workspace-terminal-form')?.addEventListener('submit', runCommand);
  $('workspace-terminal-kill')?.addEventListener('click', killCommand);
  $('workspace-terminal-clear')?.addEventListener('click', clearTerminal);
}

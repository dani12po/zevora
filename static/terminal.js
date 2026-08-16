import {$, badge, exposeHandlers, pageWrap, setPanel, state} from './core.js';

let openChatPage = async () => {};

export function configureTerminal({navigateToChat}) {
  openChatPage = navigateToChat;
}

export function renderTerminal() {
  const projectReady = Boolean($('project-select').value);
  setPanel('Terminal', pageWrap(`<h2>Scoped Terminal</h2>${badge('approval required','yellow')}`, `<div class="card terminal-tool">
    <p>Commands run without a shell inside the selected project. Only bounded test and syntax-check commands accepted by the backend allowlist can run.</p>
    <label>Command<input id="terminal-command" class="technical-text" value="python -m pytest -q" ${projectReady ? '' : 'disabled'}></label>
    <label>Purpose<input id="terminal-purpose" value="Run the project test suite" ${projectReady ? '' : 'disabled'}></label>
    <button class="btn-sm" id="queue-terminal" ${projectReady ? '' : 'disabled'} onclick="queueTerminalAction()">Add to chat for approval</button>
    <span id="terminal-msg" class="inline-status">${projectReady ? 'The action will not run until confirmed in chat.' : 'Select a project first.'}</span>
  </div>`));
}

export async function queueTerminalAction() {
  const command = $('terminal-command').value.trim();
  if (!command) return;
  state.pendingActions.push({tool:'execute_command', arguments:{command}, approved:false, purpose:$('terminal-purpose').value.trim()});
  await openChatPage();
  $('route-status').textContent = 'Terminal action queued - send a prompt to request approval';
}

exposeHandlers({queueTerminalAction});

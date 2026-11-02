import {$, exposeHandlers, state} from './core.js?v=20260819-3';
import {focusWorkspaceTerminal} from './workspace.js?v=20260819-3';

let openChatPage = async () => {};

export function configureTerminal({navigateToChat}) {
  openChatPage = navigateToChat;
}

export function renderTerminal() {
  focusWorkspaceTerminal();
}

export async function queueTerminalAction() {
  const command = $('terminal-command').value.trim();
  if (!command) return;
  state.pendingActions.push({tool:'execute_command', arguments:{command}, approved:false, purpose:$('terminal-purpose').value.trim()});
  await openChatPage();
  $('route-status').textContent = 'Terminal action queued - send a prompt to request approval';
}

exposeHandlers({queueTerminalAction});

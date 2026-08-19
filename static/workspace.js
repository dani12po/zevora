import {$, state} from './core.js?v=20260819-2';

const KEYS = {
  chatWidth: 'zevora.workspace.chatWidth',
  terminalHeight: 'zevora.workspace.terminalHeight',
  chatOpen: 'zevora.workspace.chatOpen',
  terminalOpen: 'zevora.workspace.terminalOpen',
  sidebarCollapsed: 'zevora.sidebar.autoCollapsed',
};

function numberSetting(key, fallback, min, max) {
  const value = Number(localStorage.getItem(key));
  return Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : fallback;
}

function mountChat(target) {
  const messages = $('messages');
  const composer = $('composer');
  if (messages && messages.parentElement !== target) target.append(messages);
  if (composer && composer.parentElement !== target) target.append(composer);
}

function setWorkspaceVisible(active) {
  const workspace = $('coding-workspace');
  const mainHost = $('main-chat-host');
  const dock = $('chat-dock-content');
  if (!workspace || !mainHost || !dock) return;
  workspace.classList.toggle('hidden', !active);
  document.body.classList.toggle('coding-workspace-active', active);
  if (active) {
    mountChat(dock);
    mainHost.classList.add('hidden');
  } else {
    mountChat(mainHost);
    mainHost.classList.remove('hidden');
  }
  state.codingWorkspaceActive = active;
  localStorage.setItem('zevora.workspace.active', String(active));
}

function setChatOpen(open) {
  const dock = $('chat-dock');
  const openButton = $('chat-dock-open');
  if (!dock || !openButton) return;
  dock.classList.toggle('is-collapsed', !open);
  openButton.classList.toggle('hidden', open);
  localStorage.setItem(KEYS.chatOpen, String(open));
}

function setTerminalOpen(open) {
  const terminal = $('workspace-terminal');
  const toggle = $('workspace-terminal-toggle');
  const indicator = $('workspace-terminal-collapsed-indicator');
  if (!terminal) return;
  terminal.classList.toggle('is-collapsed', !open);
  if (toggle) {
    toggle.textContent = open ? '⌄' : '⌃';
    toggle.title = open ? 'Collapse terminal' : 'Expand terminal';
    toggle.setAttribute('aria-label', open ? 'Collapse terminal' : 'Expand terminal');
    toggle.setAttribute('aria-expanded', String(open));
  }
  if (indicator) indicator.classList.toggle('hidden', open);
  localStorage.setItem(KEYS.terminalOpen, String(open));
}

function resizeFromPointer(event, kind) {
  const workspace = $('coding-workspace');
  if (!workspace) return;
  const onMove = move => {
    if (kind === 'chat') {
      const width = Math.min(620, Math.max(280, window.innerWidth - move.clientX));
      workspace.style.setProperty('--chat-width', `${width}px`);
      localStorage.setItem(KEYS.chatWidth, String(width));
    } else {
      const height = Math.min(520, Math.max(140, window.innerHeight - move.clientY));
      workspace.style.setProperty('--terminal-height', `${height}px`);
      localStorage.setItem(KEYS.terminalHeight, String(height));
    }
  };
  const stop = () => {
    document.removeEventListener('pointermove', onMove);
    document.removeEventListener('pointerup', stop);
  };
  document.addEventListener('pointermove', onMove);
  document.addEventListener('pointerup', stop, {once: true});
  onMove(event);
}

export function enterCodingWorkspace() {
  setWorkspaceVisible(true);
  setChatOpen(localStorage.getItem(KEYS.chatOpen) !== 'false');
  setTerminalOpen(localStorage.getItem(KEYS.terminalOpen) !== 'false');
}

export function leaveCodingWorkspace() {
  setWorkspaceVisible(false);
}

export function initWorkspaceShell() {
  const workspace = $('coding-workspace');
  if (!workspace) return;
  workspace.style.setProperty('--chat-width', `${numberSetting(KEYS.chatWidth, 360, 280, 620)}px`);
  workspace.style.setProperty('--terminal-height', `${numberSetting(KEYS.terminalHeight, 220, 140, 520)}px`);
  $('chat-dock-toggle')?.addEventListener('click', () => setChatOpen(false));
  $('chat-dock-open')?.addEventListener('click', () => setChatOpen(true));
  $('workspace-terminal-toggle')?.addEventListener('click', () => {
    setTerminalOpen($('workspace-terminal')?.classList.contains('is-collapsed'));
  });
  $('workspace-terminal-collapsed-indicator')?.addEventListener('click', () => setTerminalOpen(true));
  $('chat-dock-resizer')?.addEventListener('pointerdown', event => resizeFromPointer(event, 'chat'));
  $('workspace-terminal-resizer')?.addEventListener('pointerdown', event => resizeFromPointer(event, 'terminal'));
  $('workspace-sidebar-toggle')?.addEventListener('click', () => {
    const collapsed = document.body.classList.toggle('sidebar-collapsed');
    localStorage.setItem(KEYS.sidebarCollapsed, String(collapsed));
  });
  if (localStorage.getItem(KEYS.sidebarCollapsed) === 'true') document.body.classList.add('sidebar-collapsed');
  if (localStorage.getItem('zevora.workspace.active') === 'true') enterCodingWorkspace();
  else leaveCodingWorkspace();
}

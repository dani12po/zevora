import {$, state} from './core.js?v=20260819-3';

export const WORKSPACE_ROUTES = new Set(['/filesystem', '/terminal']);
const KEYS = {
  chatWidth: 'zevora.workspace.chatWidth', terminalHeight: 'zevora.workspace.terminalHeight',
  chatOpen: 'zevora.workspace.chatOpen', terminalOpen: 'zevora.workspace.terminalOpen',
};

function numberSetting(key, fallback, min, max) {
  const raw = localStorage.getItem(key);
  if (raw === null) return fallback;
  const value = Number(raw);
  return Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : fallback;
}

function chatSurface() {
  const surface = $('chat-surface');
  if (!surface) return null;
  // The markup predates the canonical host. Move the existing, unique nodes
  // into it once; subsequent layout changes move this single surface only.
  for (const id of ['messages', 'audit-result', 'composer']) {
    const node = $(id);
    if (node && node.parentElement !== surface) surface.append(node);
  }
  return surface;
}

export function mountChatSurface(target) {
  const surface = chatSurface();
  if (surface && target && surface.parentElement !== target) target.append(surface);
}

function setSidebarCollapsed(collapsed, {userOverride = false} = {}) {
  document.body.classList.toggle('sidebar-collapsed', collapsed);
  $('sidebar')?.setAttribute('aria-hidden', String(collapsed));
  $('workspace-sidebar-toggle')?.setAttribute('aria-expanded', String(!collapsed));
  if (userOverride && state.workspaceMode) state.workspaceSidebarUserOverride = true;
}

function setWorkspaceVisible(active) {
  const workspace = $('coding-workspace');
  const mainHost = $('main-chat-host');
  const dock = $('chat-dock-content');
  if (!workspace || !mainHost || !dock) return;
  workspace.classList.toggle('hidden', !active);
  mainHost.classList.toggle('hidden', active);
  document.body.classList.toggle('workspace-mode', active);
  document.body.classList.toggle('coding-workspace-active', active);
  workspace.setAttribute('aria-hidden', String(!active));
  state.workspaceMode = active;
  state.codingWorkspaceActive = active;
  mountChatSurface(active ? dock : mainHost);
}

function setChatOpen(open) {
  const dock = $('chat-dock');
  const content = $('chat-dock-content');
  const openButton = $('chat-dock-open');
  if (!dock || !content || !openButton) return;
  dock.classList.toggle('is-collapsed', !open);
  $('coding-workspace')?.classList.toggle('chat-dock-collapsed', !open);
  document.body.classList.toggle('chat-dock-collapsed', !open);
  content.setAttribute('aria-hidden', String(!open));
  openButton.classList.toggle('hidden', open);
  $('chat-dock-toggle')?.setAttribute('aria-expanded', String(open));
  localStorage.setItem(KEYS.chatOpen, String(open));
}

export function ensureWorkspaceChatOpen() { if (state.workspaceMode) setChatOpen(true); }

function setTerminalOpen(open) {
  const terminal = $('workspace-terminal');
  const toggle = $('workspace-terminal-toggle');
  if (!terminal) return;
  terminal.classList.toggle('is-collapsed', !open);
  document.body.classList.toggle('terminal-collapsed', !open);
  if (toggle) {
    toggle.textContent = open ? '⌄' : '⌃';
    toggle.title = open ? 'Collapse terminal' : 'Expand terminal';
    toggle.setAttribute('aria-label', open ? 'Collapse terminal' : 'Expand terminal');
    toggle.setAttribute('aria-expanded', String(open));
  }
  $('workspace-terminal-collapsed-indicator')?.classList.toggle('hidden', open);
  localStorage.setItem(KEYS.terminalOpen, String(open));
}

export function focusWorkspaceTerminal() {
  setTerminalOpen(true);
  $('workspace-terminal-command')?.focus();
}

function resizeFromPointer(event, kind) {
  const workspace = $('coding-workspace');
  if (!workspace) return;
  event.preventDefault();
  const onMove = move => {
    if (kind === 'chat') {
      const max = Math.floor(window.innerWidth * .5);
      const width = Math.min(max, Math.max(320, window.innerWidth - move.clientX));
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
  document.addEventListener('pointerup', stop, {once:true});
  onMove(event);
}

export function enterWorkspaceMode() {
  const entering = !state.workspaceMode;
  if (entering) {
    state.sidebarBeforeWorkspace = document.body.classList.contains('sidebar-collapsed');
    state.workspaceSidebarUserOverride = false;
  }
  setWorkspaceVisible(true);
  if (entering) setSidebarCollapsed(true);
  setChatOpen(localStorage.getItem(KEYS.chatOpen) !== 'false');
  setTerminalOpen(localStorage.getItem(KEYS.terminalOpen) !== 'false');
}

export function leaveWorkspaceMode() {
  if (!state.workspaceMode) return;
  setWorkspaceVisible(false);
  setSidebarCollapsed(Boolean(state.sidebarBeforeWorkspace));
  state.workspaceSidebarUserOverride = false;
}

export function syncWorkspaceLayout(path) {
  if (WORKSPACE_ROUTES.has(path)) enterWorkspaceMode();
  else leaveWorkspaceMode();
}

export const enterCodingWorkspace = enterWorkspaceMode;
export const leaveCodingWorkspace = leaveWorkspaceMode;

export function initWorkspaceShell({openFullChat} = {}) {
  const workspace = $('coding-workspace');
  if (!workspace) return;
  chatSurface();
  workspace.style.setProperty('--chat-width', `${numberSetting(KEYS.chatWidth, 440, 320, Math.floor(window.innerWidth * .5))}px`);
  workspace.style.setProperty('--terminal-height', `${numberSetting(KEYS.terminalHeight, 220, 140, 520)}px`);
  $('chat-dock-toggle')?.addEventListener('click', () => setChatOpen(false));
  $('chat-dock-open')?.addEventListener('click', () => setChatOpen(true));
  $('workspace-open-full-chat')?.addEventListener('click', () => openFullChat?.());
  $('workspace-terminal-toggle')?.addEventListener('click', () => setTerminalOpen($('workspace-terminal')?.classList.contains('is-collapsed')));
  $('workspace-terminal-collapsed-indicator')?.addEventListener('click', () => setTerminalOpen(true));
  $('chat-dock-resizer')?.addEventListener('pointerdown', event => resizeFromPointer(event, 'chat'));
  $('workspace-terminal-resizer')?.addEventListener('pointerdown', event => resizeFromPointer(event, 'terminal'));
  $('workspace-sidebar-toggle')?.addEventListener('click', () => setSidebarCollapsed(!document.body.classList.contains('sidebar-collapsed'), {userOverride:true}));
  setWorkspaceVisible(false);
}

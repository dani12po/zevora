export const $ = id => document.getElementById(id);

export const state = {
  activeChat: null,
  isSending: false,
  gatewayReady: false,
  pendingAttachments: [],
  pendingActions: [],
  pendingApprovalRequest: null,
  fsProjectId: null,
};

const gatewayBase = window.ZEVORA_GATEWAY_URL || window.location.origin;
const routes = new Map();
const navByPath = {
  '/providers': 'nav-providers',
  '/local-ai': 'nav-local-ai',
  '/model-router': 'nav-model-router',
  '/mcp': 'nav-mcp',
  '/terminal': 'nav-terminal',
  '/filesystem': 'nav-filesystem',
  '/memory': 'nav-memory',
  '/cache': 'nav-cache',
  '/usage': 'nav-usage',
  '/docs': 'nav-docs',
  '/settings': 'nav-settings',
};

export async function api(path, options = {}) {
  const controller = new AbortController();
  const timeoutMs = path === '/health' ? 3000 : path === '/api/chat' ? 75000 : 15000;
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(gatewayBase + path, {
      ...options,
      headers: {'Content-Type': 'application/json', ...(options.headers || {})},
      signal: controller.signal,
    });
    const data = await response.json().catch(() => ({error: {message: `HTTP ${response.status}`}}));
    if (!response.ok) {
      const payload = data.detail || data.error || {};
      const normalized = typeof payload === 'object' ? payload : {message: String(payload)};
      const error = new Error(normalized.message || 'Gateway request failed');
      Object.assign(error, normalized);
      throw error;
    }
    return data;
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error(`Gateway request timed out after ${Math.round(timeoutMs / 1000)} seconds`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

const ERROR_MESSAGES = {
  AGENT_LOOP_LIMIT: 'Planning could not reach a stable result. Refine the request or try again.',
  INTERNAL_ERROR: 'ZEVORA encountered an unexpected problem. Retry the request; restart the gateway if it continues.',
  INVALID_ATTACHMENT: 'One or more attachments could not be read. Check the file type and size, then attach them again.',
  INVALID_ROUTING_OVERRIDE: 'The selected routing option is incomplete. Choose Auto or select the required provider and model.',
  MCP_TOOL_NOT_FOUND: 'That tool is no longer available. Refresh the tools page and choose an installed tool.',
  PROJECT_NOT_FOUND: 'The selected project is no longer available. Open the project folder again.',
  PROJECT_NOT_REGISTERED: 'Open this project in ZEVORA before indexing it.',
  PROJECT_PATH_INVALID: 'The project folder cannot be accessed. Check that it still exists and is permitted.',
  PROVIDER_CONFIGURATION_INVALID: 'The provider configuration is invalid. Review its endpoint, model, credentials, and runtime settings.',
  PROVIDER_NOT_FOUND: 'That provider is no longer available. Refresh the page and select a configured provider.',
  PROVIDER_RUNTIME_APPROVAL_REQUIRED: 'Approve this custom provider runtime before running it.',
  ROUTING_OVERRIDE_UNAVAILABLE: 'The selected provider or model is unavailable. Choose another option or use Auto routing.',
  SETTINGS_WRITE_FAILED: 'Settings could not be saved. Check file permissions and try again.',
  SHUTDOWN_FORBIDDEN: 'Only the ZEVORA gateway controller can stop this process.',
  UNINSTALL_PATH_REJECTED: 'Local Intelligence was not removed because its installation path is unsafe or invalid.',
  VALIDATION_ERROR: 'Some request details are invalid. Review the highlighted values and try again.',
  PICKER_UNAVAILABLE: 'The native folder picker is unavailable. Enter the project folder path manually.',
};

export function userErrorMessage(error, fallback = 'The request could not be completed.') {
  return ERROR_MESSAGES[error?.code] || error?.message || fallback;
}

export function escapeHtml(value) {
  const node = document.createElement('div');
  node.textContent = value ?? '';
  return node.innerHTML;
}

export function fmtBytes(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let index = 0;
  while (bytes >= 1024 && index < units.length - 1) {
    bytes /= 1024;
    index += 1;
  }
  return `${bytes.toFixed(index ? 1 : 0)} ${units[index]}`;
}

export function badge(label, color) {
  return `<span class="badge badge-${color}">${escapeHtml(label)}</span>`;
}

export function pageWrap(headerHtml, bodyHtml, description = '') {
  const copy = description ? `<p>${escapeHtml(description)}</p>` : '';
  return `<div class="page"><div class="page-header"><div class="page-heading">${headerHtml}${copy}</div></div>${bodyHtml}</div>`;
}

export function stateIndicator(kind = 'local', label) {
  const text = label || (kind === 'cloud' ? 'Cloud provider' : 'Local workspace');
  return `<span class="state-indicator state-indicator-${kind}" aria-label="${escapeHtml(text)}"><span></span>${escapeHtml(text)}</span>`;
}

export function emptyState(title, message, {kind = 'local', actions = ''} = {}) {
  return `<div class="empty empty-state-compact">${stateIndicator(kind)}<b>${escapeHtml(title)}</b><p>${escapeHtml(message)}</p>${actions}</div>`;
}

export function loadingState(message, kind = 'local') {
  return `<div class="loading-state">${stateIndicator(kind, kind === 'cloud' ? 'Contacting cloud' : 'Loading locally')}<span>${escapeHtml(message)}</span></div>`;
}

function replaceMessages(html) {
  const host = $('messages');
  host.classList.remove('route-enter');
  host.innerHTML = html;
  requestAnimationFrame(() => host.classList.add('route-enter'));
}

export function setPanel(title, html) {
  $('chat-title').textContent = 'Workspace';
  $('project-label').textContent = title;
  replaceMessages(`<section class="panel-content">${html}</section>`);
  $('composer').classList.add('hidden');
}

export function setMessages(html) {
  replaceMessages(html);
}

export function registerRoutes(routeMap) {
  Object.entries(routeMap).forEach(([path, handler]) => routes.set(path, handler));
}

function setActiveNav(path) {
  document.querySelectorAll('.nav-item').forEach(node => node.classList.remove('active'));
  const node = $(navByPath[path]);
  if (node) node.classList.add('active');
}

export async function render(path) {
  const normalized = routes.has(path) ? path : '/';
  setActiveNav(normalized);
  try {
    await routes.get(normalized)?.();
  } catch (error) {
    setPanel(normalized.slice(1) || 'chat', `<div class="card"><b class="error-text">Unable to load this page</b><p class="muted-copy">${escapeHtml(userErrorMessage(error))}</p></div>`);
  }
}

export async function navigate(path, {replace = false} = {}) {
  if (replace) history.replaceState({path}, '', path);
  else history.pushState({path}, '', path);
  await render(path);
}

export function setSidebarOpen(open) {
  document.body.classList.toggle('sidebar-open', open);
  $('mobile-menu').setAttribute('aria-expanded', String(open));
}

export function exposeHandlers(handlers) {
  Object.assign(window, handlers);
}

window.addEventListener('popstate', () => render(location.pathname));

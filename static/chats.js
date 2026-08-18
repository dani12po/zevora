import {$, api, escapeHtml, exposeHandlers, loadingState, navigate, pageWrap, setMessages, setPanel, setSidebarOpen, state, userErrorMessage} from './core.js?v=20260818-7';
import {renderMarkdown} from './markdown.js?v=20260818-7';

let renamingChatId = null;
let regenerateMessage = null;

export function configureMessageActions(actions = {}) {
  regenerateMessage = actions.regenerate || null;
}

export async function refreshSidebarChats() {
  const chats = await api('/api/chats?limit=5');
  const list = $('chat-list');
  list.innerHTML = chats.length ? '' : '<div class="sidebar-empty">No chats yet</div>';
  chats.forEach(chat => {
    const button = document.createElement('button');
    button.className = `chat-item${chat.id === state.activeChat ? ' active' : ''}`;
    button.innerHTML = `<span class="chat-item-title">${escapeHtml(chat.title)}</span>`;
    button.onclick = async () => {
      setSidebarOpen(false);
      await openChat(chat.id);
    };
    list.append(button);
  });
}

const FAILURE_LABELS = {
  AUTH_ERROR: 'API key is invalid or expired',
  RATE_LIMIT: 'Provider rate limit reached',
  TIMEOUT: 'Request timed out',
  LOCAL_MODEL_UNAVAILABLE: 'Local model is not loaded',
  NETWORK_ERROR: 'Provider could not be reached',
  UNKNOWN: 'Model request failed',
};

function sourceLabel(meta) {
  if (meta.source === 'local_model' || meta.route === 'LOCAL' || meta.provider === 'local') return 'Local Intelligence';
  const model = meta.model && meta.model !== 'auto' ? meta.model : '';
  return model || meta.provider || 'AI assistant';
}

function fallbackTraceHtml(trace = []) {
  if (!trace.length) return '';
  const rows = trace.map(item => {
    const local = item.source === 'local_model';
    const source = local ? 'Local Intelligence' : (item.provider || 'Cloud provider');
    const model = !local && item.model ? ` / ${item.model}` : '';
    const reason = item.failure_message || FAILURE_LABELS[item.failure_reason] || (item.status === 'success' ? 'Completed' : 'Failed');
    return `<li class="attempt-${escapeHtml(item.status)}"><span class="attempt-mark" aria-hidden="true">${item.status === 'success' ? '✓' : '×'}</span><span><b>${escapeHtml(source + model)}</b><small>${escapeHtml(reason)}</small></span></li>`;
  }).join('');
  return `<ul class="fallback-trace" aria-label="Model attempts">${rows}</ul>`;
}

function workflowHtml(meta) {
  const workflow = Array.isArray(meta.agentic_log) ? meta.agentic_log.filter(Boolean) : [];
  const observations = Array.isArray(meta.agent_trace?.observations) ? meta.agent_trace.observations : [];
  if (!workflow.length && !observations.length) return '';
  const workflowItems = workflow.map(item => `<li>${escapeHtml(item)}</li>`).join('');
  const verifiedItems = observations.map(item => {
    const label = item.tool || 'Tool action';
    const status = item.ok === false ? 'failed' : 'completed';
    return `<li><span class="verified-mark" aria-hidden="true">✓</span><span><b>${escapeHtml(label)}</b><small>${escapeHtml(status)}</small></span></li>`;
  }).join('');
  return `<details class="workflow-disclosure"><summary><span aria-hidden="true">⌄</span> Workflow</summary>${workflowItems ? `<ol class="workflow-list">${workflowItems}</ol>` : ''}${verifiedItems ? `<section class="verified-actions"><h4>✓ Verified actions</h4><ul>${verifiedItems}</ul></section>` : ''}</details>`;
}

async function setMessageFeedback(button, rating, meta) {
  if (!meta.chat_id || !meta.message_id) return;
  const nextRating = meta.feedback === rating ? null : rating;
  const result = await api(`/api/chats/${encodeURIComponent(meta.chat_id)}/messages/${meta.message_id}/feedback`, {
    method: 'POST', body: JSON.stringify({rating: nextRating}),
  });
  meta.feedback = result.rating;
  const toolbar = button.closest('.message-toolbar');
  toolbar?.querySelectorAll('[data-rating]').forEach(item => item.classList.toggle('is-active', item.dataset.rating === result.rating));
}

function appendToolbar(bubble, text, meta) {
  if (!meta.message_id || meta.error || meta.typing) return;
  const toolbar = document.createElement('div'); toolbar.className = 'message-toolbar';
  const copy = document.createElement('button'); copy.type = 'button'; copy.className = 'icon-btn'; copy.textContent = '⧉'; copy.title = 'Copy answer'; copy.setAttribute('aria-label', 'Copy answer');
  copy.onclick = async () => { await navigator.clipboard.writeText(text); copy.classList.add('is-active'); setTimeout(() => copy.classList.remove('is-active'), 900); };
  const up = document.createElement('button'); up.type = 'button'; up.className = 'icon-btn'; up.dataset.rating = 'up'; up.textContent = '↑'; up.title = 'Helpful'; up.setAttribute('aria-label', 'Thumbs up');
  const down = document.createElement('button'); down.type = 'button'; down.className = 'icon-btn'; down.dataset.rating = 'down'; down.textContent = '↓'; down.title = 'Not helpful'; down.setAttribute('aria-label', 'Thumbs down');
  [up, down].forEach(item => item.onclick = () => setMessageFeedback(item, item.dataset.rating, meta).catch(() => item.classList.add('error')));
  const regenerate = document.createElement('button'); regenerate.type = 'button'; regenerate.className = 'icon-btn'; regenerate.textContent = '↻'; regenerate.title = 'Regenerate answer'; regenerate.setAttribute('aria-label', 'Regenerate answer');
  regenerate.onclick = () => regenerateMessage?.(meta.regenerate_content || '');
  toolbar.append(copy, up, down, regenerate); bubble.append(toolbar);
  toolbar.querySelectorAll('[data-rating]').forEach(item => item.classList.toggle('is-active', item.dataset.rating === meta.feedback));
}

export function appendMessage(role, text, meta = {}) {
  const message = document.createElement('article');
  message.className = `message-row ${role}${meta.error ? ' message-error' : ''}${meta.typing ? ' is-typing' : ''}`;
  const avatar = document.createElement('div');
  avatar.className = 'message-avatar'; avatar.textContent = role === 'assistant' ? 'Z' : 'Y'; avatar.setAttribute('aria-hidden', 'true');
  const content = document.createElement('div'); content.className = 'message-content';
  const header = document.createElement('header'); header.className = 'message-header';
  const name = document.createElement('b'); name.textContent = role === 'assistant' ? 'ZEVORA' : 'You'; header.append(name);
  if (role === 'assistant') { const source = document.createElement('span'); source.textContent = sourceLabel(meta); header.append(source); }
  const bubble = document.createElement('div'); bubble.className = 'message-bubble';
  if (role === 'assistant' && !meta.typing) bubble.insertAdjacentHTML('beforeend', workflowHtml(meta));
  const body = document.createElement('div'); body.className = 'message-body';
  if (meta.typing) body.innerHTML = `<span class="typing-copy">${escapeHtml(text)}</span><span class="typing-dots" aria-label="Generating response"><i></i><i></i><i></i></span>`;
  else body.innerHTML = renderMarkdown(text);
  bubble.append(body);
  if (meta.error) bubble.insertAdjacentHTML('beforeend', fallbackTraceHtml(meta.fallback_trace));
  const facts = [];
  if (meta.tools?.length) facts.push(meta.tools.join(', '));
  if (Number.isFinite(meta.estimated_cost)) facts.push(`$${Number(meta.estimated_cost).toFixed(6)}`);
  if (meta.project_files?.length) facts.push(`${meta.project_files.length} project file(s)`);
  if (meta.attachments?.length) facts.push(`${meta.attachments.length} attachment(s)`);
  if (facts.length) { const info = document.createElement('small'); info.className = 'meta technical-text'; info.textContent = facts.join(' · '); bubble.append(info); }
  if (meta.retry) { const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'retry-message'; retry.textContent = 'Try again'; retry.onclick = meta.retry; bubble.append(retry); }
  if (role === 'assistant') appendToolbar(bubble, text, meta);
  content.append(header, bubble); message.append(avatar, content);
  message.setTypingStatus = label => { const node = message.querySelector('.typing-copy'); if (node) node.textContent = label; };
  $('messages').append(message); $('messages').scrollTop = $('messages').scrollHeight;
  return message;
}

export async function newChat() {
  const chat = await api('/api/chats', {method:'POST', body:JSON.stringify({title:'New chat', project_id:$('project-select').value || null})});
  state.activeChat = chat.id;
  await navigate('/', {replace: location.pathname === '/'});
  $('messages').innerHTML = ''; $('prompt').focus(); await refreshSidebarChats();
}

export async function openChat(id) {
  const chat = await api(`/api/chats/${id}`);
  state.activeChat = id;
  if (location.pathname !== '/') await navigate('/');
  $('chat-title').textContent = chat.title; $('messages').innerHTML = ''; $('composer').classList.remove('hidden');
  if (chat.project_id && [...$('project-select').options].some(option => option.value === String(chat.project_id))) $('project-select').value = String(chat.project_id);
  let previousUser = '';
  chat.messages.forEach(message => {
    let metadata = {}; try { metadata = JSON.parse(message.metadata || '{}'); } catch (_) {}
    if (message.role === 'user') previousUser = message.content;
    if (message.role === 'assistant') {
      metadata.message_id = message.id; metadata.chat_id = id; metadata.feedback = message.feedback || null;
      metadata.regenerate_content = previousUser;
    }
    appendMessage(message.role, message.content, metadata);
  });
  await refreshSidebarChats();
}

export async function renderChatVault() {
  $('composer').classList.add('hidden'); $('chat-title').textContent = 'All Chats';
  setMessages(`<section class="panel-content"><div class="page"><div class="page-header"><h2>Chat History</h2><button id="delete-all-chats" class="btn-sm danger" type="button" disabled>Delete all chats</button></div><p id="delete-all-status" class="technical-text" role="status" aria-live="polite"></p><input id="vault-search" placeholder="Search chats..." autocomplete="off"><div id="vault-list">${loadingState('Loading chat history...', 'local')}</div></div></section>`);
  $('vault-search').oninput = () => loadVaultList($('vault-search').value.trim()); await loadVaultList('');
}

async function loadVaultList(query) {
  const chats = await api(`/api/chats?limit=500${query ? `&query=${encodeURIComponent(query)}` : ''}`);
  const container = $('vault-list'); if (!container) return;
  const deleteAllButton = $('delete-all-chats');
  if (deleteAllButton) { if (chats.length) deleteAllButton.disabled = false; deleteAllButton.onclick = deleteAllChats; }
  if (!chats.length) { container.innerHTML = `<div class="empty empty-state-compact"><b>No chats</b><p>${query ? `No results for "${escapeHtml(query)}"` : 'Start a conversation to see history here.'}</p></div>`; return; }
  const rows = chats.map(chat => `<div class="vault-row"><button class="chat-item vault-chat-item" data-chat-id="${escapeHtml(chat.id)}"><span class="chat-item-title">${escapeHtml(chat.title)}</span></button><div class="vault-actions"><button class="btn-sm rename-chat" data-chat-id="${escapeHtml(chat.id)}">Rename</button><button class="btn-sm danger delete-chat" data-chat-id="${escapeHtml(chat.id)}">Delete</button></div></div>`).join('');
  container.innerHTML = rows;
  container.querySelectorAll('.vault-chat-item').forEach(button => button.onclick = () => openChat(button.dataset.chatId));
  container.querySelectorAll('.rename-chat').forEach(button => button.onclick = () => startRenameChat(button.dataset.chatId, chats.find(chat => String(chat.id) === button.dataset.chatId)?.title || ''));
  container.querySelectorAll('.delete-chat').forEach(button => button.onclick = () => deleteChat(button.dataset.chatId, chats.find(chat => String(chat.id) === button.dataset.chatId)?.title || ''));
}

async function deleteAllChats() {
  if (!confirm('Delete all chat history? This permanently removes every conversation and cannot be undone.')) return;
  const button = $('delete-all-chats');
  if (button) { button.disabled = true; button.classList.add('btn-loading'); }
  const status = $('delete-all-status');
  if (status) { status.classList.remove('error-text'); status.textContent = 'Deleting chat history...'; }
  try {
    const result = await api('/api/chats', {method:'DELETE'});
    state.activeChat = null;
    await refreshSidebarChats();
    await renderChatVault();
    const refreshedStatus = $('delete-all-status');
    if (refreshedStatus) refreshedStatus.textContent = `${result.deleted} chat(s) deleted.`;
  } catch (error) {
    if (status) {
      status.classList.add('error-text');
      status.textContent = `Delete failed: ${userErrorMessage(error)} Restart the gateway if it was updated recently.`;
    }
  } finally {
    if (button) { button.disabled = false; button.classList.remove('btn-loading'); }
  }
}
async function deleteChat(id, title) { if (!confirm(`Delete "${title}"?`)) return; await api(`/api/chats/${id}`,{method:'DELETE'}); if (state.activeChat === id) state.activeChat = null; await (location.pathname === '/chats' ? renderChatVault() : refreshSidebarChats()); }
function startRenameChat(id, title) { renamingChatId = id; $('rename-chat-input').value = title; $('rename-chat-dialog').showModal(); }
export async function confirmRenameChat(event) { event?.preventDefault(); const title = $('rename-chat-input').value.trim(); if (!title || !renamingChatId) return; await api(`/api/chats/${renamingChatId}`,{method:'PATCH',body:JSON.stringify({title})}); renamingChatId = null; $('rename-chat-dialog').close(); await (location.pathname === '/chats' ? renderChatVault() : refreshSidebarChats()); }

exposeHandlers({openChat,confirmRenameChat});

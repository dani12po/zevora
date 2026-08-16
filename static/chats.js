import {$, api, escapeHtml, exposeHandlers, loadingState, navigate, pageWrap, setMessages, setPanel, state} from './core.js';

let renamingChatId = null;

export async function refreshSidebarChats() {
  const chats = await api('/api/chats?limit=5');
  const list = $('chat-list');
  list.innerHTML = chats.length ? '' : '<div class="sidebar-empty">No chats yet</div>';
  chats.forEach(chat => {
    const button = document.createElement('button');
    button.className = `chat-item${chat.id === state.activeChat ? ' active' : ''}`;
    button.innerHTML = `<span class="chat-item-title">${escapeHtml(chat.title)}</span>`;
    button.onclick = () => openChat(chat.id);
    list.append(button);
  });
}

export function appendMessage(role, text, meta = {}) {
  const message = document.createElement('article');
  message.className = `message ${role}${meta.error ? ' message-error' : ''}`;
  const body = document.createElement('div'); body.className = 'message-body'; body.textContent = text; message.append(body);
  const facts = [];
  if (meta.route) facts.push(meta.route, meta.provider || 'local', meta.model || 'auto');
  if (meta.tools?.length) facts.push(meta.tools.join(', '));
  if (Number.isFinite(meta.estimated_cost)) facts.push(`$${Number(meta.estimated_cost).toFixed(6)}`);
  if (meta.project_files?.length) facts.push(`${meta.project_files.length} project file(s)`);
  if (meta.attachments?.length) facts.push(`${meta.attachments.length} attachment(s)`);
  if (facts.length) { const info = document.createElement('small'); info.className = 'meta technical-text'; info.textContent = facts.join(' - '); message.append(info); }
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
  chat.messages.forEach(message => { let metadata = {}; try { metadata = JSON.parse(message.metadata || '{}'); } catch (_) {} appendMessage(message.role, message.content, metadata); });
  await refreshSidebarChats();
}

export async function renderChatVault() {
  $('composer').classList.add('hidden'); $('chat-title').textContent = 'All Chats';
  setMessages(`<section class="panel-content"><div class="page"><div class="page-header"><h2>Chat History</h2></div><input id="vault-search" placeholder="Search chats..." autocomplete="off"><div id="vault-list">${loadingState('Loading chat history...', 'local')}</div></div></section>`);
  $('vault-search').oninput = () => loadVaultList($('vault-search').value.trim()); await loadVaultList('');
}

async function loadVaultList(query) {
  const chats = await api(`/api/chats?limit=500${query ? `&query=${encodeURIComponent(query)}` : ''}`);
  const container = $('vault-list'); if (!container) return;
  if (!chats.length) { container.innerHTML = `<div class="empty empty-state-compact"><b>No chats</b><p>${query ? `No results for "${escapeHtml(query)}"` : 'Start a conversation to see history here.'}</p></div>`; return; }
  const rows = chats.map(chat => `<div class="vault-row"><button class="chat-item vault-chat-item" data-chat-id="${escapeHtml(chat.id)}"><span class="chat-item-title">${escapeHtml(chat.title)}</span></button><div class="vault-actions"><button class="btn-sm rename-chat" data-chat-id="${escapeHtml(chat.id)}">Rename</button><button class="btn-sm danger delete-chat" data-chat-id="${escapeHtml(chat.id)}">Delete</button></div></div>`).join('');
  container.innerHTML = rows;
  container.querySelectorAll('.vault-chat-item').forEach(button => button.onclick = () => openChat(button.dataset.chatId));
  container.querySelectorAll('.rename-chat').forEach(button => button.onclick = () => startRenameChat(button.dataset.chatId, chats.find(chat => String(chat.id) === button.dataset.chatId)?.title || ''));
  container.querySelectorAll('.delete-chat').forEach(button => button.onclick = () => deleteChat(button.dataset.chatId, chats.find(chat => String(chat.id) === button.dataset.chatId)?.title || ''));
}

async function deleteChat(id, title) { if (!confirm(`Delete "${title}"?`)) return; await api(`/api/chats/${id}`,{method:'DELETE'}); if (state.activeChat === id) state.activeChat = null; await (location.pathname === '/chats' ? renderChatVault() : refreshSidebarChats()); }
function startRenameChat(id, title) { renamingChatId = id; $('rename-chat-input').value = title; $('rename-chat-dialog').showModal(); }
export async function confirmRenameChat(event) { event?.preventDefault(); const title = $('rename-chat-input').value.trim(); if (!title || !renamingChatId) return; await api(`/api/chats/${renamingChatId}`,{method:'PATCH',body:JSON.stringify({title})}); renamingChatId = null; $('rename-chat-dialog').close(); await (location.pathname === '/chats' ? renderChatVault() : refreshSidebarChats()); }

exposeHandlers({openChat,confirmRenameChat});

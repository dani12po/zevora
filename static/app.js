// ── Core utils ───────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const gatewayBase = window.ZEVORA_GATEWAY_URL || window.location.origin;
let activeChat = null, isSending = false, gatewayReady = false;
let pendingAttachments = [], pendingActions = [], pendingApprovalRequest = null;
const ATTACHMENT_LIMITS = {image: 8_000_000, pdf: 12_000_000, text: 2_000_000};

async function api(path, options = {}) {
  const controller = new AbortController();
  const timeoutMs = path === '/health' ? 3000 : path === '/api/chat' ? 75000 : 15000;
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(gatewayBase + path, {
      ...options,
      headers: {'Content-Type': 'application/json', ...(options.headers || {})},
      signal: controller.signal
    });
    const data = await res.json().catch(() => ({error: {message: `HTTP ${res.status}`}}));
    if (!res.ok) {
      const payload = data.error || {};
      const err = new Error(payload.message || data.detail || 'Gateway request failed');
      Object.assign(err, payload);
      throw err;
    }
    return data;
  } catch (err) {
    if (err.name === 'AbortError') throw new Error(`Gateway request timed out after ${Math.round(timeoutMs / 1000)} seconds`);
    throw err;
  } finally { clearTimeout(timeout); }
}

function escapeHtml(v) { const n = document.createElement('div'); n.textContent = v; return n.innerHTML; }
function fmtBytes(b) {
  if (!b) return '0 B';
  const u = ['B','KB','MB','GB']; let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return `${b.toFixed(i ? 1 : 0)} ${u[i]}`;
}
function badge(label, color) {
  return `<span class="badge badge-${color}">${escapeHtml(label)}</span>`;
}
function pageWrap(headerHtml, bodyHtml, description = '') {
  return `<div class="page"><div class="page-header"><div class="page-heading">${headerHtml}${description ? `<p>${escapeHtml(description)}</p>` : ''}</div></div>${bodyHtml}</div>`;
}

// ── Client-side Router ───────────────────────────────────────────────────────
const ROUTES = {
  '/':             renderChat,
  '/chats':        renderChatVault,
  '/docs':         renderDocs,
  '/providers':    renderProviders,
  '/local-ai':     renderLocalAI,
  '/model-router': renderModelRouter,
  '/mcp':          renderMCP,
  '/terminal':     renderTerminal,
  '/filesystem':   renderFilesystem,
  '/memory':       renderMemory,
  '/cache':        renderCache,
  '/usage':        renderUsage,
  '/settings':     renderSettings,
};

// Map path → nav link id for active highlighting
const PATH_TO_NAV = {
  '/providers': 'nav-providers', '/local-ai': 'nav-local-ai',
  '/model-router': 'nav-model-router', '/mcp': 'nav-mcp',
  '/terminal': 'nav-terminal', '/filesystem': 'nav-filesystem',
  '/memory': 'nav-memory', '/cache': 'nav-cache',
  '/usage': 'nav-usage', '/docs': 'nav-docs', '/settings': 'nav-settings',
};

function setActiveNav(path) {
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  const id = PATH_TO_NAV[path];
  if (id) { const el = $(id); if (el) el.classList.add('active'); }
}

async function navigate(path, { replace = false } = {}) {
  if (replace) history.replaceState({path}, '', path);
  else history.pushState({path}, '', path);
  await render(path);
}

async function render(path) {
  const handler = ROUTES[path];
  setActiveNav(path);
  if (handler) {
    try { await handler(); }
    catch (err) { setPanel(path.slice(1) || 'chat', `<div class="card"><b style="color:var(--red)">Error</b><p style="color:var(--muted)">${escapeHtml(err.message)}</p></div>`); }
  } else {
    // Unknown path → go home
    await render('/');
  }
}

window.addEventListener('popstate', () => render(location.pathname));

// ── Gateway health ───────────────────────────────────────────────────────────
function syncWorkspaceAccess() {
  const selected = $('project-select')?.selectedOptions?.[0];
  const projectReady = Boolean(selected?.value);
  const projectName = selected?.textContent || '';
  const access = $('workspace-access');
  if (access) {
    access.className = `workspace-access ${projectReady ? 'is-project' : 'is-chat'}`;
    access.querySelector('b').textContent = projectReady ? 'File access enabled' : 'Chat only';
    access.querySelector('span').textContent = projectReady
      ? `The agent may work inside ${projectName}. File changes still require approval.`
      : 'Select a project folder before asking the agent to read or change files.';
    access.querySelector('button').classList.toggle('hidden', projectReady);
  }
  if ($('project-label') && location.pathname === '/') {
    $('project-label').textContent = projectReady
      ? `Project connected · ${projectName}`
      : 'Chat only · select a folder to let the agent work with files';
  }
}

function syncComposerState() {
  const sendButton = $('composer')?.querySelector('button[type=submit]');
  if (sendButton) sendButton.disabled = isSending || !gatewayReady;
  syncWorkspaceAccess();
}

async function checkGateway() {
  const el = $('gateway'); el.textContent = 'Checking gateway…';
  el.classList.remove('is-online', 'is-offline');
  gatewayReady = false; syncComposerState();
  try {
    const h = await api('/health');
    gatewayReady = h.status === 'ok' && h.service === 'zevora';
    el.textContent = gatewayReady ? '● Gateway connected' : '○ Gateway unavailable';
    el.classList.toggle('is-online', gatewayReady);
    el.classList.toggle('is-offline', !gatewayReady);
    el.title = `${h.service} ${h.version}`; el.onclick = gatewayReady ? null : checkGateway;
  } catch (_) {
    gatewayReady = false;
    el.textContent = '○ Gateway offline — click to retry';
    el.classList.add('is-offline');
    el.title = 'Make sure ZEVORA gateway is running';
    el.onclick = checkGateway;
  }
  syncComposerState();
  return gatewayReady;
}

// ── Panel host ────────────────────────────────────────────────────────────────
function setPanel(title, html) {
  $('chat-title').textContent = 'Workspace';
  $('project-label').textContent = title;
  $('messages').innerHTML = `<section class="panel-content">${html}</section>`;
  $('composer').classList.add('hidden');
}

// ── Projects ──────────────────────────────────────────────────────────────────
async function refreshProjects() {
  const projects = await api('/api/projects');
  const sel = $('project-select');
  const current = sel.value;
  sel.innerHTML = '<option value="">No folder selected</option>';
  projects.forEach(p => sel.add(new Option(p.name, p.id)));
  if ([...sel.options].some(option => option.value === current)) sel.value = current;
  syncWorkspaceAccess();
}
async function loadProject(path = $('project-path').value.trim()) {
  if (!path) return;
  const project = await api('/api/projects/load', {method:'POST', body:JSON.stringify({path})});
  await refreshProjects();
  $('project-select').value = project.id;
  syncWorkspaceAccess();
  $('route-status').textContent = `Folder ready · ${project.name}`;
  $('project-dialog').close();
}
async function pickProject() {
  try {
    const r = await api('/api/projects/pick-folder', {method:'POST'});
    if (!r.cancelled) {
      await refreshProjects(); $('project-select').value = r.project.id;
      syncWorkspaceAccess();
      $('route-status').textContent = `Folder ready · ${r.project.name}`;
      $('project-dialog').close();
    }
  } catch (e) { alert(e.message); }
}
async function createProject() {
  const name = $('new-project-name').value.trim(); if (!name) return;
  try {
    const created = await api('/api/projects/create', {method:'POST', body:JSON.stringify({name, approved:true})});
    await loadProject(created.project);
    $('create-dialog').close(); $('new-project-name').value = '';
  } catch (e) { alert(e.message); }
}

// ── Sidebar chat list (max 5 recent, no search here) ─────────────────────────
const SIDEBAR_LIMIT = 5;

async function refreshSidebarChats() {
  const chats = await api(`/api/chats?limit=${SIDEBAR_LIMIT}`);
  const list = $('chat-list'); list.innerHTML = '';
  if (!chats.length) {
    list.innerHTML = '<div style="padding:6px 8px;color:var(--muted);font-size:12px">No chats yet</div>';
    return;
  }
  for (const chat of chats) {
    const btn = document.createElement('button');
    btn.className = `chat-item${chat.id === activeChat ? ' active' : ''}`;
    btn.dataset.chatId = chat.id;
    btn.innerHTML = `<span class="chat-item-title">${escapeHtml(chat.title)}</span>`;
    btn.onclick = () => openChat(chat.id);
    list.append(btn);
  }
}

// ── Chat Vault helpers (shared by vault page) ─────────────────────────────────
let renamingChatId = null;

async function deleteChat(id, title) {
  if (!confirm(`Delete "${title}"?`)) return;
  await api(`/api/chats/${id}`, {method:'DELETE'});
  if (activeChat === id) { activeChat = null; }
  // Refresh whatever is currently visible
  if (location.pathname === '/chats') await renderChatVault();
  else await refreshSidebarChats();
}

function startRenameChat(id, currentTitle) {
  renamingChatId = id;
  $('rename-chat-input').value = currentTitle;
  $('rename-chat-dialog').showModal();
}

async function confirmRenameChat() {
  const title = $('rename-chat-input').value.trim();
  if (!title || !renamingChatId) return;
  await api(`/api/chats/${renamingChatId}`, {method:'PATCH', body:JSON.stringify({title})});
  renamingChatId = null; $('rename-chat-dialog').close();
  if (location.pathname === '/chats') await renderChatVault();
  else await refreshSidebarChats();
}

// ── Chat: open / new / send ───────────────────────────────────────────────────
function traceHtml(trace) {
  if (!trace?.stages?.length) return '';
  const stages = trace.stages.map(item => `<li class="trace-${escapeHtml(item.status || 'completed')}"><b>${escapeHtml(item.stage)}</b><span>${escapeHtml(item.status || 'completed')}</span></li>`).join('');
  const observations = (trace.observations || []).map(item => `<details><summary>${escapeHtml(item.tool)} · ${item.ok ? 'completed' : item.approval_required ? 'approval required' : 'failed'}</summary><pre>${escapeHtml(typeof item.output === 'string' ? item.output : JSON.stringify(item.output, null, 2))}</pre></details>`).join('');
  return `<details class="agent-trace"><summary>Agent trace · ${trace.verified === true ? 'verified' : trace.verified === false ? 'verification failed' : 'not verified'}</summary><ol>${stages}</ol>${observations}</details>`;
}

function fallbackTraceHtml(trace) {
  if (!trace?.length) return '';
  const label = item => item.source === 'local'
    ? (item.kind === 'exact_cache' ? 'Local Intelligence cache' : 'Local Intelligence')
    : `${item.provider || 'provider'}${item.model ? ` / ${item.model}` : ''}`;
  const rows = trace.map(item => `<li class="trace-${item.status === 'success' ? 'completed' : 'failed'}"><b>${escapeHtml(label(item))}</b><span>${escapeHtml(item.status)}</span></li>`).join('');
  const recovered = trace.some((item, index) => index > 1 && item.status === 'success');
  const summary = recovered ? 'Fallback trace · recovered' : 'Fallback trace';
  return `<details class="agent-trace fallback-trace"><summary>${summary}</summary><ol>${rows}</ol></details>`;
}

function fallbackStatus(data) {
  const trace = data.fallback_trace || [];
  if (data.reason === 'EXACT_CACHE_HIT') return 'Completed · answered by Local Intelligence cache';
  const winner = trace.find((item, index) => index > 1 && item.status === 'success');
  return winner ? `Completed · recovered with ${winner.provider}${winner.model ? ` / ${winner.model}` : ''}` : 'Completed';
}

function appendMessage(role, text, meta = {}) {
  const el = document.createElement('article'); el.className = `message ${role}${meta.error ? ' message-error' : ''}`;
  const body = document.createElement('div'); body.className = 'message-body'; body.textContent = text; el.append(body);
  const facts = [];
  if (meta.route) facts.push(meta.route, meta.provider || 'local', meta.model || 'auto');
  if (meta.tools?.length) facts.push(meta.tools.join(', '));
  if (Number.isFinite(meta.estimated_cost)) facts.push(`$${Number(meta.estimated_cost).toFixed(6)}`);
  if (meta.project_files?.length) facts.push(`${meta.project_files.length} project file(s)`);
  if (meta.attachments?.length) facts.push(`${meta.attachments.length} attachment(s)`);
  if (facts.length) {
    const m = document.createElement('small'); m.className = 'meta'; m.textContent = facts.join(' · '); el.append(m);
  }
  if (meta.project_files?.length) {
    const files = document.createElement('div'); files.className = 'context-files';
    files.textContent = `Context: ${meta.project_files.join(', ')}${meta.context_hash ? ` · ${meta.context_hash.slice(0, 12)}` : ''}`;
    el.append(files);
  }
  if (meta.fallback_trace?.length) el.insertAdjacentHTML('beforeend', fallbackTraceHtml(meta.fallback_trace));
  if (meta.agent_trace) el.insertAdjacentHTML('beforeend', traceHtml(meta.agent_trace));
  $('messages').append(el); $('messages').scrollTop = $('messages').scrollHeight; return el;
}

function attachmentKind(file) {
  if (file.type.startsWith('image/')) return 'image';
  if (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) return 'pdf';
  return 'text';
}

function fileBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1] || '');
    reader.onerror = () => reject(new Error(`Unable to read ${file.name}`));
    reader.readAsDataURL(file);
  });
}

function mentionedFiles(text = $('prompt').value) {
  return [...text.matchAll(/@([^\s,;]+)/g)].map(match => match[1]).slice(0, 12);
}

function renderComposerItems() {
  const host = $('composer-items');
  const attachments = pendingAttachments.map((item, index) => `<span class="composer-chip">${escapeHtml(item.name)} <small>${fmtBytes(item.size)}</small><button type="button" aria-label="Remove ${escapeHtml(item.name)}" onclick="removeAttachment(${index})">×</button></span>`);
  const actions = pendingActions.map((item, index) => `<span class="composer-chip action-chip">${escapeHtml(item.tool)}<button type="button" aria-label="Remove ${escapeHtml(item.tool)}" onclick="removeAction(${index})">×</button></span>`);
  const mentions = mentionedFiles().map(path => `<span class="composer-chip mention-chip">@${escapeHtml(path)}</span>`);
  host.innerHTML = [...attachments, ...actions, ...mentions].join('');
  host.classList.toggle('hidden', !host.innerHTML);
}

function removeAttachment(index) { pendingAttachments.splice(index, 1); renderComposerItems(); }
function removeAction(index) { pendingActions.splice(index, 1); renderComposerItems(); }

async function addAttachments(files) {
  const selected = [...files];
  if (pendingAttachments.length + selected.length > 8) throw new Error('A maximum of 8 attachments is allowed');
  for (const file of selected) {
    const kind = attachmentKind(file), limit = ATTACHMENT_LIMITS[kind];
    if (file.size > limit) throw new Error(`${file.name} exceeds the ${fmtBytes(limit)} ${kind} limit`);
    pendingAttachments.push({name:file.name, media_type:file.type || 'text/plain', data_base64:await fileBase64(file), size:file.size});
  }
  renderComposerItems();
}

function actionArgumentsTemplate(tool) {
  const templates = {
    execute_command:{command:'python -m pytest -q'}, git:{operation:'status'},
    search_files:{query:'', pattern:'*.ts'}, create_file:{path:'', content:''},
    write_file:{path:'', content:''}, edit_file:{path:'', old_text:'', new_text:''},
    move_file:{source:'', destination:''}, copy_file:{source:'', destination:''},
  };
  return templates[tool] || {path:''};
}

function openActionDialog() {
  if (!$('project-select').value) { $('route-status').textContent = 'Select a project before adding actions'; return; }
  const tool = $('action-tool').value;
  $('action-arguments').value = JSON.stringify(actionArgumentsTemplate(tool), null, 2);
  $('action-purpose').value = ''; $('action-error').classList.add('hidden'); $('action-dialog').showModal();
}

function addStructuredAction(event) {
  event.preventDefault();
  try {
    if (pendingActions.length >= 30) throw new Error('A maximum of 30 actions is allowed');
    const args = JSON.parse($('action-arguments').value);
    if (!args || Array.isArray(args) || typeof args !== 'object') throw new Error('Arguments must be a JSON object');
    pendingActions.push({tool:$('action-tool').value, arguments:args, approved:false, purpose:$('action-purpose').value.trim()});
    $('action-dialog').close(); renderComposerItems();
  } catch (error) { $('action-error').textContent = error.message; $('action-error').classList.remove('hidden'); }
}

function showApproval(request, error) {
  pendingApprovalRequest = {
    ...request,
    actions:request.actions.map(action => ({...action})),
    approvalIndexes:(error.pending_approvals || []).map(item => Number(item.index)).filter(Number.isInteger),
  };
  const toolLabels = {create_file:'Create file',write_file:'Write file',edit_file:'Edit file',delete_file:'Delete file',move_file:'Move file',copy_file:'Copy file',execute_command:'Run command'};
  const rows = (error.pending_approvals || []).map(item => `<div class="approval-item"><b>${escapeHtml(toolLabels[item.tool] || item.tool)}</b><span>${escapeHtml(item.purpose || 'Requested by the agent')}</span><pre>${escapeHtml(JSON.stringify(item.arguments || {}, null, 2))}</pre></div>`).join('');
  $('approval-list').innerHTML = rows || '<p>No approval details were returned.</p>';
  $('approval-dialog').showModal();
}

async function newChat() {
  const chat = await api('/api/chats', {method:'POST', body:JSON.stringify({title:'New chat', project_id:$('project-select').value || null})});
  activeChat = chat.id;
  await navigate('/', {replace: location.pathname === '/'});
  $('messages').innerHTML = ''; $('prompt').focus();
  await refreshSidebarChats();
}

async function openChat(id) {
  const chat = await api(`/api/chats/${id}`);
  activeChat = id;
  if (location.pathname !== '/') await navigate('/', {replace: false});
  $('chat-title').textContent = chat.title; $('messages').innerHTML = '';
  $('composer').classList.remove('hidden');
  if (chat.project_id && [...$('project-select').options].some(o => o.value === String(chat.project_id))) {
    $('project-select').value = String(chat.project_id);
  }
  syncWorkspaceAccess();
  chat.messages.forEach(m => {
    let metadata = {};
    try { metadata = JSON.parse(m.metadata || '{}'); } catch (_) { metadata = {}; }
    appendMessage(m.role, m.content, metadata);
  });
  syncComposerState();
  await refreshSidebarChats();
}

async function send(replay = null) {
  const content = replay?.content || $('prompt').value.trim(); if (!content || isSending) return;
  if (!gatewayReady && !await checkGateway()) {
    $('route-status').textContent = 'Gateway offline'; return;
  }
  const request = replay || {
    content,
    attachments: pendingAttachments.map(({name, media_type, data_base64}) => ({name, media_type, data_base64})),
    actions: pendingActions.map(action => ({...action})),
  };
  isSending = true; syncComposerState();
  let userMessage = null, waiting = null;
  try {
    if (!activeChat) await newChat();
    const projectId = $('project-select').value || null;
    // The gateway performs planning as well; this client-side preflight is kept
    // only for showing approval details before normal chat execution.
    if (!replay && projectId && !request.actions.length) {
      $('route-status').textContent = 'Step 1 of 3 · Planning the required actions';
      const plan = await api('/api/agent/plan', {method:'POST', body:JSON.stringify({
        prompt: content, project_id: Number(projectId),
      })});
      request.actions = (plan.actions || []).map(action => ({
        tool:action.tool, arguments:action.arguments, purpose:action.purpose, approved:false,
      }));
    }
    userMessage = appendMessage('user', content, {attachments:request.attachments}); $('prompt').value = '';
    $('route-status').textContent = request.actions.length ? 'Step 2 of 3 · Running approved actions' : 'Generating response';
    waiting = appendMessage('assistant', request.actions.length ? 'Working in the selected project…' : 'Preparing a response…');
    const mode=$('routing-override')?.value||'auto';
    const provider=$('routing-provider')?.value||null, model=$('routing-model')?.value||null;
    const data = await api('/api/chat', {method:'POST', body:JSON.stringify({
      message: content, conversation_id: activeChat,
      project_id: projectId, mode, provider, model,
      attachments: request.attachments, actions: request.actions,
    })});
    activeChat = data.conversation_id; waiting.remove();
    appendMessage('assistant', data.response, data);
    pendingAttachments = []; pendingActions = []; pendingApprovalRequest = null; renderComposerItems();
    $('route-status').textContent = data.reason === 'TOOLS_EXECUTED'
      ? 'Completed · changes were written to the selected folder'
      : fallbackStatus(data);
    await refreshSidebarChats();
  } catch (err) {
    waiting?.remove();
    const readableErrors = {
      PROJECT_REQUIRED: 'Open a project folder first. The agent cannot access drive files from chat-only mode.',
      ACTION_FAILED: 'The requested action failed. No success was reported and files outside the selected folder were not changed.',
      AI_EXECUTION_ERROR: err.message || 'Local Intelligence had no exact answer and all available AI providers failed.',
    };
    const explanation = readableErrors[err.code] || err.message || 'The request could not be completed.';
    $('route-status').textContent = err.code === 'APPROVAL_REQUIRED' ? 'Waiting for your approval' : `Stopped · ${explanation}`;
    if (err.code === 'APPROVAL_REQUIRED') {
      userMessage?.remove(); $('prompt').value = content; showApproval(request, err);
    } else {
      if (!userMessage) userMessage = appendMessage('user', content, {attachments:request.attachments});
      appendMessage('assistant', explanation, {error:true, fallback_trace:err.fallback_trace});
      if (err.code === 'PROJECT_REQUIRED') $('project-dialog').showModal();
      if (!err.code) { gatewayReady = false; await checkGateway(); }
    }
  } finally { isSending = false; syncComposerState(); renderComposerItems(); $('prompt').focus(); }
}

async function approvePendingActions(event) {
  event.preventDefault();
  if (!pendingApprovalRequest) return;
  const approvedIndexes = new Set(pendingApprovalRequest.approvalIndexes || []);
  pendingApprovalRequest.actions = pendingApprovalRequest.actions.map((action, index) => ({...action, approved:action.approved || approvedIndexes.has(index)}));
  const {approvalIndexes: _, ...replay} = pendingApprovalRequest; $('approval-dialog').close(); pendingApprovalRequest = null;
  await send(replay);
}

// ── VIEW: / (Chat) ────────────────────────────────────────────────────────────
async function refreshRoutingSelectors() {
  const mode=$('routing-override'); if(!mode)return;
  const models=await api('/api/models').catch(()=>[]);
  const providers=[...new Set(models.map(item=>item.provider))];
  $('routing-provider').innerHTML=providers.map(item=>`<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`).join('');
  const syncModels=()=>{const selected=$('routing-provider').value;$('routing-model').innerHTML=models.filter(item=>item.provider===selected).map(item=>`<option value="${escapeHtml(item.model_id)}">${escapeHtml(item.model_id)}</option>`).join('');};
  $('routing-provider').onchange=syncModels; syncModels();
  mode.onchange=()=>{const explicit=mode.value==='provider'||mode.value==='model';$('routing-provider').classList.toggle('hidden',!explicit);$('routing-model').classList.toggle('hidden',mode.value!=='model');}; mode.onchange();
}
function renderChat() {
  $('composer').classList.remove('hidden'); refreshRoutingSelectors();
  $('chat-title').textContent = activeChat ? 'Chat' : 'What are you building?';
  if (!activeChat) {
    $('messages').innerHTML = `<div class="empty"><b>ZEVORA</b>
      <p>Open a project folder, then ask the agent to create, edit, inspect, or test files.</p>
      <div class="actions">
        <button id="open-project">Open folder</button>
        <button id="create-project">Create project</button>
      </div>
      <a class="empty-docs" href="/docs" data-route>Read the quick start</a></div>`;
    const op = $('open-project'); if (op) op.onclick = () => $('project-dialog').showModal();
    const cp = $('create-project'); if (cp) cp.onclick = () => $('create-dialog').showModal();
  }
  syncWorkspaceAccess();
}

// ── VIEW: /docs ───────────────────────────────────────────────────────────────
function renderDocs() {
  setPanel('Docs', pageWrap('<h2>Using ZEVORA</h2>', `<div class="docs-layout">
    <nav class="docs-toc" aria-label="Documentation sections">
      <a href="#quick-start">Quick start</a><a href="#file-work">Create or edit files</a>
      <a href="#approval">Approvals</a><a href="#status-guide">Status guide</a>
    </nav>
    <div class="docs-content">
      <section id="quick-start"><h3>Quick start</h3><ol><li>Click <b>Open folder</b>.</li><li>Choose a specific project folder, for example <code>E:\\Projects\\my-app</code>.</li><li>Describe the result you want in chat.</li><li>Review and approve file changes when prompted.</li></ol></section>
      <section id="file-work"><h3>Create or edit files</h3><p>Use a direct request with the filename and desired result.</p><pre>Create contoh.html with a responsive personal profile page.</pre><p>The agent plans the operation, asks for approval, writes inside the selected folder, and reports the exact saved path.</p></section>
      <section id="approval"><h3>Approvals</h3><p>Reading project files is automatic. Creating, overwriting, moving, or deleting files requires one-time approval. ZEVORA cannot write outside the selected project folder.</p></section>
      <section id="status-guide"><h3>Status guide</h3><dl><dt>Chat only</dt><dd>No folder access. General questions still work.</dd><dt>File access enabled</dt><dd>The selected project is available to tools.</dd><dt>Waiting for your approval</dt><dd>Review the exact action before it runs.</dd><dt>Completed</dt><dd>The backend confirmed the request or file operation succeeded.</dd><dt>Stopped</dt><dd>No success was reported. Read the visible explanation before retrying.</dd></dl></section>
    </div></div>`));
}

// ── VIEW: /chats (Vault) ──────────────────────────────────────────────────────
async function renderChatVault() {
  $('composer').classList.add('hidden');
  $('chat-title').textContent = 'All Chats';
  // Render search box + loading state immediately
  $('messages').innerHTML = `<section class="panel-content">
    <div class="page">
      <div class="page-header" style="gap:12px">
        <h2 style="margin:0">Chat History</h2>
      </div>
      <input id="vault-search" placeholder="Search chats…" style="margin-bottom:16px" autocomplete="off">
      <div id="vault-list"><div style="color:var(--muted);padding:20px 0">Loading…</div></div>
    </div>
  </section>`;

  $('vault-search').oninput = () => loadVaultList($('vault-search').value.trim());
  await loadVaultList('');
}

async function loadVaultList(query) {
  const url = `/api/chats?limit=500${query ? '&query=' + encodeURIComponent(query) : ''}`;
  const chats = await api(url);
  const container = $('vault-list');
  if (!container) return;
  if (!chats.length) {
    container.innerHTML = `<div class="empty" style="margin:40px auto"><b>No chats</b><p>${query ? 'No results for "' + escapeHtml(query) + '"' : 'Start a conversation to see history here.'}</p></div>`;
    return;
  }
  const now = Date.now();
  const groups = [
    {label:'Today',        test: d => now - d < 864e5},
    {label:'Last 7 days',  test: d => now - d < 6048e5  && now - d >= 864e5},
    {label:'Last 30 days', test: d => now - d < 25920e5 && now - d >= 6048e5},
    {label:'Older',        test: () => true},
  ];
  let html = '';
  for (const grp of groups) {
    const gc = chats.filter(c => grp.test(new Date(c.updated_at).getTime()));
    if (!gc.length) continue;
    html += `<div class="chat-group-label">${grp.label}</div>`;
    for (const c of gc) {
      html += `<div class="vault-row">
        <button class="chat-item vault-chat-item" onclick="openChatFromVault('${c.id}')">
          <span class="chat-item-title">${escapeHtml(c.title)}</span>
        </button>
        <div class="vault-actions">
          <button class="btn-sm" onclick="startRenameChat('${c.id}','${escapeHtml(c.title).replace(/'/g,"\\'")}')">Rename</button>
          <button class="btn-sm danger" onclick="deleteChat('${c.id}','${escapeHtml(c.title).replace(/'/g,"\\'")}')">Delete</button>
        </div>
      </div>`;
    }
  }
  container.innerHTML = html;
}

async function openChatFromVault(id) {
  await openChat(id);
  // openChat navigates to '/' and loads the chat
}

// ── VIEW: /providers ──────────────────────────────────────────────────────────
async function renderProviders() {
  const [providerStatus, providerConfig, models, manifests] = await Promise.all([
    api('/api/providers'), api('/api/providers/config'), api('/api/models'),
    api('/api/provider-manifests').catch(() => ({providers:[], runtime_availability:{}}))
  ]);
  const modelCounts = {}; models.forEach(m => { modelCounts[m.provider] = (modelCounts[m.provider] || 0) + 1; });
  const statusMap = {}; providerStatus.forEach(p => { statusMap[p.provider] = p.health_status; });
  const LABELS = {local:'Zevora Local AI',openai:'OpenAI',xai:'xAI (Grok)',nvidia:'NVIDIA NIM',deepseek:'DeepSeek',gemini:'Google Gemini',anthropic:'Anthropic'};
  const DESCRIPTIONS = {
    local:'Private on-device GGUF runtime · llama.cpp · no API key required',
    openai:'GPT-4o family · OpenAI-compatible API',
    xai:'Grok family · xAI API',
    nvidia:'NIM inference · NVIDIA API',
    deepseek:'DeepSeek family · reasoning-capable',
    gemini:'Gemini family · Google AI',
    anthropic:'Claude family · Anthropic API',
  };
  let cards = '';

  const buildCard = (p) => {
    const health = statusMap[p.provider] || (p.provider === 'local' && p.runtime_status?.configured ? 'healthy' : 'unconfigured');
    if (p.provider === 'local') {
      const runtime = p.runtime_status || {};
      const state = runtime.loaded ? 'loaded' : runtime.configured ? 'ready' : 'unavailable';
      const stateBadge = state === 'loaded' || state === 'ready' ? badge(`● ${state}`, 'green') : badge('● unavailable', 'red');
      return `<div class="card" style="margin-bottom:12px"><div class="provider-card">
        <div class="provider-card-name">${escapeHtml(LABELS.local)} ${stateBadge}</div>
        <div style="font-size:12px;color:var(--muted)">${runtime.runtime || 'llamacpp'}</div>
        <div style="grid-column:1/-1;font-size:12px;color:var(--muted)">${escapeHtml(DESCRIPTIONS.local)}</div>
        <div class="card-grid" style="grid-column:1/-1">
          <div class="card-sm card"><div class="card-lbl">Model</div><div class="card-val">${escapeHtml(runtime.model_id || p.default_model || 'zevora')}</div></div>
          <div class="card-sm card"><div class="card-lbl">GGUF</div><div class="card-val">${runtime.model_exists ? `${runtime.model_size_mb} MB` : 'Missing'}</div></div>
          <div class="card-sm card"><div class="card-lbl">Context</div><div class="card-val">${runtime.context_length || '—'}</div></div>
          <div class="card-sm card"><div class="card-lbl">Process RSS</div><div class="card-val">${runtime.process_rss_mb ? runtime.process_rss_mb + ' MB' : '—'}</div></div>
          <div class="card-sm card"><div class="card-lbl">Load delta</div><div class="card-val">${runtime.load_delta_mb ? runtime.load_delta_mb + ' MB' : 'Not loaded'}</div></div>
        </div>
        <div style="grid-column:1/-1;font-size:11px;color:var(--muted);word-break:break-word">${escapeHtml(runtime.model_path || '')}</div>
      </div></div>`;
    }
    const bh = health === 'healthy' ? badge('● healthy','green')
      : !p.key_set ? badge('○ not configured','grey')
      : health === 'unavailable' ? badge('● unavailable','red')
      : badge('○ not configured','grey');
    const desc = DESCRIPTIONS[p.provider] || 'Custom OpenAI-compatible provider';
    const keyRow = `
      <div class="provider-field"><label>API Key</label>
        <span class="key-display" id="key-display-${p.provider}">${p.key_set ? '••••••••' + p.key_masked.slice(-4) : 'Not set'}</span>
        <button class="btn-sm" onclick="toggleKeyEdit('${p.provider}')">Edit</button></div>
      <div class="provider-field" id="key-edit-${p.provider}" style="display:none"><label>New key</label>
        <input type="password" id="key-input-${p.provider}" placeholder="sk-…" autocomplete="new-password">
        <button class="btn-sm" onclick="cancelKeyEdit('${p.provider}')">Cancel</button></div>`;
    return `<div class="card" style="margin-bottom:12px"><div class="provider-card">
      <div class="provider-card-name">${escapeHtml(LABELS[p.provider] || p.provider)} ${bh}</div>
      <div style="display:flex;gap:6px;align-items:center">
        <span style="font-size:12px;color:var(--muted)">${modelCounts[p.provider] || 0} models</span>
        <label class="toggle" title="Enabled"><input type="checkbox" id="toggle-${p.provider}" ${p.enabled ? 'checked' : ''} onchange="markProviderDirty('${p.provider}')"><span class="toggle-slider"></span></label>
      </div>
      ${desc ? `<div style="grid-column:1/-1;font-size:12px;color:var(--muted);margin-bottom:4px">${escapeHtml(desc)}</div>` : ''}
      <div class="provider-fields">${keyRow}
        <div class="provider-field"><label>Base URL</label>
          <input type="text" id="url-${p.provider}" value="${escapeHtml(p.base_url)}" oninput="markProviderDirty('${p.provider}')"><span></span></div>
        <div class="provider-field"><label>Default Model</label>
          <input type="text" id="model-${p.provider}" value="${escapeHtml(p.default_model || '')}" placeholder="Provider model ID" oninput="markProviderDirty('${p.provider}')"><span></span></div>
        <div class="provider-field"><label>Image input</label>
          <label class="toggle" title="Advertise vision support only when this endpoint and model accept images"><input type="checkbox" id="vision-${p.provider}" ${p.supports_vision ? 'checked' : ''} onchange="markProviderDirty('${p.provider}')"><span class="toggle-slider"></span></label><span></span></div>
        <div class="provider-field"><label>Priority</label>
          <input type="number" id="prio-${p.provider}" value="${p.routing_priority}" min="0" max="999" style="width:80px" oninput="markProviderDirty('${p.provider}')"><span></span></div>
      </div>
      <div class="provider-save">
        <span class="save-msg" id="save-msg-${p.provider}">Saved ✓</span>
        <button class="btn-sm" id="save-btn-${p.provider}" onclick="saveProvider('${p.provider}')" disabled>Save</button>
      </div>
    </div></div>`;
  };

  if (!providerConfig.length) {
    cards = `<div class="empty" style="margin:40px auto"><b>No providers</b><p>Provider config could not be loaded.</p></div>`;
  } else {
    providerConfig.forEach(p => { cards += buildCard(p); });
  }
  const customRows = (manifests.providers || []).map(p => `<div class="custom-provider-row">
    <div><b>${escapeHtml(p.name)}</b> ${badge(p.state, p.state === 'HEALTHY' || p.state === 'TRUSTED_RUNTIME' ? 'green' : 'grey')}
      <p>${escapeHtml(p.protocol)} · ${escapeHtml(p.default_model || 'model unresolved')} · ${p.credential.configured ? escapeHtml(p.credential.masked) : 'credential not set'}</p></div>
    <div class="provider-actions">
      <button class="btn-sm" onclick="testCustomProvider('${p.provider_id}',${p.protocol === 'custom-runtime'})">Test</button>
      <button class="btn-sm" onclick="exportCustomProvider('${p.provider_id}')">Export</button>
      ${p.protocol === 'custom-runtime' && !p.runtime?.trusted ? `<button class="btn-sm" onclick="trustCustomProvider('${p.provider_id}')">Trust</button>` : ''}
      <button class="btn-sm danger" onclick="removeCustomProvider('${p.provider_id}')">Delete</button>
    </div></div>`).join('') || '<p class="muted-copy">No user-defined providers.</p>';
  const customPanel = `<section class="provider-manager">
    <div class="panel-toolbar"><div><h3>Bring your own AI</h3><p>Configure a compatible endpoint or statically inspect an example script.</p></div></div>
    <div class="provider-form-grid">
      <label>ID<input id="custom-provider-id" placeholder="my-provider"></label>
      <label>Name<input id="custom-provider-name" placeholder="My Provider"></label>
      <label>Protocol<select id="custom-provider-protocol"><option>openai-compatible</option><option>anthropic-compatible</option><option>http-rest</option><option>local-openai-compatible</option><option>custom-runtime</option><option>unknown</option></select></label>
      <label>Base URL<input id="custom-provider-url" placeholder="https://api.example.com/v1"></label>
      <label>Default model<input id="custom-provider-model" placeholder="model-id"></label>
      <label>Credential environment<input id="custom-provider-env" placeholder="MY_PROVIDER_API_KEY"></label>
      <label>Credential value<input id="custom-provider-key" type="password" autocomplete="new-password" placeholder="Stored locally"></label>
      <label>Runtime language<select id="custom-provider-runtime"><option value="python">Python</option><option value="node">Node</option><option value="typescript">TypeScript</option><option value="shell">Shell</option></select></label>
    </div>
    <label class="provider-source-label">Example or runtime source<textarea id="custom-provider-source" rows="8" placeholder="Paste Python, Node, TypeScript, Shell, or cURL source"></textarea></label>
    <div class="provider-actions"><button class="btn-sm" onclick="analyzeProviderSource()">Analyze</button><button class="btn-sm" onclick="importProviderJson()">Import JSON</button><button class="btn-sm" onclick="saveCustomProvider()">Save provider</button></div>
    <pre id="provider-analysis" class="analysis-preview hidden"></pre>
    <div class="custom-provider-list">${customRows}</div>
  </section>`;
  setPanel('Providers', pageWrap('<h2>Providers</h2>', customPanel + cards));
}

async function analyzeProviderSource() {
  const source=$('custom-provider-source').value.trim(); if(!source) return;
  const result=await api('/api/provider-manifests/analyze',{method:'POST',body:JSON.stringify({source,language:'auto'})});
  const a=result.analysis; $('provider-analysis').textContent=JSON.stringify(a,null,2); $('provider-analysis').classList.remove('hidden');
  if(a.protocol && a.protocol!=='unknown') $('custom-provider-protocol').value=a.protocol;
  if(a.base_url) $('custom-provider-url').value=a.base_url;
  if(a.model) $('custom-provider-model').value=a.model;
  if(a.credential_env) $('custom-provider-env').value=a.credential_env;
  if(a.language && ['python','node','typescript','shell'].includes(a.language)) $('custom-provider-runtime').value=a.language;
}
function customProviderPayload() {
  const protocol=$('custom-provider-protocol').value, runtime=protocol==='custom-runtime';
  const language=$('custom-provider-runtime').value;
  return {provider_id:$('custom-provider-id').value.trim().toLowerCase(),name:$('custom-provider-name').value.trim(),protocol,
    base_url:$('custom-provider-url').value.trim(),default_model:$('custom-provider-model').value.trim(),
    credential:{source:'environment',name:$('custom-provider-env').value.trim().toUpperCase()},enabled:true,routing_priority:50,
    capabilities:{chat:true,streaming:null,reasoning:null,vision:null,tool_calling:null},
    runtime:runtime?{runtime:language,entrypoint:language==='python'?'provider.py':language==='shell'?'provider.sh':'provider.js',trusted:false,
      permissions:{network:true,filesystem:'temporary',workspace:false,allowed_hosts:[]}}:null};
}
async function saveCustomProvider() {
  const manifest=customProviderPayload(), source=$('custom-provider-source').value;
  await api('/api/provider-manifests',{method:'POST',body:JSON.stringify({manifest,credential_value:$('custom-provider-key').value||null,script:manifest.runtime?source:null})});
  await renderProviders();
}
async function importProviderJson() {
  const source=$('custom-provider-source').value.trim();
  let manifest; try{manifest=JSON.parse(source);}catch(_){alert('Paste a valid provider manifest JSON document.');return;}
  await api('/api/provider-manifests/import',{method:'POST',body:JSON.stringify({manifest,credential_value:$('custom-provider-key').value||null})});
  await renderProviders();
}
async function testCustomProvider(id,isRuntime) {
  const approved=!isRuntime||confirm('Run this provider script once with its declared credential and permissions?'); if(!approved)return;
  const path=isRuntime?`/api/provider-manifests/${id}/runtime-test`:`/api/provider-manifests/${id}/test`;
  const result=await api(path,{method:'POST',body:JSON.stringify({runtime_approved:isRuntime})}); alert(result.result?.success?'Connection succeeded':result.result?.message||'Connection failed'); await renderProviders();
}
async function trustCustomProvider(id) { if(!confirm('Trust this runtime for future provider requests?'))return; await api(`/api/provider-manifests/${id}/trust`,{method:'POST',body:JSON.stringify({approved:true})}); await renderProviders(); }
async function removeCustomProvider(id) { if(!confirm(`Delete provider ${id} and its stored runtime source?`))return; await api(`/api/provider-manifests/${id}`,{method:'DELETE'}); await renderProviders(); }
async function exportCustomProvider(id) { const data=await api(`/api/provider-manifests/${id}/export`); const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'}); const link=document.createElement('a'); link.href=URL.createObjectURL(blob); link.download=`${id}.provider.json`; link.click(); URL.revokeObjectURL(link.href); }

function toggleKeyEdit(p) { $(`key-edit-${p}`).style.display='grid'; $(`key-display-${p}`).closest('.provider-field').style.display='none'; markProviderDirty(p); }
function cancelKeyEdit(p) { $(`key-edit-${p}`).style.display='none'; $(`key-display-${p}`).closest('.provider-field').style.display='grid'; }
function markProviderDirty(p) { const b=$(`save-btn-${p}`); if(b) b.disabled=false; }
async function saveProvider(p) {
  const btn=$(`save-btn-${p}`); btn.classList.add('btn-loading');
  const ki=$(`key-input-${p}`);
  try {
    const priority = Number.parseInt($(`prio-${p}`)?.value, 10);
    await api('/api/providers/config', {method:'POST', body:JSON.stringify({provider:p, base_url:$(`url-${p}`)?.value||null, default_model:$(`model-${p}`)?.value?.trim()||null, routing_priority:Number.isNaN(priority)?null:priority, enabled:$(`toggle-${p}`)?.checked??null, supports_vision:$(`vision-${p}`)?.checked??null, api_key:ki?.value?.trim()||null})});
    const msg=$(`save-msg-${p}`); msg.classList.add('show'); setTimeout(()=>msg.classList.remove('show'),2500);
    btn.disabled=true; if(ki){ki.value=''; cancelKeyEdit(p);}
  } catch(e){ alert(`Save failed: ${e.message}`); } finally{ btn.classList.remove('btn-loading'); }
}

// ── VIEW: /local-ai ── Local Intelligence (memory, cache, experience) ─────────
async function renderLocalAI() {
  const [h, storage, mem, stats, intel, evolution] = await Promise.all([
    api('/api/health'),
    api('/api/storage'),
    api('/api/memory'),
    api('/api/stats'),
    api('/api/intelligence').catch(() => ({})),
    api('/api/evolution/status').catch(() => ({})),
  ]);
  const res = h.local_resource || {};
  const cats = mem.categories || {};
  const today = stats.today || {};
  const cacheHits = intel.api_calls_avoided ?? (today.cache_hits || 0);
  const totalReqs = intel.total_api_calls ?? (today.requests || 0);
  const hitRate = intel.cache_hit_rate ?? (totalReqs > 0 ? Math.round((cacheHits / totalReqs) * 100) : 0);
  const knowledgeCount = intel.knowledge_count || 0;

  // Storage numbers
  const memBytes = storage.categories?.memory || 0;
  const cacheBytes = storage.categories?.cache || 0;
  const expBytes = storage.categories?.experience || 0;

  const configuredProviders = (h.providers_configured || []).map(p => escapeHtml(p)).join(', ') || 'None configured';

  setPanel('Local Intelligence', pageWrap(
    `<h2>Local Intelligence</h2>${badge('Active','green')}`,
    `<div class="card" style="margin-bottom:12px">
      <div style="color:var(--muted);font-size:13px;margin-bottom:16px">
        ZEVORA keeps memory, experience, project context, and cache on this machine.
        <b style="color:var(--text)">Zevora Local AI</b> also handles eligible generation privately through llama.cpp,
        while configured cloud providers handle complex, vision, and fallback work.
      </div>
      <div class="card-grid">
        <div class="card-sm card"><div class="card-lbl">Memory</div><div class="card-val">${fmtBytes(memBytes)}</div></div>
        <div class="card-sm card"><div class="card-lbl">Knowledge Patterns</div><div class="card-val">${knowledgeCount}</div></div>
        <div class="card-sm card"><div class="card-lbl">Cache</div><div class="card-val">${fmtBytes(cacheBytes)}</div></div>
        <div class="card-sm card"><div class="card-lbl">Experience</div><div class="card-val">${fmtBytes(expBytes)}</div></div>
        <div class="card-sm card"><div class="card-lbl">Cache hit rate</div><div class="card-val">${hitRate}%</div></div>
        <div class="card-sm card"><div class="card-lbl">API calls avoided</div><div class="card-val">${cacheHits}</div></div>
        <div class="card-sm card"><div class="card-lbl">RAM available</div><div class="card-val">${res.ram_available_mb ? res.ram_available_mb + ' MB' : '—'}</div></div>
      </div>
    </div>
    <div class="card" style="margin-bottom:12px">
      <b>Memory categories</b>
      <div class="mem-grid" style="margin-top:12px">
        ${Object.entries(cats).map(([k,v]) => {
          const icons = {conversation:'💬', project:'📁', experience:'⭐', preferences:'⚙'};
          return `<div class="card card-sm"><div class="card-lbl">${icons[k]||'📌'} ${k}</div><div class="card-val">${v}</div></div>`;
        }).join('') || '<span style="color:var(--muted)">No memory entries yet.</span>'}
      </div>
    </div>
    <div class="card" style="margin-bottom:12px">
      <b>Local model and evolution</b>
      <div class="card-grid" style="margin-top:12px">
        <div class="card-sm card"><div class="card-lbl">Runtime</div><div class="card-val" style="font-size:15px">${escapeHtml(evolution.local_intelligence?.runtime || 'unknown')}</div></div>
        <div class="card-sm card"><div class="card-lbl">Installed packages</div><div class="card-val">${evolution.local_intelligence?.installed_packages?.length || 0}</div></div>
        <div class="card-sm card"><div class="card-lbl">Registered skills</div><div class="card-val">${evolution.skills?.length || 0}</div></div>
        <div class="card-sm card"><div class="card-lbl">Validated patterns</div><div class="card-val">${evolution.evolution?.validated_patterns || 0}</div></div>
        <div class="card-sm card"><div class="card-lbl">Collective learning</div><div class="card-val" style="font-size:15px">${evolution.collective_learning?.enabled ? 'Enabled' : 'Disabled'}</div></div>
        <div class="card-sm card"><div class="card-lbl">Update verification</div><div class="card-val" style="font-size:15px">${escapeHtml(evolution.updates?.verification || 'unknown')}</div></div>
      </div>
    </div>
    <div class="card">
      <b>Active providers</b>
      <p style="color:var(--muted);font-size:13px;margin:8px 0 0">${configuredProviders}</p>
      <p style="color:var(--muted);font-size:12px;margin:8px 0 0">
        Configure provider API keys in <a href="/providers" data-route style="color:var(--accent)">Providers</a>.
      </p>
    </div>`
  ));
}

// ── VIEW: /model-router ───────────────────────────────────────────────────────
async function renderModelRouter() {
  const s = await api('/api/routing/settings');
  const mode = s.mode || 'AUTO';
  const steps = [
    {label:'Local context', active:true, desc:'Cache · Memory · Project'},
    {label:'Hybrid scoring', active:true, desc:'Capability · Complexity · History'},
    {label:'Local or cloud', active:true, desc:'Zevora Local AI · Cloud providers'},
  ];
  const flow = steps.map((st,i) =>
    `${i?'<span class="route-arrow">→</span>':''}<div class="route-step${st.active?' active-step':''}" style="min-width:130px"><div>${st.label}</div><div style="font-size:10px;color:var(--muted);font-weight:400;margin-top:3px">${st.desc}</div></div>`
  ).join('');
  setPanel('Model Router', pageWrap('<h2>Model Router</h2>', `
    <div class="card" style="margin-bottom:12px">
      <b>Request flow</b>
      <div class="route-flow" style="margin-top:12px;flex-wrap:wrap;gap:4px">${flow}</div>
      <div class="card-grid" style="margin-top:16px">
        <div class="card-sm card"><div class="card-lbl">Mode</div><div class="card-val" style="font-size:15px">${escapeHtml(mode)}</div></div>
        <div class="card-sm card"><div class="card-lbl">Cloud fallback</div><div class="card-val" style="font-size:15px">${s.cloud_fallback?'✓ Yes':'✗ No'}</div></div>
        <div class="card-sm card"><div class="card-lbl">Cost optimized</div><div class="card-val" style="font-size:15px">${s.cost_optimization?'✓ Yes':'✗ No'}</div></div>
        <div class="card-sm card"><div class="card-lbl">Repair attempts</div><div class="card-val">${s.max_repair_attempts}</div></div>
      </div>
    </div>
    <div class="card">
      <b>How routing works</b>
      <ol style="margin:10px 0 0;padding-left:20px;color:var(--muted);font-size:13px;line-height:2">
        <li>Check exact cache — if hit, return immediately (zero API cost)</li>
        <li>Classify task type and required capabilities</li>
        <li>Score all configured providers by capability, cost, and history</li>
        <li>Execute on best-scoring provider</li>
        <li>On failure or quality rejection, fallback between local and cloud candidates when enabled</li>
        <li>Store result in cache and update routing experience</li>
      </ol>
    </div>
    <p style="color:var(--muted);font-size:12px;margin-top:12px">
      Change routing mode in <a href="/settings" data-route style="color:var(--accent)">Settings</a>.
      Configure providers in <a href="/providers" data-route style="color:var(--accent)">Providers</a>.
    </p>`
  ));
}

// ── VIEW: /mcp ────────────────────────────────────────────────────────────────
async function renderMCP() {
  const tools = await api('/api/tools');
  const PC = {auto:'green',approval:'yellow',deny:'red'};
  const rows = tools.map(t=>`<tr>
    <td><code style="font-family:monospace">${escapeHtml(t.name)}</code></td>
    <td>${badge(t.permission,PC[t.permission]||'grey')}</td>
    <td><label class="toggle" title="Enable ${escapeHtml(t.name)}">
      <input type="checkbox" ${t.enabled?'checked':''} onchange="setMCPToolEnabled('${escapeHtml(t.name)}',this)">
      <span class="toggle-slider"></span>
    </label></td>
    <td><span class="inline-status" id="mcp-status-${escapeHtml(t.name)}">${t.enabled?'Enabled':'Disabled'}</span></td>
  </tr>`).join('');
  setPanel('MCP', pageWrap('<h2>MCP Tools</h2>',`<div class="card"><div class="tbl-wrap"><table class="tbl">
    <thead><tr><th>Tool</th><th>Permission</th><th>Enabled</th><th>Status</th></tr></thead>
    <tbody>${rows||'<tr><td colspan="4" style="color:var(--muted)">No tools registered</td></tr>'}</tbody>
  </table></div></div>`));
}

async function setMCPToolEnabled(tool, input) {
  const previous = !input.checked;
  const status = $(`mcp-status-${tool}`);
  input.disabled = true;
  if (status) status.textContent = 'Saving…';
  try {
    const updated = await api(`/api/tools/${encodeURIComponent(tool)}`, {
      method:'PUT', body:JSON.stringify({enabled:input.checked})
    });
    input.checked = updated.enabled;
    if (status) status.textContent = updated.enabled ? 'Enabled' : 'Disabled';
  } catch (error) {
    input.checked = previous;
    if (status) status.textContent = error.message || 'Update failed';
  } finally {
    input.disabled = false;
  }
}

// ── VIEW: /terminal ───────────────────────────────────────────────────────────
function renderTerminal() {
  const projectReady = Boolean($('project-select').value);
  setPanel('Terminal', pageWrap(`<h2>Scoped Terminal</h2>${badge('approval required','yellow')}`, `<div class="card terminal-tool">
    <p>Commands run without a shell inside the selected project. Only bounded test and syntax-check commands accepted by the backend allowlist can run.</p>
    <label>Command<input id="terminal-command" value="python -m pytest -q" ${projectReady?'':'disabled'}></label>
    <label>Purpose<input id="terminal-purpose" value="Run the project test suite" ${projectReady?'':'disabled'}></label>
    <button class="btn-sm" id="queue-terminal" ${projectReady?'':'disabled'} onclick="queueTerminalAction()">Add to chat for approval</button>
    <span id="terminal-msg" class="inline-status">${projectReady?'The action will not run until confirmed in chat.':'Select a project first.'}</span>
  </div>`));
}

function queueTerminalAction() {
  const command = $('terminal-command').value.trim(); if (!command) return;
  pendingActions.push({tool:'execute_command', arguments:{command}, approved:false, purpose:$('terminal-purpose').value.trim()});
  renderComposerItems(); navigate('/'); $('route-status').textContent = 'Terminal action queued · send a prompt to request approval';
}

// ── VIEW: /filesystem ─────────────────────────────────────────────────────────
let fsProjectId = null;
async function renderFilesystem() {
  const id = $('project-select').value;
  if (!id) {
    setPanel('Filesystem', `<div class="empty" style="margin:60px auto"><b>No project open</b>
      <p>Open a project to browse its files.</p>
      <div class="actions"><button onclick="$('project-dialog').showModal()">Open project</button></div></div>`);
    return;
  }
  fsProjectId = id;
  setPanel('Filesystem', `<div style="padding:8px;color:var(--muted)">Loading tree…</div>`);
  const data = await api(`/api/filesystem/tree?project_id=${id}`);
  const layout = document.createElement('div'); layout.className='fs-layout';
  const treePane = document.createElement('div'); treePane.className='fs-tree'; treePane.id='fs-tree-pane';
  const preview = document.createElement('div'); preview.className='fs-preview'; preview.id='fs-preview';
  preview.innerHTML='<span style="color:var(--muted);font-size:13px">Click a file to preview</span>';
  layout.append(treePane, preview);
  $('messages').innerHTML=''; $('messages').append(layout); $('composer').classList.add('hidden');
  renderTree(data.tree, treePane, 0);
}

function renderTree(nodes, container, depth) {
  for (const node of nodes) {
    const row=document.createElement('div'); row.className='tree-node'; row.style.paddingLeft=`${8+depth*14}px`;
    const isDir=node.type==='dir';
    row.innerHTML=`<span class="tree-toggle">${isDir?'▶':''}</span><span class="tree-icon">${isDir?'📁':fileIcon(node.name)}</span><span>${escapeHtml(node.name)}</span>`;
    container.append(row);
    if(isDir && node.children?.length){
      const ch=document.createElement('div'); ch.className='tree-children'; ch.style.display='none';
      renderTree(node.children,ch,depth+1); container.append(ch);
      row.onclick=()=>{ const o=ch.style.display!=='none'; ch.style.display=o?'none':'block'; row.querySelector('.tree-toggle').textContent=o?'▶':'▼'; };
    } else if(!isDir){ row.onclick=()=>previewFile(node.path,row); }
  }
}
function fileIcon(n){ const e=n.split('.').pop().toLowerCase(); return {py:'🐍',js:'📜',ts:'📘',json:'📋',md:'📝',html:'🌐',css:'🎨',sh:'⚙',yml:'⚙',yaml:'⚙',txt:'📄',env:'🔑',toml:'📋',sql:'🗃',png:'🖼',jpg:'🖼',svg:'🖼'}[e]||'📄'; }
async function previewFile(path, rowEl){
  document.querySelectorAll('.fs-tree .tree-node.active').forEach(n=>n.classList.remove('active')); rowEl.classList.add('active');
  const pv=$('fs-preview'); pv.innerHTML='<span style="color:var(--muted);font-size:13px">Loading…</span>';
  try{
    const d=await api(`/api/filesystem/file?project_id=${fsProjectId}&path=${encodeURIComponent(path)}`);
    pv.innerHTML=`${d.truncated?'<div style="margin-bottom:8px;font-size:12px;color:var(--yellow)">⚠ File truncated at 200 KB</div>':''}<pre>${escapeHtml(d.content)}</pre>`;
  }catch(e){pv.innerHTML=`<span style="color:var(--red)">Error: ${escapeHtml(e.message)}</span>`;}
}

// ── VIEW: /memory ─────────────────────────────────────────────────────────────
async function renderMemory() {
  const mem = await api('/api/memory'); const cats=mem.categories||{};
  const total=Object.values(cats).reduce((a,b)=>a+b,0);
  const ICONS={conversation:'💬',project:'📁',experience:'⭐',preferences:'⚙'};
  const cards=Object.entries(cats).map(([k,v])=>`<div class="card card-sm"><div class="card-lbl">${ICONS[k]||'📌'} ${k}</div><div class="card-val">${v}</div></div>`).join('');
  setPanel('Memory', pageWrap(`<h2>Memory</h2>${badge(total+' total','grey')}`,
    `<div class="mem-grid">${cards||'<div style="color:var(--muted)">No memory entries yet.</div>'}</div>
    <div class="card"><b>Intelligence retention</b><p class="muted-copy">Preview expired operational records and low-value knowledge before deleting them.</p><div class="maintenance-actions"><button class="btn-sm" onclick="runIntelligenceMaintenance(false)">Preview cleanup</button><button class="btn-sm danger" onclick="runIntelligenceMaintenance(true)">Delete candidates</button><span id="intelligence-maintenance-msg" class="inline-status"></span></div></div>`));
}

async function runIntelligenceMaintenance(execute) {
  if (execute && !confirm('Delete the retention candidates shown by the current policy?')) return;
  const msg = $('intelligence-maintenance-msg'); msg.textContent = execute ? 'Deleting…' : 'Calculating…';
  try {
    const result = await api(`/api/maintenance/intelligence?execute=${execute?'true':'false'}`, {method:'POST'});
    const entries = Object.entries(result).filter(([key, value]) => key !== 'ok' && key !== 'executed' && Number.isFinite(value));
    msg.textContent = `${execute?'Deleted':'Candidates'} · ${entries.map(([key,value]) => `${key.replaceAll('_',' ')}: ${value}`).join(' · ') || 'none'}`;
  } catch (error) { msg.textContent = `Error: ${error.message}`; }
}

// ── VIEW: /cache ──────────────────────────────────────────────────────────────
async function renderCache() {
  const s=await api('/api/storage');
  const pct=s.budget_bytes>0?Math.min(100,(s.managed_bytes/s.budget_bytes)*100):0;
  const dpct=s.disk_total_bytes>0?Math.min(100,((s.disk_total_bytes-s.disk_free_bytes)/s.disk_total_bytes)*100):0;
  const bc=s.state==='critical'?'red':s.state==='warning'?'yellow':'green';
  const sb=s.state==='critical'?badge('● critical','red'):s.state==='warning'?badge('◐ warning','yellow'):badge('● normal','green');
  const CI={raw:'📥',processed:'⚙',curated:'✨',memory:'🧠',cache:'⚡',embeddings:'🔢',datasets:'📊',archive:'🗃',evaluation:'🔍',logs:'📋',models:'🤖'};
  const cc=Object.entries(s.categories||{}).map(([k,v])=>`<div class="card card-sm"><div class="card-lbl">${CI[k]||'📁'} ${k}</div><div class="card-val">${fmtBytes(v)}</div></div>`).join('');
  setPanel('Cache', pageWrap(`<h2>Storage</h2>${sb}`,
    `<div class="card" style="margin-bottom:12px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px"><b>Managed data</b><span style="font-size:13px">${fmtBytes(s.managed_bytes)} / ${fmtBytes(s.budget_bytes)}</span></div>
      <div class="progress-wrap"><div class="progress-bar ${bc}" style="width:${pct.toFixed(1)}%"></div></div>
      <div class="storage-summary"><span>Free: ${fmtBytes(s.disk_free_bytes)}</span><span>Total: ${fmtBytes(s.disk_total_bytes)}</span><span>Used: ${dpct.toFixed(1)}%</span></div>
    </div>
    <div class="card-grid" style="margin-bottom:16px">${cc}</div>
    <div class="card"><b>Maintenance</b>
      <div style="display:flex;gap:10px;margin-top:12px;flex-wrap:wrap">
        <button class="btn-sm" id="btn-cleanup" onclick="runCleanup()">Clear expired files</button>
        <span id="cleanup-msg" style="font-size:12px;color:var(--muted);align-self:center"></span>
      </div></div>`));
}
async function runCleanup(){
  const b=$('btn-cleanup'); b.classList.add('btn-loading'); b.textContent='Running…';
  const m=$('cleanup-msg');
  try{
    const r=await api('/api/maintenance/cleanup-plan',{method:'POST'});
    const c=r.would_delete?.length||0; const sv=fmtBytes(r.estimated_bytes_saved||0);
    m.textContent=c>0?`${c} file(s) eligible · ${sv} recoverable (dry-run)`:'Nothing to clean up.';
  }catch(e){m.textContent=`Error: ${e.message}`;}
  finally{b.classList.remove('btn-loading'); b.textContent='Clear expired files';}
}

// ── VIEW: /usage ──────────────────────────────────────────────────────────────
function usageRows(rows) {
  return rows.length ? rows.map(r => `<tr>
    <td><span class="table-date">${escapeHtml(r.day)}</span></td>
    <td><span class="provider-mark">${escapeHtml(r.provider)}</span></td>
    <td><code class="model-name">${escapeHtml(r.model || 'Not reported')}</code></td>
    <td class="numeric-cell">${Number(r.requests || 0).toLocaleString()}</td>
    <td class="numeric-cell">${Number(r.cache_hits || 0).toLocaleString()}</td>
    <td class="numeric-cell">${Number(r.input_tokens || 0).toLocaleString()}</td>
    <td class="numeric-cell">${Number(r.output_tokens || 0).toLocaleString()}</td>
    <td class="numeric-cell cost-cell">$${Number(r.estimated_cost || 0).toFixed(6)}</td>
  </tr>`).join('') : `<tr><td colspan="8" class="table-empty">No usage data for this period.</td></tr>`;
}

async function renderUsage(){
  const [today, hist] = await Promise.all([api('/api/stats'), api('/api/usage/history?days=30')]);
  const t = today.today || {};
  const requests = Number(t.requests || 0);
  const cacheHits = Number(t.cache_hits || 0);
  const cacheRate = requests ? Math.round((cacheHits / requests) * 100) : 0;
  const sc = `<div class="metric-card"><div class="metric-icon requests-icon">R</div><div><div class="card-lbl">Requests today</div><div class="card-val">${requests.toLocaleString()}</div></div></div>
    <div class="metric-card"><div class="metric-icon cache-icon">C</div><div><div class="card-lbl">Cache hits</div><div class="card-val">${cacheHits.toLocaleString()}</div></div></div>
    <div class="metric-card"><div class="metric-icon rate-icon">%</div><div><div class="card-lbl">Cache hit rate</div><div class="card-val">${cacheRate}%</div></div></div>
    <div class="metric-card"><div class="metric-icon cost-icon">$</div><div><div class="card-lbl">Estimated cost</div><div class="card-val cost-value">$${Number(t.estimated_cost || 0).toFixed(4)}</div></div></div>`;
  const rows = hist.rows || [];
  setPanel('Usage', pageWrap('<h2>Usage</h2>', `<section class="metrics-grid" aria-label="Today usage summary">${sc}</section>
    <section class="data-panel">
      <div class="panel-toolbar">
        <div><h3>Usage history</h3><p>Provider activity during the last 30 days</p></div>
        <label class="filter-field"><span>Provider</span><select id="usage-provider-filter" onchange="filterUsage()">
          <option value="">All providers</option>
          <option>local</option><option>openai</option><option>anthropic</option><option>gemini</option>
          <option>deepseek</option><option>xai</option><option>nvidia</option>
        </select></label>
      </div>
      <div class="tbl-wrap"><table class="tbl usage-table"><thead><tr><th>Date</th><th>Provider</th><th>Model</th><th>Requests</th><th>Cache hits</th><th>Input tokens</th><th>Output tokens</th><th>Est. cost</th></tr></thead>
      <tbody id="usage-body">${usageRows(rows)}</tbody></table></div>
    </section>`, 'Monitor requests, cache efficiency, token volume, and provider cost.'));
}
async function filterUsage(){
  const p = $('usage-provider-filter').value;
  const h = await api(`/api/usage/history?days=30${p ? '&provider=' + encodeURIComponent(p) : ''}`);
  const tb = $('usage-body');
  if (tb) tb.innerHTML = usageRows(h.rows || []);
}

// ── VIEW: /settings ───────────────────────────────────────────────────────────
async function renderSettings(){
  const s = await api('/api/settings');
  setPanel('Settings', pageWrap('<h2>Settings</h2>',`
    <form id="settings-form" onsubmit="saveSettings(event)">
      <div class="card" style="margin-bottom:12px"><div class="settings-section">
        <h3>Routing</h3>
        <div class="settings-row"><label for="s-routing-mode">Routing mode</label>
          <select id="s-routing-mode">
            <option value="AUTO" ${s.routing_mode==='AUTO'?'selected':''}>AUTO — local-first or cloud-first by task</option>
            <option value="LOCAL_ONLY" ${s.routing_mode==='LOCAL_ONLY'?'selected':''}>LOCAL ONLY — never call cloud providers</option>
            <option value="CLOUD_ONLY" ${s.routing_mode==='CLOUD_ONLY'?'selected':''}>CLOUD ONLY — never load the local model</option>
          </select></div>
        <div class="toggle-row"><label>Cloud fallback (retry with another provider on failure)</label>
          <label class="toggle"><input type="checkbox" id="s-cloud-fallback" ${s.cloud_fallback?'checked':''}><span class="toggle-slider"></span></label></div>
        <div class="toggle-row"><label>Cost optimization (prefer cheaper capable providers)</label>
          <label class="toggle"><input type="checkbox" id="s-cost-opt" ${s.cost_optimization?'checked':''}><span class="toggle-slider"></span></label></div>
      </div></div>
      <div class="card" style="margin-bottom:12px"><div class="settings-section">
        <h3>Gateway</h3>
        <div class="settings-row"><label>Gateway URL</label>
          <input type="text" value="${escapeHtml(s.gateway_url)}" disabled style="color:var(--muted)"></div>
      </div></div>
      <div style="display:flex;align-items:center;gap:12px">
        <button type="submit" class="primary" style="min-height:36px;padding:8px 20px">Save changes</button>
        <span id="settings-save-msg" style="font-size:13px;color:var(--accent);opacity:0;transition:opacity .3s"></span>
      </div>
    </form>`));
}
async function saveSettings(event){
  event.preventDefault();
  try{
    await api('/api/settings',{method:'POST',body:JSON.stringify({
      routing_mode:$('s-routing-mode').value,
      cloud_fallback:$('s-cloud-fallback').checked,
      cost_optimization:$('s-cost-opt').checked
    })});
    const m=$('settings-save-msg'); m.textContent='Saved ✓'; m.style.opacity='1';
    setTimeout(()=>m.style.opacity='0',2500);
  }catch(e){alert(`Save failed: ${e.message}`);}
}

// ── Event wiring ──────────────────────────────────────────────────────────────
function setSidebarOpen(open) {
  document.body.classList.toggle('sidebar-open', open);
  $('mobile-menu').setAttribute('aria-expanded', String(open));
}

function setChatSectionCollapsed(collapsed) {
  $('chat-section').classList.toggle('is-collapsed', collapsed);
  $('chat-section-toggle').setAttribute('aria-expanded', String(!collapsed));
  localStorage.setItem('zevora.sidebar.chatsCollapsed', String(collapsed));
}

$('chat-section-toggle').onclick = () => setChatSectionCollapsed(!$('chat-section').classList.contains('is-collapsed'));
$('mobile-menu').onclick = () => setSidebarOpen(true);
$('sidebar-close').onclick = () => setSidebarOpen(false);
$('sidebar-scrim').onclick = () => setSidebarOpen(false);

// Intercept all [data-route] link clicks → SPA navigation
document.addEventListener('click', e => {
  const link = e.target.closest('[data-route]');
  if (!link) return;
  const href = link.getAttribute('href');
  if (!href || href.startsWith('http')) return;
  e.preventDefault();
  setSidebarOpen(false);
  navigate(href);
});

$('new-chat').onclick = newChat;
$('open-project').onclick = () => $('project-dialog').showModal();
$('create-project').onclick = () => $('create-dialog').showModal();
$('pick-project').onclick = pickProject;
$('load-project').onclick = e => { e.preventDefault(); loadProject().catch(err => alert(err.message)); };
$('confirm-create-project').onclick = e => { e.preventDefault(); createProject(); };
$('confirm-rename-chat').onclick = e => { e.preventDefault(); confirmRenameChat(); };

$('project-select').onchange = syncWorkspaceAccess;
$('composer-open-project').onclick = () => $('project-dialog').showModal();
$('audit').onclick = async () => {
  const id = $('project-select').value; if (!id) return;
  const result = await api(`/api/projects/${id}/audit`, {method:'POST'});
  const el = $('audit-result'); el.classList.remove('hidden');
  el.textContent = `Audit · Health ${result.health_score}/100 · ${result.files_indexed} files · ${result.languages.join(', ')||'Unknown'} · ${result.frameworks.join(', ')||'No framework'}`;
};

$('composer').onsubmit = e => { e.preventDefault(); send(); };
$('prompt').oninput = renderComposerItems;
$('prompt').onkeydown = e => { if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();} };
$('attach-file').onclick = () => $('file-input').click();
$('file-input').onchange = async event => {
  try { await addAttachments(event.target.files); }
  catch (error) { $('route-status').textContent = `INVALID_ATTACHMENT · ${error.message}`; }
  finally { event.target.value = ''; }
};
$('add-action').onclick = openActionDialog;
$('action-tool').onchange = event => { $('action-arguments').value = JSON.stringify(actionArgumentsTemplate(event.target.value), null, 2); };
$('confirm-add-action').onclick = addStructuredAction;
$('approve-actions').onclick = approvePendingActions;
$('reject-actions').onclick = () => { pendingApprovalRequest = null; };
document.addEventListener('keydown', e => {
  if(e.ctrlKey&&e.key==='Enter'){e.preventDefault();send();}
  if(e.ctrlKey&&e.key.toLowerCase()==='n'){e.preventDefault();newChat();}
});

// ── Boot ──────────────────────────────────────────────────────────────────────
setChatSectionCollapsed(localStorage.getItem('zevora.sidebar.chatsCollapsed') === 'true');
checkGateway();
setInterval(checkGateway, 30000);
Promise.allSettled([refreshProjects(), refreshSidebarChats()]);
// Render the correct view based on current URL (handles refresh + direct navigation)
render(location.pathname);

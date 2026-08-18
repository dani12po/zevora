import {$, api, emptyState, escapeHtml, fmtBytes, navigate, setMessages, state, stateIndicator, userErrorMessage} from './core.js?v=20260818-11';
import {appendMessage, configureMessageActions, newChat, refreshSidebarChats, replaceAssistantMessage} from './chats.js?v=20260818-12';

const LIMITS = {image:8_000_000,pdf:12_000_000,text:2_000_000};
let projectSelectionGeneration = 0;
let activeRequestId = null;

function beginProjectSelection() { projectSelectionGeneration += 1; return projectSelectionGeneration; }
function isCurrentProjectSelection(generation) { return generation === projectSelectionGeneration; }

export function syncWorkspaceAccess() {
  const selected = $('project-select')?.selectedOptions?.[0], ready = Boolean(selected?.value), name = selected?.textContent || '';
  const access = $('workspace-access');
  if (access) { access.className = `workspace-access ${ready ? 'is-project' : 'is-chat'}`; access.querySelector('b').textContent = ready ? 'File access enabled' : 'Chat only'; access.querySelector('span').textContent = ready ? `The agent may read and change files inside ${name}. Another folder must be selected before it can be accessed.` : 'Select a project folder before asking the agent to read or change files.'; access.querySelector('button').classList.toggle('hidden', ready); }
  if ($('project-label') && location.pathname === '/') $('project-label').textContent = ready ? `Project connected - ${name}` : 'Chat only - select a folder to let the agent work with files';
}

function syncComposerState() { const button = $('composer')?.querySelector('button[type=submit]'); if (button) button.disabled = state.isSending || !state.gatewayReady; $('stop-request')?.classList.toggle('hidden', !state.isSending || !activeRequestId); syncWorkspaceAccess(); }

let gatewayCheckPromise = null;

export function checkGateway() {
  if (gatewayCheckPromise) return gatewayCheckPromise;
  const element = $('gateway');
  const wasReady = state.gatewayReady;
  if (!wasReady) {
    element.textContent = 'Checking gateway...';
    element.classList.remove('is-online','is-offline');
    syncComposerState();
  }
  gatewayCheckPromise = api('/health').then(health => {
    state.gatewayReady = health.status === 'ok' && health.service === 'zevora';
    element.textContent = state.gatewayReady ? 'Gateway connected' : 'Gateway unavailable';
    element.classList.toggle('is-online', state.gatewayReady);
    element.classList.toggle('is-offline', !state.gatewayReady);
    element.title = `${health.service} ${health.version}`;
    element.onclick = state.gatewayReady ? null : checkGateway;
    syncComposerState();
    return state.gatewayReady;
  }).catch(error => {
    state.gatewayReady = false;
    element.textContent = 'Gateway offline - click to retry';
    element.classList.remove('is-online');
    element.classList.add('is-offline');
    element.title = error.message || 'Make sure ZEVORA gateway is running';
    element.onclick = checkGateway;
    syncComposerState();
    return false;
  }).finally(() => { gatewayCheckPromise = null; });
  return gatewayCheckPromise;
}

export async function refreshProjects() { const projects = await api('/api/projects'), select = $('project-select'), current = select.value; select.innerHTML = '<option value="">No folder selected</option>'; projects.forEach(project => select.add(new Option(project.name,project.id))); if ([...select.options].some(option => option.value === current)) select.value = current; syncWorkspaceAccess(); }
export async function loadProject(path = $('project-path').value.trim()) { if (!path) return; const generation=beginProjectSelection(); const project = await api('/api/projects/load',{method:'POST',body:JSON.stringify({path})}); if(!isCurrentProjectSelection(generation))return project; await refreshProjects(); if(!isCurrentProjectSelection(generation))return project; $('project-select').value = project.id; syncWorkspaceAccess(); $('route-status').textContent = `Folder ready - ${project.name}`; $('project-dialog').close(); return project; }
export async function pickProject() { const generation=beginProjectSelection(); try { const result = await api('/api/projects/pick-folder',{method:'POST'}); if (!isCurrentProjectSelection(generation)||result.cancelled)return result; await refreshProjects(); if(!isCurrentProjectSelection(generation))return result; $('project-select').value=result.project.id; syncWorkspaceAccess(); $('route-status').textContent=`Folder ready - ${result.project.name}`; $('project-dialog').close(); return result; } catch(error){if(isCurrentProjectSelection(generation))$('route-status').textContent=userErrorMessage(error);} }
export async function createProject() { const name=$('new-project-name').value.trim(); if(!name)return; try{const created=await api('/api/projects/create',{method:'POST',body:JSON.stringify({name,approved:true})});await loadProject(created.project);$('create-dialog').close();$('new-project-name').value='';}catch(error){$('route-status').textContent=userErrorMessage(error);} }

function attachmentKind(file){if(file.type.startsWith('image/'))return'image';if(file.type==='application/pdf'||file.name.toLowerCase().endsWith('.pdf'))return'pdf';return'text';}
function fileBase64(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',',2)[1]||'');reader.onerror=()=>reject(new Error(`Unable to read ${file.name}`));reader.readAsDataURL(file);});}
function mentionedFiles(){return [...$('prompt').value.matchAll(/@([^\s,;]+)/g)].map(match=>match[1]).slice(0,12);}
export function renderComposerItems(){const host=$('composer-items');const attachments=state.pendingAttachments.map((item,index)=>`<span class="composer-chip">${escapeHtml(item.name)} <small>${fmtBytes(item.size)}</small><button type="button" data-remove-attachment="${index}">x</button></span>`);const actions=state.pendingActions.map((item,index)=>`<span class="composer-chip action-chip">${escapeHtml(item.tool)}<button type="button" data-remove-action="${index}">x</button></span>`);const mentions=mentionedFiles().map(path=>`<span class="composer-chip mention-chip">@${escapeHtml(path)}</span>`);host.innerHTML=[...attachments,...actions,...mentions].join('');host.classList.toggle('hidden',!host.innerHTML);host.querySelectorAll('[data-remove-attachment]').forEach(button=>button.onclick=()=>{state.pendingAttachments.splice(Number(button.dataset.removeAttachment),1);renderComposerItems();});host.querySelectorAll('[data-remove-action]').forEach(button=>button.onclick=()=>{state.pendingActions.splice(Number(button.dataset.removeAction),1);renderComposerItems();});}
export async function addAttachments(files){const selected=[...files];if(state.pendingAttachments.length+selected.length>8)throw new Error('A maximum of 8 attachments is allowed');for(const file of selected){const kind=attachmentKind(file),limit=LIMITS[kind];if(file.size>limit)throw new Error(`${file.name} exceeds the ${fmtBytes(limit)} ${kind} limit`);state.pendingAttachments.push({name:file.name,media_type:file.type||'text/plain',data_base64:await fileBase64(file),size:file.size});}renderComposerItems();}
function actionTemplate(tool){return({execute_command:{command:'python -m pytest -q'},git:{operation:'status'},search_files:{query:'',pattern:'*.ts'},create_file:{path:'',content:''},write_file:{path:'',content:''},edit_file:{path:'',old_text:'',new_text:''},move_file:{source:'',destination:''},copy_file:{source:'',destination:''}})[tool]||{path:''};}
export function openActionDialog(){if(!$('project-select').value){$('route-status').textContent='Select a project before adding actions';return;}$('action-arguments').value=JSON.stringify(actionTemplate($('action-tool').value),null,2);$('action-purpose').value='';$('action-error').classList.add('hidden');$('action-dialog').showModal();}
export function addStructuredAction(event){event.preventDefault();try{if(state.pendingActions.length>=30)throw new Error('A maximum of 30 actions is allowed');const args=JSON.parse($('action-arguments').value);if(!args||Array.isArray(args)||typeof args!=='object')throw new Error('Arguments must be a JSON object');state.pendingActions.push({tool:$('action-tool').value,arguments:args,approved:false,purpose:$('action-purpose').value.trim()});$('action-dialog').close();renderComposerItems();}catch(error){$('action-error').textContent=error.message;$('action-error').classList.remove('hidden');}}

function showApproval(request,error){state.pendingApprovalRequest={...request,actions:request.actions.map(action=>({...action})),approvalIndexes:(error.pending_approvals||[]).map(item=>Number(item.index)).filter(Number.isInteger)};$('approval-list').innerHTML=(error.pending_approvals||[]).map(item=>`<div class="approval-item"><b>${escapeHtml(item.tool)}</b><span>${escapeHtml(item.purpose||'Requested by the agent')}</span><pre>${escapeHtml(JSON.stringify(item.arguments||{},null,2))}</pre></div>`).join('')||'<p>No approval details were returned.</p>';$('approval-dialog').showModal();}
function fallbackStatus(data){if(data.reason==='EXACT_CACHE_HIT')return'Completed - answered by Local Intelligence cache';const winner=(data.fallback_trace||[]).find((item,index)=>index>0&&item.status==='success');return winner?`Completed - recovered with ${winner.provider}${winner.model?` / ${winner.model}`:''}`:'Completed';}
function resizePrompt(){const prompt=$('prompt');prompt.style.height='auto';prompt.style.height=`${Math.min(prompt.scrollHeight,220)}px`;}
function failureTitle(error){if(error.code==='AI_EXECUTION_ERROR')return'**AI response unavailable**';if(error.code==='PROJECT_REQUIRED')return'**Project folder required**';if(error.code==='ACTION_FAILED')return'**Action failed**';return'**The request could not be completed**';}

function newProgressId(){return `zv-${crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;}

function streamError(payload = {}) {
  const error = new Error(payload.message || 'Gateway stream failed');
  Object.assign(error, payload, {streamTerminal:true});
  return error;
}

async function streamChat(payload, onEvent) {
  const controller = new AbortController();
  let idleTimer = setTimeout(() => controller.abort(), 35000);
  const resetIdleTimer = () => {
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => controller.abort(), 35000);
  };
  let lastSequence = 0;
  try {
    const base = window.ZEVORA_GATEWAY_URL || window.location.origin;
    const response = await fetch(base + '/api/chat/stream', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload), signal:controller.signal,
    });
    if (!response.ok || !response.body || !response.headers.get('content-type')?.includes('text/event-stream')) {
      throw new Error(`Realtime workflow unavailable (HTTP ${response.status})`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let final = null;
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      resetIdleTimer();
      buffer += decoder.decode(value, {stream:true}).replace(/\r\n/g, '\n');
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const data = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
        if (!data) continue;
        const event = JSON.parse(data);
        resetIdleTimer();
        if (event.type === 'workflow') {
          if (event.sequence && event.sequence <= lastSequence) continue;
          lastSequence = Math.max(lastSequence, event.sequence || 0);
          onEvent?.(event);
        }
        if (event.type === 'error') throw streamError(event.error);
        if (event.type === 'final') final = event.data;
      }
    }
    if (!final) throw new Error('Realtime workflow ended before the final response');
    return final;
  } finally {
    clearTimeout(idleTimer);
  }
}

function watchProgress(requestId, message){
  let stopped = false;
  let timer = null;
  let sequence = 0;
  const events = [];
  const poll = async () => {
    if (stopped) return;
    try {
      const progress = await api(`/api/chat/progress/${encodeURIComponent(requestId)}?after=${sequence}`);
      for (const event of progress.events || []) {
        if (event.sequence <= sequence) continue;
        sequence = event.sequence;
        events.push(event);
      }
      message.setWorkflowProgress?.({...progress, events});
      if (['completed','failed','cancelled'].includes(progress.status)) return;
    } catch (_) {
      // The initial poll can race request registration; retry while the chat call runs.
    }
    if (!stopped) timer = setTimeout(poll, 500);
  };
  poll();
  return () => { stopped = true; if (timer) clearTimeout(timer); };
}

export async function regenerateResponse(content, meta, message, originalText) {
  if (!content || !meta?.chat_id || !meta?.message_id || !message || state.isSending) return;
  if (!state.gatewayReady && !await checkGateway()) { $('route-status').textContent = 'Gateway offline'; return; }
  state.isSending = true; syncComposerState();
  const bubble = message.querySelector('.message-bubble');
  if (bubble) bubble.innerHTML = '<div class="message-body"><span class="typing-copy">Regenerating…</span><span class="typing-dots" aria-label="Regenerating response"><i></i><i></i><i></i></span></div>';
  try {
    const data = await api(`/api/chats/${encodeURIComponent(meta.chat_id)}/messages/${meta.message_id}/regenerate`, {
      method: 'POST',
      body: JSON.stringify({
        content, mode: $('routing-override')?.value || 'auto',
        provider: $('routing-provider')?.value || null, model: $('routing-model')?.value || null,
        attachments: [], actions: [],
      }),
    });
    replaceAssistantMessage(message, data.response, {...meta, ...data, regenerate_content: content});
    $('route-status').textContent = fallbackStatus(data);
  } catch (error) {
    replaceAssistantMessage(message, originalText, meta);
    $('route-status').textContent = `Regenerate failed - ${userErrorMessage(error)}`;
  } finally {
    state.isSending = false; syncComposerState(); $('prompt').focus();
  }
}

configureMessageActions({regenerate: regenerateResponse});

async function routeCodingPrompt(content) {
  if (location.pathname === '/filesystem' || !content) return;
  try {
    const decision = await api(`/api/route?prompt=${encodeURIComponent(content)}`);
    const taskTypes = new Set(decision.task_type || []);
    const tools = decision.tools || [];
    const codingRequest = taskTypes.has('coding')
      || taskTypes.has('debugging')
      || taskTypes.has('tool_task')
      || tools.some(tool => tool === 'filesystem.read' || tool === 'terminal.execute' || tool === 'project.create');
    if (codingRequest) await navigate('/filesystem');
  } catch (_) {
    // Navigation is an enhancement; the canonical chat request remains available.
  }
}

export async function send(replay=null){
  const content=replay?.content||$('prompt').value.trim();
  if(!content||state.isSending)return;
  await routeCodingPrompt(content);
  if(!state.gatewayReady&&!await checkGateway()){$('route-status').textContent='Gateway offline';return;}
  const request=replay||{content,attachments:state.pendingAttachments.map(({name,media_type,data_base64})=>({name,media_type,data_base64})),actions:state.pendingActions.map(action=>({...action}))};
  state.isSending=true;syncComposerState();let userMessage=null,waiting=null,stopProgress=()=>{};
  try{
    if(!state.activeChat)await newChat();
    const projectId=$('project-select').value||null;
    const requestId=newProgressId();activeRequestId=requestId;syncComposerState();
    if(!request.retrying)userMessage=appendMessage('user',content,{attachments:request.attachments});
    $('prompt').value='';resizePrompt();
    const activity=request.actions.length?'Running workspace actions':'Generating response';
    $('route-status').textContent=request.actions.length?'Step 2 of 3 - Running actions':'Generating response';
    if(waiting)waiting.setTypingStatus(activity);else waiting=appendMessage('assistant',activity,{typing:true});
    const payload={message:content,request_id:requestId,conversation_id:state.activeChat,project_id:projectId,mode:$('routing-override')?.value||'auto',provider:$('routing-provider')?.value||null,model:$('routing-model')?.value||null,attachments:request.attachments,actions:request.actions};
    let data;
    try {
      data=await streamChat(payload,event=>waiting.setWorkflowEvent?.(event));
    } catch (streamFailure) {
      if (streamFailure.streamTerminal) throw streamFailure;
      $('route-status').textContent='Realtime connection interrupted - recovering response';
      stopProgress=watchProgress(requestId,waiting);
      data=await api('/api/chat',{method:'POST',body:JSON.stringify(payload)});
    }
    stopProgress();state.activeChat=data.conversation_id;replaceAssistantMessage(waiting,data.response,{...data,regenerate_content:content});waiting.classList.remove('is-typing');
    state.pendingAttachments=[];state.pendingActions=[];state.pendingApprovalRequest=null;renderComposerItems();
    $('route-status').textContent=data.reason==='TOOLS_EXECUTED'?'Completed - changes were written to the selected folder':fallbackStatus(data);
    window.dispatchEvent(new CustomEvent('zevora:workflow-complete', {detail:data}));
    await refreshSidebarChats();
  }catch(error){
    stopProgress();waiting?.remove();
    const readable={PROJECT_REQUIRED:'Open a project folder first. The agent cannot access drive files from chat-only mode.',ACTION_FAILED:'The requested action failed. No success was reported.',AI_EXECUTION_ERROR:error.message||'No configured AI model was able to respond.'};
    const explanation=readable[error.code]||userErrorMessage(error);
    $('route-status').textContent=error.code==='APPROVAL_REQUIRED'?'Waiting for your approval':`Stopped - ${explanation}`;
    if(error.code==='APPROVAL_REQUIRED'){
      userMessage?.remove();$('prompt').value=content;resizePrompt();showApproval(request,error);
    }else{
      if(!userMessage&&!request.retrying)appendMessage('user',content,{attachments:request.attachments});
      const errorMessage=appendMessage('assistant',`${failureTitle(error)}\n\n${explanation}`,{error:true,fallback_trace:error.fallback_trace||[],retry:()=>{errorMessage.remove();send({...request,retrying:true});}});
      if(error.code==='PROJECT_REQUIRED')$('project-dialog').showModal();
      if(!error.code){state.gatewayReady=false;await checkGateway();}
    }
  }finally{stopProgress();activeRequestId=null;state.isSending=false;syncComposerState();renderComposerItems();$('prompt').focus();}
}

async function cancelActiveRequest(){
  if(!activeRequestId)return;
  const requestId=activeRequestId;
  $('route-status').textContent='Stopping request';
  try{await api(`/api/chat/cancel/${encodeURIComponent(requestId)}`,{method:'POST'});}
  catch(error){$('route-status').textContent=`Stop failed - ${userErrorMessage(error)}`;}
}
export async function approvePendingActions(event){event.preventDefault();if(!state.pendingApprovalRequest)return;const indexes=new Set(state.pendingApprovalRequest.approvalIndexes||[]);state.pendingApprovalRequest.actions=state.pendingApprovalRequest.actions.map((action,index)=>({...action,approved:action.approved||indexes.has(index)}));const{approvalIndexes,...replay}=state.pendingApprovalRequest;$('approval-dialog').close();state.pendingApprovalRequest=null;await send(replay);}

async function refreshRoutingSelectors(){const mode=$('routing-override');if(!mode)return;const models=await api('/api/models').catch(()=>[]),providers=[...new Set(models.map(item=>item.provider))];$('routing-provider').innerHTML=providers.map(item=>`<option>${escapeHtml(item)}</option>`).join('');const sync=()=>{$('routing-model').innerHTML=models.filter(item=>item.provider===$('routing-provider').value).map(item=>`<option value="${escapeHtml(item.model_id)}">${escapeHtml(item.model_id)}</option>`).join('');};$('routing-provider').onchange=sync;sync();mode.onchange=()=>{const explicit=['provider','model'].includes(mode.value);$('routing-provider').classList.toggle('hidden',!explicit);$('routing-model').classList.toggle('hidden',mode.value!=='model');};mode.onchange();}
export function renderChat(){ $('composer').classList.remove('hidden');refreshRoutingSelectors();$('chat-title').textContent=state.activeChat?'Chat':'What are you building?';if(!state.activeChat){setMessages(`<div class="empty">${stateIndicator('local','Local workspace')}<b>ZEVORA</b><p>Open a project folder, then ask the agent to create, edit, inspect, or test files.</p><div class="actions"><button id="chat-open-project">Open folder</button><button id="chat-create-project">Create project</button></div><a class="empty-docs" href="/docs" data-route>Read the quick start</a></div>`);$('chat-open-project').onclick=()=>$('project-dialog').showModal();$('chat-create-project').onclick=()=>$('create-dialog').showModal();}syncWorkspaceAccess();}

export function wireChatEvents(){ $('project-select').onchange=()=>{beginProjectSelection();syncWorkspaceAccess();};$('composer').onsubmit=event=>{event.preventDefault();send();};$('stop-request').onclick=cancelActiveRequest;$('prompt').oninput=()=>{renderComposerItems();resizePrompt();};$('prompt').onkeydown=event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send();}};resizePrompt();$('attach-file').onclick=()=>$('file-input').click();$('file-input').onchange=async event=>{try{await addAttachments(event.target.files);}catch(error){$('route-status').textContent=userErrorMessage({code:'INVALID_ATTACHMENT',message:error.message});}finally{event.target.value='';}};$('add-action').onclick=openActionDialog;$('action-tool').onchange=event=>{$('action-arguments').value=JSON.stringify(actionTemplate(event.target.value),null,2);};$('confirm-add-action').onclick=addStructuredAction;$('approve-actions').onclick=approvePendingActions;$('reject-actions').onclick=()=>{state.pendingApprovalRequest=null;};}

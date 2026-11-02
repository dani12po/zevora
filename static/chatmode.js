import {$, api, state, userErrorMessage} from './core.js?v=20260819-3';
import {appendMessage, replaceAssistantMessage} from './chats.js?v=20260819-3';
import {syncWorkspaceAccess} from './chat.js?v=20260819-3';

export const CHAT_MODES = new Set(['ask', 'auto', 'coding']);
export const MODE_PLACEHOLDERS = {
  ask: 'Ask anything — pure Q&A, files are never touched',
  auto: 'Example: Create contoh.html with a simple personal profile page',
  coding: 'Describe the change — select a folder first for file actions',
};
export const SLASH_COMMANDS = {'/ask': {mode: 'ask'}, '/coding': {mode: 'coding'}};

export function getChatMode() { return CHAT_MODES.has(state.chatMode) ? state.chatMode : 'auto'; }

export function setChatMode(mode) {
  state.chatMode = CHAT_MODES.has(mode) ? mode : 'auto';
  try { localStorage.setItem('zevora.chat.mode', state.chatMode); } catch (_) {}
  document.querySelectorAll('[data-chat-mode]').forEach(b => b.classList.toggle('active', b.dataset.chatMode === state.chatMode));
  const prompt = $('prompt'); if (prompt) prompt.placeholder = MODE_PLACEHOLDERS[state.chatMode];
  syncWorkspaceAccess();
}

export function parseSlashCommand(raw) {
  const text = (raw || '').trim();
  if (!text.startsWith('/')) return {kind: 'send', mode: null, content: raw};
  const space = text.indexOf(' ');
  const command = (space < 0 ? text : text.slice(0, space)).toLowerCase();
  const rest = space < 0 ? '' : text.slice(space + 1).trim();
  if (command === '/help') return {kind: 'local', markdown: '**Slash commands**\n\n- `/ask …` — pure Q&A, never touches files\n- `/coding …` — workspace agent flow (needs a selected folder)\n- `/skills` — list available skills\n- `/help` — this list'};
  if (command === '/skills') return {kind: 'skills'};
  const known = SLASH_COMMANDS[command];
  if (known) return {kind: 'send', mode: known.mode, content: rest};
  return {kind: 'send', mode: null, content: raw};
}

export async function renderSkillsMessage() {
  const message = appendMessage('assistant', 'Loading skills…', {typing: true});
  try {
    const info = await api('/api/intelligence');
    const basic = info?.basic_skills?.allowed || [];
    const dynamic = (info?.skills || []).map(s => s.skill_id || s.name).filter(Boolean);
    const lines = ['**Skills**'];
    lines.push(basic.length ? `- Built-in: ${basic.join(', ')}` : '- Built-in: none enabled');
    lines.push(dynamic.length ? `- Custom: ${dynamic.join(', ')}` : '- Custom: none registered');
    lines.push('\nUse `/ask` for Q&A or `/coding` for file work.');
    replaceAssistantMessage(message, lines.join('\n'), {});
  } catch (error) {
    replaceAssistantMessage(message, `Could not load skills - ${userErrorMessage(error)}`, {error: true});
  }
}

export async function routeCodingPrompt(content, chatMode) {
  if (!content) return {coding: false, workspace: false, route: null, task_types: [], tools: []};
  if (chatMode === 'ask') return {coding: false, workspace: false, route: null, task_types: ['general_chat'], tools: []};
  if (chatMode === 'coding') {
    const hasProject = Boolean($('project-select').value);
    return {coding: true, workspace: hasProject, route: hasProject ? '/filesystem' : null, task_types: ['coding'], tools: ['filesystem.read']};
  }
  try {
    const decision = await api(`/api/route?prompt=${encodeURIComponent(content)}`);
    const taskTypes = new Set(decision.task_type || []);
    const tools = decision.tools || [];
    const codingRequest = taskTypes.has('coding') || taskTypes.has('debugging') || taskTypes.has('tool_task') || tools.some(t => t === 'filesystem.read' || t === 'terminal.execute' || t === 'project.create');
    const needsWorkspace = tools.length > 0;
    return {coding: codingRequest, workspace: codingRequest && needsWorkspace && Boolean($('project-select').value), route: codingRequest && needsWorkspace ? '/filesystem' : null, task_types: [...taskTypes], tools};
  } catch (_) { /* classification is an enhancement; chat stays available */ }
  return {coding: false, workspace: false, route: null, task_types: [], tools: []};
}

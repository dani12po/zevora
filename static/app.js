import {$, api, navigate, registerRoutes, render, setSidebarOpen} from './core.js?v=20260818-11';
import {checkGateway, createProject, loadProject, pickProject, refreshProjects, renderChat, renderComposerItems, syncWorkspaceAccess, wireChatEvents} from './chat.js?v=20260818-12';
import {confirmRenameChat, newChat, refreshSidebarChats, renderChatVault} from './chats.js?v=20260818-12';
import {wireMarkdownActions} from './markdown.js?v=20260818-12';
import {renderDocs} from './docs.js?v=20260818-10';
import {renderProviders} from './providers.js?v=20260818-10';
import {renderLocalAI} from './local-ai.js?v=20260818-10';
import {renderModelRouter} from './model-router.js?v=20260818-10';
import {renderMCP} from './mcp.js?v=20260818-10';
import {configureTerminal, renderTerminal} from './terminal.js?v=20260818-10';
import {renderFilesystem} from './filesystem.js?v=20260818-10';
import {renderMemory} from './memory.js?v=20260818-10';
import {renderCache} from './cache.js?v=20260818-10';
import {renderUsage} from './usage.js?v=20260818-10';
import {renderSettings} from './settings.js?v=20260818-10';

export const ROUTES = {
  '/': renderChat,
  '/chats': renderChatVault,
  '/docs': renderDocs,
  '/providers': renderProviders,
  '/local-ai': renderLocalAI,
  '/model-router': renderModelRouter,
  '/mcp': renderMCP,
  '/terminal': renderTerminal,
  '/filesystem': renderFilesystem,
  '/memory': renderMemory,
  '/cache': renderCache,
  '/usage': renderUsage,
  '/settings': renderSettings,
};

registerRoutes(ROUTES);
configureTerminal({navigateToChat: async () => {
  await navigate('/');
  renderComposerItems();
}});

function setChatSectionCollapsed(collapsed) {
  $('chat-section').classList.toggle('is-collapsed', collapsed);
  $('chat-section-toggle').setAttribute('aria-expanded', String(!collapsed));
  localStorage.setItem('zevora.sidebar.chatsCollapsed', String(collapsed));
}

function wireShellEvents() {
  $('chat-section-toggle').onclick = () => setChatSectionCollapsed(!$('chat-section').classList.contains('is-collapsed'));
  $('mobile-menu').onclick = () => setSidebarOpen(true);
  $('sidebar-close').onclick = () => setSidebarOpen(false);
  $('sidebar-scrim').onclick = () => setSidebarOpen(false);
  document.addEventListener('click', event => {
    const link = event.target.closest('[data-route]');
    if (!link) return;
    const href = link.getAttribute('href');
    if (!href || href.startsWith('http')) return;
    event.preventDefault();
    setSidebarOpen(false);
    navigate(href);
  });

  $('new-chat').onclick = newChat;
  $('open-project').onclick = () => $('project-dialog').showModal();
  $('create-project').onclick = () => $('create-dialog').showModal();
  $('open-folder-btn').onclick = () => $('project-dialog').showModal();
  $('composer-open-project').onclick = () => $('project-dialog').showModal();
  $('pick-project').onclick = pickProject;
  $('load-project').onclick = event => { event.preventDefault(); loadProject().catch(error => alert(error.message)); };
  $('confirm-create-project').onclick = event => { event.preventDefault(); createProject(); };
  $('confirm-rename-chat').onclick = confirmRenameChat;
  $('audit').onclick = async () => {
    const projectId = $('project-select').value;
    if (!projectId) return;
    const result = await api(`/api/projects/${projectId}/audit`, {method:'POST'});
    if ($('project-select').value !== projectId) return;
    const output = $('audit-result');
    output.classList.remove('hidden');
    output.textContent = `Audit - Health ${result.health_score}/100 - ${result.files_indexed} files - ${result.languages.join(', ') || 'Unknown'} - ${result.frameworks.join(', ') || 'No framework'}`;
  };
  document.addEventListener('keydown', event => {
    if (event.ctrlKey && event.key === 'Enter') { event.preventDefault(); $('composer').requestSubmit(); }
    if (event.ctrlKey && event.key.toLowerCase() === 'n') { event.preventDefault(); newChat(); }
  });
  wireChatEvents();
  wireMarkdownActions($('messages'));
}

setChatSectionCollapsed(localStorage.getItem('zevora.sidebar.chatsCollapsed') === 'true');
wireShellEvents();
syncWorkspaceAccess();
checkGateway();
setInterval(checkGateway, 30000);
Promise.allSettled([refreshProjects(), refreshSidebarChats()]);
render(location.pathname);

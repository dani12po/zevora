import {$, api, emptyState, escapeHtml, loadingState, setMessages, setPanel, state, userErrorMessage} from './core.js?v=20260818-11';

const READ_ONLY_EXTENSIONS = new Set(['png','jpg','jpeg','gif','webp','ico','pdf','zip','gz','tar','woff','woff2','ttf','exe','dll']);
let activePath = '';
let savedContent = '';
let activeRow = null;

export async function renderFilesystem() {
  const projectId = $('project-select').value;
  const workspaceHost = $('workspace-filesystem');
  if (!projectId) {
    const actions = '<div class="actions"><button id="filesystem-open-project">Open project</button></div>';
    const content = emptyState('No project open', 'Open a project to browse its files.', {kind:'local', actions});
    if (workspaceHost) workspaceHost.innerHTML = `<div class="workspace-placeholder">${content}</div>`;
    else setPanel('Filesystem', content);
    $('filesystem-open-project').onclick = () => $('project-dialog').showModal();
    return;
  }
  state.fsProjectId = projectId;
  if (workspaceHost) workspaceHost.innerHTML = loadingState('Loading project tree...', 'local');
  else setPanel('Filesystem', loadingState('Loading project tree...', 'local'));
  const data = await api(`/api/filesystem/tree?project_id=${projectId}`);
  if (state.fsProjectId !== projectId) return;
  const layout = document.createElement('div');
  layout.className = 'fs-layout route-enter';
  const treePane = document.createElement('div');
  treePane.className = 'fs-tree';
  treePane.id = 'fs-tree-pane';
  const preview = document.createElement('div');
  preview.className = 'fs-preview';
  preview.id = 'fs-preview';
  preview.innerHTML = '<span class="muted-copy">Select a file to edit or preview.</span>';
  layout.append(treePane, preview);
  if (workspaceHost) workspaceHost.replaceChildren(layout);
  else {
    setMessages('');
    $('messages').append(layout);
    $('composer').classList.add('hidden');
  }
  renderTree(data.tree, treePane, 0);
  if (activePath) {
    const row = treePane.querySelector(`[data-file-path="${CSS.escape(activePath)}"]`);
    if (row) await openFile(activePath, row);
    else resetEditorState();
  }
}

function renderTree(nodes, container, depth) {
  for (const node of nodes) {
    const row = document.createElement('div');
    row.className = 'tree-node';
    row.style.paddingLeft = `${8 + depth * 14}px`;
    const isDirectory = node.type === 'dir';
    if (!isDirectory) row.dataset.filePath = node.path;
    row.innerHTML = `<span class="tree-toggle">${isDirectory ? '&#9654;' : ''}</span><span class="tree-icon">${isDirectory ? '&#9633;' : fileIcon(node.name)}</span><span class="technical-text">${escapeHtml(node.name)}</span>`;
    container.append(row);
    if (isDirectory && node.children?.length) {
      const children = document.createElement('div');
      children.className = 'tree-children';
      children.style.display = 'none';
      renderTree(node.children, children, depth + 1);
      container.append(children);
      row.onclick = () => {
        const open = children.style.display !== 'none';
        children.style.display = open ? 'none' : 'block';
        row.querySelector('.tree-toggle').innerHTML = open ? '&#9654;' : '&#9660;';
      };
    } else if (!isDirectory) {
      row.onclick = () => openFile(node.path, row);
    }
  }
}

function fileIcon(name) {
  const extension = name.split('.').pop().toLowerCase();
  return {py:'PY',js:'JS',ts:'TS',json:'{}',md:'MD',html:'<>',css:'#',sh:'SH',yml:'Y',yaml:'Y',txt:'T',env:'E',toml:'T',sql:'DB',png:'IM',jpg:'IM',svg:'IM'}[extension] || 'F';
}

function resetEditorState() {
  activePath = '';
  savedContent = '';
  activeRow = null;
}

function isReadOnly(path, data) {
  const extension = path.split('.').pop().toLowerCase();
  return data.truncated || READ_ONLY_EXTENSIONS.has(extension) || data.content.includes('\u0000');
}

function lineNumbers(content) {
  const count = Math.max(1, content.split('\n').length);
  return Array.from({length: count}, (_, index) => index + 1).join('\n');
}

function syncDirtyState() {
  const editor = $('fs-editor');
  const dirty = Boolean(editor && !editor.readOnly && editor.value !== savedContent);
  $('fs-dirty')?.classList.toggle('hidden', !dirty);
  if ($('fs-save')) $('fs-save').disabled = !dirty;
  if ($('fs-lines') && editor) $('fs-lines').textContent = lineNumbers(editor.value);
}

function renderEditor(path, data) {
  const preview = $('fs-preview');
  const readOnly = isReadOnly(path, data);
  const warning = data.truncated ? 'This preview is truncated and read-only.' : (readOnly ? 'This file type is read-only.' : '');
  preview.innerHTML = `<section class="fs-editor-shell">
    <header class="fs-editor-header">
      <div class="fs-editor-title"><b>${escapeHtml(path)}</b><span id="fs-dirty" class="fs-dirty hidden">Modified</span></div>
      <div class="fs-editor-actions">
        <button id="fs-reload" class="icon-action" type="button" title="Reload file" aria-label="Reload file">↻</button>
        <button id="fs-save" class="icon-action" type="button" title="Save file" aria-label="Save file" disabled>▣</button>
      </div>
    </header>
    ${warning ? `<div class="warning-text fs-editor-warning">${escapeHtml(warning)}</div>` : ''}
    <div class="fs-editor-body">
      <pre id="fs-lines" class="fs-editor-lines" aria-hidden="true">${lineNumbers(data.content)}</pre>
      <textarea id="fs-editor" class="fs-editor-input" spellcheck="false" aria-label="File editor" ${readOnly ? 'readonly' : ''}></textarea>
    </div>
    <footer id="fs-editor-status" class="fs-editor-status">${readOnly ? 'Read only' : 'Ready'}</footer>
  </section>`;
  const editor = $('fs-editor');
  editor.value = data.content;
  savedContent = data.content;
  editor.addEventListener('input', syncDirtyState);
  editor.addEventListener('scroll', () => { $('fs-lines').scrollTop = editor.scrollTop; });
  editor.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      saveActiveFile();
    }
  });
  $('fs-reload').onclick = () => openFile(activePath, activeRow, {force:true});
  $('fs-save').onclick = saveActiveFile;
  syncDirtyState();
}

async function saveActiveFile() {
  const editor = $('fs-editor');
  if (!editor || editor.readOnly || !activePath || editor.value === savedContent) return;
  const status = $('fs-editor-status');
  status.textContent = 'Saving...';
  $('fs-save').disabled = true;
  try {
    const result = await api(`/api/projects/${state.fsProjectId}/files/write`, {
      method: 'PUT',
      body: JSON.stringify({path: activePath, content: editor.value}),
    });
    savedContent = editor.value;
    status.textContent = `Saved ${result.bytes} bytes`;
    syncDirtyState();
  } catch (error) {
    status.textContent = userErrorMessage(error, 'File could not be saved.');
    syncDirtyState();
  }
}

function hasDirtyEditor() {
  const editor = $('fs-editor');
  return Boolean(editor && !editor.readOnly && editor.value !== savedContent);
}

function workflowChangedFiles(detail = {}) {
  const observations = detail.agent_trace?.observations || [];
  return observations.some(item => String(item.tool || '').includes('file'));
}

window.addEventListener('zevora:workflow-complete', event => {
  if (location.pathname !== '/filesystem' || !workflowChangedFiles(event.detail) || hasDirtyEditor()) return;
  renderFilesystem().catch(() => {});
});

async function openFile(path, row, {force=false} = {}) {
  const editor = $('fs-editor');
  if (!force && activePath && activePath !== path && editor && editor.value !== savedContent) {
    const discard = window.confirm(`Discard unsaved changes to ${activePath}?`);
    if (!discard) return;
  }
  document.querySelectorAll('.fs-tree .tree-node.active').forEach(node => node.classList.remove('active'));
  row?.classList.add('active');
  activePath = path;
  activeRow = row;
  const preview = $('fs-preview');
  preview.innerHTML = loadingState('Loading file...', 'local');
  try {
    const data = await api(`/api/filesystem/file?project_id=${state.fsProjectId}&path=${encodeURIComponent(path)}`);
    renderEditor(path, data);
  } catch (error) {
    preview.innerHTML = `<span class="error-text">${escapeHtml(userErrorMessage(error, 'File could not be opened.'))}</span>`;
  }
}

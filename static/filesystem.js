import {$, api, emptyState, escapeHtml, loadingState, setMessages, setPanel, state} from './core.js?v=20260818-7';

export async function renderFilesystem() {
  const projectId = $('project-select').value;
  if (!projectId) {
    const actions = '<div class="actions"><button id="filesystem-open-project">Open project</button></div>';
    setPanel('Filesystem', emptyState('No project open', 'Open a project to browse its files.', {kind:'local', actions}));
    $('filesystem-open-project').onclick = () => $('project-dialog').showModal();
    return;
  }
  state.fsProjectId = projectId;
  setPanel('Filesystem', loadingState('Loading project tree...', 'local'));
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
  preview.innerHTML = '<span class="muted-copy">Click a file to preview</span>';
  layout.append(treePane, preview);
  setMessages('');
  $('messages').append(layout);
  $('composer').classList.add('hidden');
  renderTree(data.tree, treePane, 0);
}

function renderTree(nodes, container, depth) {
  for (const node of nodes) {
    const row = document.createElement('div');
    row.className = 'tree-node';
    row.style.paddingLeft = `${8 + depth * 14}px`;
    const isDirectory = node.type === 'dir';
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
      row.onclick = () => previewFile(node.path, row);
    }
  }
}

function fileIcon(name) {
  const extension = name.split('.').pop().toLowerCase();
  return {py:'PY',js:'JS',ts:'TS',json:'{}',md:'MD',html:'<>',css:'#',sh:'SH',yml:'Y',yaml:'Y',txt:'T',env:'E',toml:'T',sql:'DB',png:'IM',jpg:'IM',svg:'IM'}[extension] || 'F';
}

async function previewFile(path, row) {
  document.querySelectorAll('.fs-tree .tree-node.active').forEach(node => node.classList.remove('active'));
  row.classList.add('active');
  const preview = $('fs-preview');
  preview.innerHTML = loadingState('Loading file...', 'local');
  try {
    const data = await api(`/api/filesystem/file?project_id=${state.fsProjectId}&path=${encodeURIComponent(path)}`);
    preview.innerHTML = `${data.truncated ? '<div class="warning-text">File truncated at 200 KB</div>' : ''}<pre>${escapeHtml(data.content)}</pre>`;
  } catch (error) {
    preview.innerHTML = `<span class="error-text">Error: ${escapeHtml(error.message)}</span>`;
  }
}

// First-run onboarding wizard — three steps: welcome, folder (optional), first chat.
// Shows once; dismissal is stored in localStorage so returning users never see it again.
import {$, api, navigate} from './core.js?v=20261103-2';
import {pickProject, refreshProjects} from './chat.js?v=20261103-2';
import {newChat} from './chats.js?v=20261103-2';

const ONBOARDING_KEY = 'zevora.onboarding.done';

export async function maybeShowOnboarding() {
  try { if (localStorage.getItem(ONBOARDING_KEY) === 'true') return; } catch (_) { return; }
  let projects = [];
  try { projects = await api('/api/projects'); } catch (_) { return; }
  if (projects.length) { markDone(); return; } // already set up
  showWizard();
}

function markDone() { try { localStorage.setItem(ONBOARDING_KEY, 'true'); } catch (_) {} }

function showWizard() {
  if ($('onboarding-dialog')) { $('onboarding-dialog').showModal(); return; }
  const dialog = document.createElement('dialog');
  dialog.id = 'onboarding-dialog';
  dialog.innerHTML = `
    <div class="onboarding-body">
      <h2>Welcome to ZEVORA 🐴</h2>
      <p class="technical-text">Your private AI coding workspace. Everything stays on this machine.</p>
      <ol class="onboarding-steps">
        <li><b>Optional:</b> connect a project folder so the AI can read your code.</li>
        <li>Just start chatting — the local model works offline, no API key needed.</li>
        <li>Add a cloud provider later in <b>Providers</b> for complex tasks.</li>
      </ol>
      <div class="onboarding-actions">
        <button id="onboarding-pick" class="btn-sm" type="button">Connect folder</button>
        <button id="onboarding-chat" class="btn-sm primary" type="button">Just start chatting</button>
      </div>
    </div>`;
  document.body.appendChild(dialog);
  dialog.querySelector('#onboarding-pick').onclick = async () => {
    markDone(); dialog.close();
    const result = await pickProject();
    if (result && !result.cancelled) navigate('/');
  };
  dialog.querySelector('#onboarding-chat').onclick = async () => {
    markDone(); dialog.close();
  };
  dialog.addEventListener('cancel', () => markDone());
  dialog.showModal();
}

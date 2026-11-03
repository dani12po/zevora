// Scheduled tasks page — list, create, toggle, delete, and run ZEVORA automations.
import {$, api, escapeHtml, loadingState, pageWrap, setMessages} from './core.js?v=20260819-3';

const KIND_LABELS = {
  once: 'Once (ISO time)',
  daily: 'Daily (HH:MM UTC)',
  weekly: 'Weekly (DDD:HH:MM UTC)',
  interval: 'Every N minutes',
};

export async function renderSchedules() {
  setMessages(pageWrap(`
    <section class="panel-content"><div class="page">
      <div class="page-header"><h2>Scheduled Tasks</h2>
        <button id="new-schedule" class="btn-sm" type="button">New task</button></div>
      <p class="technical-text">Automations that run a prompt on a schedule while ZEVORA is running.
      Times are UTC.</p>
      <div id="schedule-list">${loadingState('Loading tasks...', 'local')}</div>
      <div id="schedule-form-holder"></div>
    </div></section>`));
  $('new-schedule').onclick = showScheduleForm;
  await loadSchedules();
}

async function loadSchedules() {
  const container = $('schedule-list');
  if (!container) return;
  const tasks = await api('/api/schedules');
  if (!tasks.length) {
    container.innerHTML = `<div class="empty empty-state-compact"><b>No scheduled tasks</b>
      <p>Create one to run a prompt every day, week, or on an interval.</p></div>`;
    return;
  }
  container.innerHTML = tasks.map(task => `
    <div class="vault-row schedule-row" data-task-id="${escapeHtml(String(task.id))}">
      <div class="schedule-info">
        <b>${escapeHtml(task.name)}</b>
        <span class="technical-text">${escapeHtml(KIND_LABELS[task.schedule_kind] || task.schedule_kind)}${task.schedule_value ? ' · ' + escapeHtml(task.schedule_value) : ''}</span>
        <span class="technical-text">${task.enabled ? 'Next: ' + escapeHtml((task.next_run_at || '—').replace('T', ' ').slice(0, 16)) : 'Paused'}</span>
      </div>
      <div class="vault-actions">
        <button class="btn-sm run-now" type="button">Run now</button>
        <button class="btn-sm toggle-task" type="button">${task.enabled ? 'Pause' : 'Resume'}</button>
        <button class="btn-sm danger delete-task" type="button">Delete</button>
      </div>
    </div>`).join('');

  container.querySelectorAll('.schedule-row').forEach(row => {
    const id = row.dataset.taskId;
    row.querySelector('.run-now').onclick = () => runNow(id, row);
    row.querySelector('.toggle-task').onclick = () => toggleTask(id, row);
    row.querySelector('.delete-task').onclick = async () => {
      if (!confirm('Delete this scheduled task?')) return;
      await api(`/api/schedules/${id}`, {method: 'DELETE'});
      await loadSchedules();
    };
  });
}

async function runNow(id, row) {
  const status = row.querySelector('.technical-text');
  const original = status.textContent;
  status.textContent = 'Running...';
  try {
    const result = await api(`/api/schedules/${id}/run-now`, {method: 'POST'});
    status.textContent = result.status === 'success'
      ? `Done: ${String(result.result || '').slice(0, 80)}`
      : `Failed: ${String(result.result || '').slice(0, 80)}`;
  } catch (error) {
    status.textContent = 'Run failed';
  }
  setTimeout(() => { if (row.isConnected) status.textContent = original; }, 6000);
}

async function toggleTask(id, row) {
  const current = row.querySelector('.toggle-task').textContent === 'Pause';
  await api(`/api/schedules/${id}`, {method: 'PATCH', body: JSON.stringify({enabled: !current})});
  await loadSchedules();
}

function showScheduleForm() {
  const holder = $('schedule-form-holder');
  if (!holder || holder.querySelector('form')) return;
  holder.innerHTML = `
    <form id="schedule-form" class="schedule-form">
      <h3>New scheduled task</h3>
      <label>Name<input id="sched-name" required maxlength="200" placeholder="Morning repo digest"></label>
      <label>Prompt<textarea id="sched-prompt" required maxlength="8000" rows="3" placeholder="What should ZEVORA do on each run?"></textarea></label>
      <label>Schedule
        <select id="sched-kind">
          <option value="daily">Daily</option>
          <option value="weekly">Weekly</option>
          <option value="interval">Interval</option>
          <option value="once">Once</option>
        </select>
      </label>
      <label id="sched-value-label">Time (HH:MM UTC)<input id="sched-value" placeholder="08:00"></label>
      <div class="onboarding-actions">
        <button type="button" class="btn-sm" id="sched-cancel">Cancel</button>
        <button type="submit" class="btn-sm primary">Create task</button>
      </div>
    </form>`;
  const kindSelect = $('sched-kind');
  kindSelect.onchange = () => {
    $('sched-value-label').firstChild.textContent = `${KIND_LABELS[kindSelect.value]}\n`;
    $('sched-value').placeholder = kindSelect.value === 'weekly' ? 'mon:09:00'
      : kindSelect.value === 'interval' ? '60' : kindSelect.value === 'once'
        ? '2026-12-01T08:00:00+00:00' : '08:00';
  };
  $('sched-cancel').onclick = () => { holder.innerHTML = ''; };
  $('schedule-form').onsubmit = async event => {
    event.preventDefault();
    try {
      await api('/api/schedules', {
        method: 'POST',
        body: JSON.stringify({
          name: $('sched-name').value.trim(),
          prompt: $('sched-prompt').value.trim(),
          schedule_kind: kindSelect.value,
          schedule_value: $('sched-value').value.trim(),
        }),
      });
      holder.innerHTML = '';
      await loadSchedules();
    } catch (error) {
      alert(userMessage(error));
    }
  };
}

function userMessage(error) {
  try {
    const payload = JSON.parse(error.message || '{}');
    return payload.error?.message || error.message || 'Could not save task';
  } catch (_) {
    return error.message || 'Could not save task';
  }
}

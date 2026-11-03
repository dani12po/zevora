import {$, api, escapeHtml, pageWrap, setPanel, userErrorMessage} from './core.js?v=20261103-2';

export async function renderSettings() {
  const [settings, tg] = await Promise.all([
    api('/api/settings'),
    api('/api/telegram/config').catch(() => null),
  ]);

  setPanel('Settings', pageWrap('<h2>Settings</h2>', `

    <!-- ── Routing ── -->
    <form id="settings-form">
      <div class="card settings-card">
        <div class="settings-section">
          <h3>Routing</h3>
          <div class="settings-row">
            <label for="s-routing-mode">Routing mode</label>
            <select id="s-routing-mode">
              <option value="AUTO"              ${settings.routing_mode === 'AUTO'              ? 'selected' : ''}>AUTO — local-first or cloud-first by task</option>
              <option value="LOCAL_ONLY"        ${settings.routing_mode === 'LOCAL_ONLY'        ? 'selected' : ''}>LOCAL ONLY — never call cloud providers</option>
              <option value="REMOTE_LOCAL_ONLY" ${settings.routing_mode === 'REMOTE_LOCAL_ONLY' ? 'selected' : ''}>REMOTE LOCAL ONLY — remote Lexi server only</option>
              <option value="CLOUD_ONLY"        ${settings.routing_mode === 'CLOUD_ONLY'        ? 'selected' : ''}>CLOUD ONLY — never load the local model</option>
            </select>
          </div>
          <div class="toggle-row">
            <label>Cloud fallback (retry with another provider on failure)</label>
            <label class="toggle"><input type="checkbox" id="s-cloud-fallback" ${settings.cloud_fallback ? 'checked' : ''}><span class="toggle-slider"></span></label>
          </div>
          <div class="toggle-row">
            <label>Cost optimization (prefer cheaper capable providers)</label>
            <label class="toggle"><input type="checkbox" id="s-cost-opt" ${settings.cost_optimization ? 'checked' : ''}><span class="toggle-slider"></span></label>
          </div>
        </div>
      </div>
      <div class="card settings-card">
        <div class="settings-section">
          <h3>Gateway</h3>
          <div class="settings-row">
            <label>Gateway URL</label>
            <input class="technical-text" value="${escapeHtml(settings.gateway_url)}" disabled>
          </div>
        </div>
      </div>
      <div class="settings-actions">
        <button type="submit" class="primary">Save changes</button>
        <span id="settings-save-msg" class="save-msg"></span>
      </div>
    </form>

    <!-- ── Telegram ── -->
    <div class="card settings-card" id="telegram-card">
      <div class="settings-section">
        <div class="tg-header">
          <div>
            <h3>Telegram Bot</h3>
            <p class="tg-subtitle">Connect a Telegram bot so you can chat with ZEVORA from your phone.
            No need to edit <code>.env</code> — everything is saved here.</p>
          </div>
          <span id="tg-status-badge" class="tg-badge ${tg?.bot_token_set ? 'tg-badge-ok' : 'tg-badge-off'}">
            ${tg?.bot_token_set ? 'Configured' : 'Not configured'}
          </span>
        </div>

        ${tg?.bot_token_set ? `
        <div class="tg-current">
          <div class="tg-info-row">
            <span class="tg-label">Bot token</span>
            <span class="technical-text">${escapeHtml(tg.bot_token_masked || '••••••')}</span>
          </div>
          <div class="tg-info-row">
            <span class="tg-label">Gateway token</span>
            <span class="technical-text">${tg.gateway_token_set ? escapeHtml(tg.gateway_token_masked || '••••') : '<span class="tg-warn">Not set — generate one below</span>'}</span>
          </div>
          <div class="tg-info-row">
            <span class="tg-label">Gateway URL</span>
            <span class="technical-text">${escapeHtml(tg.gateway_url || '')}</span>
          </div>
          ${tg.allowed_users?.length ? `
          <div class="tg-info-row">
            <span class="tg-label">Allowed users</span>
            <span class="technical-text">@${tg.allowed_users.map(escapeHtml).join(', @')}</span>
          </div>` : ''}
        </div>` : ''}

        <details class="tg-setup" ${tg?.bot_token_set ? '' : 'open'}>
          <summary>${tg?.bot_token_set ? 'Edit configuration' : 'Set up Telegram bot'}</summary>
          <div class="tg-setup-guide">
            <b>Quick setup (2 minutes)</b>
            <ol>
              <li>Open Telegram → search <b>@BotFather</b> → send <code>/newbot</code></li>
              <li>Copy the token (looks like <code>123456:ABC-...</code>) → paste below</li>
              <li>Click <b>Generate gateway token</b> (auto-creates a secure token)</li>
              <li>Click <b>Save &amp; apply</b></li>
              <li>Start the gateway process:<br>
                <code class="tg-cmd">python scripts/telegram_gateway.py</code></li>
              <li>Send <code>/start</code> to your bot in Telegram — done!</li>
            </ol>
          </div>

          <form id="tg-form" class="tg-form">
            <div class="tg-field">
              <label for="tg-bot-token">Bot token <span class="tg-required">*</span></label>
              <input id="tg-bot-token" type="password" autocomplete="new-password"
                placeholder="123456:ABC-DefGhi..." maxlength="200">
              <small>From @BotFather. Leave blank to keep the existing token.</small>
            </div>

            <div class="tg-field">
              <label for="tg-gateway-token">Gateway token</label>
              <div class="tg-token-row">
                <input id="tg-gateway-token" type="text" class="technical-text"
                  placeholder="Auto-generate or paste your own" maxlength="100"
                  value="${escapeHtml(tg?.gateway_token_masked || '')}">
                <button type="button" class="btn-sm" id="tg-gen-token">Generate</button>
              </div>
              <small>Shared secret between the gateway process and this server.</small>
            </div>

            <div class="tg-field">
              <label for="tg-gateway-url">ZEVORA gateway URL</label>
              <input id="tg-gateway-url" type="text" class="technical-text"
                value="${escapeHtml(tg?.gateway_url || 'http://127.0.0.1:7432')}" maxlength="200">
              <small>The URL where this ZEVORA instance is running.</small>
            </div>

            <div class="tg-field">
              <label for="tg-allowed-users">Allowed Telegram usernames</label>
              <input id="tg-allowed-users" type="text"
                value="${escapeHtml((tg?.allowed_users || []).join(', '))}"
                placeholder="yourusername, friend" maxlength="500">
              <small>Comma-separated. Leave blank to allow any user (not recommended).</small>
            </div>

            <div class="tg-field tg-field-inline">
              <label>Enable Telegram gateway</label>
              <label class="toggle">
                <input type="checkbox" id="tg-enabled" ${tg?.enabled ? 'checked' : ''}>
                <span class="toggle-slider"></span>
              </label>
            </div>

            <div class="tg-actions">
              <button type="button" class="btn-sm danger" id="tg-reset">Clear config</button>
              <span id="tg-save-msg" class="save-msg"></span>
              <button type="submit" class="btn-sm primary">Save &amp; apply</button>
            </div>
          </form>
        </details>

        <!-- gateway status (live) -->
        <div id="tg-gateway-status" class="tg-gateway-status"></div>
      </div>
    </div>
  `));

  $('settings-form').onsubmit = saveSettings;
  wireTelegramForm();
  loadTelegramGatewayStatus();
}

// ── Routing settings ──────────────────────────────────────────────────────────
async function saveSettings(event) {
  event.preventDefault();
  try {
    await api('/api/settings', {
      method: 'POST',
      body: JSON.stringify({
        routing_mode: $('s-routing-mode').value,
        cloud_fallback: $('s-cloud-fallback').checked,
        cost_optimization: $('s-cost-opt').checked,
      }),
    });
    showMsg('settings-save-msg', 'Saved');
  } catch (error) {
    showMsg('settings-save-msg', userErrorMessage(error), true);
  }
}

// ── Telegram form ─────────────────────────────────────────────────────────────
function wireTelegramForm() {
  // Generate gateway token button
  $('tg-gen-token')?.addEventListener('click', async () => {
    try {
      const result = await api('/api/telegram/config', {
        method: 'POST',
        body: JSON.stringify({ generate_token: true }),
      });
      if ($('tg-gateway-token')) {
        $('tg-gateway-token').value = result.gateway_token || '';
        $('tg-gateway-token').type = 'text';
      }
      showMsg('tg-save-msg', 'Token generated — save to apply');
    } catch (error) {
      showMsg('tg-save-msg', userErrorMessage(error), true);
    }
  });

  // Save form
  $('tg-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const botToken  = $('tg-bot-token').value.trim();
    const gwToken   = $('tg-gateway-token').value.trim();
    const gwUrl     = $('tg-gateway-url').value.trim();
    const rawUsers  = $('tg-allowed-users').value.trim();
    const enabled   = $('tg-enabled').checked;

    const payload = { enabled };
    if (botToken) payload.bot_token = botToken;
    if (gwToken && !gwToken.startsWith('*')) payload.gateway_token = gwToken;
    if (gwUrl)   payload.gateway_url = gwUrl;
    payload.allowed_users = rawUsers ? rawUsers.split(',').map(u => u.trim()).filter(Boolean) : [];

    try {
      await api('/api/telegram/config', { method: 'POST', body: JSON.stringify(payload) });
      showMsg('tg-save-msg', 'Saved — restart the gateway process to apply');
      // Refresh the whole settings page to show updated masked values
      setTimeout(() => renderSettings(), 1200);
    } catch (error) {
      showMsg('tg-save-msg', userErrorMessage(error), true);
    }
  });

  // Reset / clear config
  $('tg-reset')?.addEventListener('click', async () => {
    if (!confirm('Clear all Telegram configuration? The bot will stop working until reconfigured.')) return;
    try {
      await api('/api/telegram/config', { method: 'DELETE' });
      showMsg('tg-save-msg', 'Cleared');
      setTimeout(() => renderSettings(), 900);
    } catch (error) {
      showMsg('tg-save-msg', userErrorMessage(error), true);
    }
  });
}

// ── Gateway live status ───────────────────────────────────────────────────────
async function loadTelegramGatewayStatus() {
  const container = $('tg-gateway-status');
  if (!container) return;
  try {
    const status = await api('/api/telegram/status');
    const gw = status.gateway || {};
    const connected = gw.connected;
    container.innerHTML = `
      <div class="tg-live-status ${connected ? 'tg-live-ok' : 'tg-live-off'}">
        <span class="tg-live-dot"></span>
        <span>${connected
          ? `Gateway connected · last seen ${(gw.last_seen || '').replace('T', ' ').slice(0, 19)} UTC`
          : 'Gateway process not running'
        }</span>
        ${!connected && status.bot_token_set ? `
        <span class="tg-live-hint">Run: <code>python scripts/telegram_gateway.py</code></span>` : ''}
      </div>`;
  } catch (_) {
    container.innerHTML = '';
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function showMsg(id, text, isError = false) {
  const el = $(id);
  if (!el) return;
  el.textContent = text;
  el.classList.toggle('error-text', isError);
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 3000);
}

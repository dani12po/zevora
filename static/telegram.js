import {$, api, pageWrap, setPanel, userErrorMessage} from './core.js?v=20261103-2';

export async function renderTelegram() {
  let status = null;
  try { status = await api('/api/telegram/status'); } catch { status = null; }
  const connected = status?.gateway?.connected;
  setPanel('Telegram', pageWrap('<h2>Telegram Connect</h2>', `
    <div class="card settings-card">
      <div class="settings-section">
        <h3>Connect your bot</h3>
        <p>Paste the bot token from <b>@BotFather</b> and save. Then start the gateway process once — ZEVORA will answer Telegram messages for you.</p>
        <div class="settings-row"><label for="tg-token">Bot token</label>
          <input type="password" id="tg-token" placeholder="${status?.bot_token_set ? 'Token saved — paste a new one to replace' : '123456789:ABC…'}" autocomplete="off" style="max-width:420px">
        </div>
        <div class="settings-actions">
          <button type="button" class="primary" id="tg-save">Save &amp; Connect</button>
          <button type="button" id="tg-verify">Verify token</button>
          <span id="tg-msg" class="save-msg"></span>
        </div>
        <div class="settings-row"><label>Status</label><span class="technical-text" id="tg-status-text">${
          status?.bot_token_set
            ? (connected ? `🟢 Gateway connected` : '🟡 Token saved — gateway not running')
            : '⚪ Not configured'
        }</span></div>
        <div class="settings-row" id="tg-launch-row" style="display:none"><label>Start the gateway</label>
          <code class="technical-text" id="tg-launch">python scripts/telegram_gateway.py</code>
        </div>
      </div>
    </div>
    <div class="card settings-card">
      <div class="settings-section">
        <h3>Test the bot</h3>
        <p>Open your bot in Telegram, send it <code>/start</code>, then paste the message or your chat id here to receive a live test message from ZEVORA.</p>
        <div class="settings-row"><label for="tg-test">Chat id or anything</label>
          <input id="tg-test" placeholder="e.g. 123456789 or just any text" style="max-width:420px">
        </div>
        <div class="settings-actions">
          <button type="button" class="primary" id="tg-test-send">Send test message</button>
          <span id="tg-test-msg" class="save-msg"></span>
        </div>
      </div>
    </div>
  `, 'Connect ZEVORA to a Telegram bot without touching environment variables.'));

  $('tg-save').onclick = saveAndConnect;
  $('tg-verify').onclick = verifyToken;
  $('tg-test-send').onclick = sendTest;
}

async function setMessage(id, text, isError) {
  const el = $(id);
  el.textContent = text;
  el.classList.toggle('error-text', Boolean(isError));
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 4000);
}

async function saveAndConnect() {
  const token = $('tg-token').value.trim();
  if (!token) { setMessage('tg-msg', 'Paste your bot token first.', true); return; }
  try {
    const saved = await api('/api/telegram/config', {method: 'POST', body: JSON.stringify({bot_token: token, enabled: true})});
    $('tg-token').value = '';
    if (saved.gateway_token) {
      $('tg-launch-row').style.display = '';
      $('tg-launch').textContent = `python scripts/telegram_gateway.py  # shared token: ${saved.gateway_token}`;
    }
    $('tg-status-text').textContent = '🟡 Token saved — verifying…';
    const check = await api('/api/telegram/verify', {method: 'POST'});
    if (check.valid) {
      $('tg-status-text').textContent = `🟢 Connected as @${check.bot_username}`;
      setMessage('tg-msg', `Connected to @${check.bot_username}. Now run the gateway command below.`, false);
    } else {
      $('tg-status-text').textContent = '🔴 Token rejected by Telegram';
      setMessage('tg-msg', 'Telegram rejected this token. Double-check it from @BotFather.', true);
    }
  } catch (error) {
    setMessage('tg-msg', userErrorMessage(error), true);
  }
}

async function verifyToken() {
  try {
    const check = await api('/api/telegram/verify', {method: 'POST'});
    if (check.valid) {
      $('tg-status-text').textContent = `🟢 Connected as @${check.bot_username}`;
      setMessage('tg-msg', `Token valid — bot @${check.bot_username} (${check.bot_name}).`, false);
    } else {
      setMessage('tg-msg', 'Token invalid or Telegram unreachable.', true);
    }
  } catch (error) {
    setMessage('tg-msg', userErrorMessage(error), true);
  }
}

async function sendTest() {
  const value = $('tg-test').value.trim();
  if (!value) { setMessage('tg-test-msg', 'Type your chat id or any text first.', true); return; }
  try {
    const result = await api('/api/telegram/test-chat', {method: 'POST', body: JSON.stringify({message: value})});
    if (result.sent) {
      setMessage('tg-test-msg', 'Sent! Check your Telegram. 🎉', false);
    } else {
      setMessage('tg-test-msg', result.error || 'Could not deliver the message.', true);
    }
  } catch (error) {
    setMessage('tg-test-msg', userErrorMessage(error), true);
  }
}

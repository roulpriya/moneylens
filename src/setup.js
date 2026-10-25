const form = document.getElementById('setup-form');
const result = document.getElementById('result');
const save = document.getElementById('save');
const cancel = document.getElementById('cancel');
const config = JSON.parse(document.getElementById('setup-config').textContent);
const inputs = new Map();
let busy = false;
const showResult = (text, error = false) => {
  result.textContent = text;
  result.classList.toggle('error', error);
};
const clear = () => {
  form.reset();
  for (const input of inputs.values()) if (input.dataset.secret === 'true') input.type = 'password';
};
const complete = () => {
  clear();
  form.hidden = true;
  showResult(config.verification
    ? 'Verified. This statement opened successfully. The saved local PDF password is ready for future refreshes. You can close this tab.'
    : 'Your details are saved on this device, but haven’t been verified against a statement. You can close this tab and return to setup.');
};
const request = config.request || {};
const details = document.getElementById('statement-details');
for (const line of [[request.bank, request.statement_type].filter(Boolean).join(' · '),
                    [request.period, request.account_hint].filter(Boolean).join(' · '),
                    !request.bank && !request.statement_type ? request.filename : '']) {
  if (!line) continue;
  const value = document.createElement('p');
  value.textContent = line;
  details.append(value);
  details.hidden = false;
}
if (request.email_subject || request.email_url) {
  document.getElementById('source-email').hidden = false;
  document.getElementById('email-subject').textContent = request.email_subject || 'Statement email';
  document.getElementById('email-date').textContent = request.email_date || '';
  if (request.email_url) {
    const link = document.getElementById('email-link');
    link.href = request.email_url;
    link.hidden = false;
  }
}
if (request.instructions) {
  document.getElementById('unlock-instructions').hidden = false;
  document.getElementById('instructions-text').textContent = request.instructions;
}
if (config.verification) {
  save.textContent = 'Verify & save';
  document.getElementById('storage-note').textContent = 'Checked on your device. Only the working PDF-unlock value is saved, unencrypted. Form entries aren’t sent to your AI conversation.';
}
if (config.context) {
  const context = document.getElementById('request-context');
  context.textContent = config.context;
  context.hidden = false;
}
for (const field of config.fields) {
  const container = document.createElement('div');
  const label = document.createElement('label');
  label.htmlFor = `field-${field.id}`;
  label.textContent = field.label;
  const input = document.createElement('input');
  input.id = label.htmlFor;
  input.name = field.id;
  input.type = field.type;
  input.required = true;
  input.maxLength = field.maxLength;
  input.autocomplete = 'off';
  input.spellcheck = false;
  input.setAttribute('autocapitalize', 'none');
  input.setAttribute('autocorrect', 'off');
  input.setAttribute('aria-describedby', `${input.id}-help`);
  const help = document.createElement('p');
  help.className = 'field-help';
  help.id = `${input.id}-help`;
  help.textContent = field.help;
  container.append(label);
  if (field.type === 'password') {
    input.dataset.secret = 'true';
    const wrap = document.createElement('div');
    wrap.className = 'password-wrap';
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'show-password';
    toggle.textContent = 'Show';
    toggle.setAttribute('aria-label', 'Show PDF password');
    toggle.setAttribute('aria-pressed', 'false');
    toggle.addEventListener('click', () => {
      const visible = input.type === 'password';
      input.type = visible ? 'text' : 'password';
      toggle.textContent = visible ? 'Hide' : 'Show';
      toggle.setAttribute('aria-label', visible ? 'Hide PDF password' : 'Show PDF password');
      toggle.setAttribute('aria-pressed', String(visible));
    });
    wrap.append(input, toggle);
    container.append(wrap);
  } else container.append(input);
  container.append(help);
  inputs.set(field.id, input);
  document.getElementById('setup-fields').append(container);
}
save.disabled = !config.token || !inputs.size;
if (save.disabled) showResult('Open this page through the MoneyLens local setup server.', true);
else fetch('/status', {mode: 'same-origin', credentials: 'omit', cache: 'no-store'})
  .then(response => response.ok ? response.json() : null)
  .then(status => { if (status?.saved) complete(); })
  .catch(() => {});
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || !form.reportValidity() || save.disabled) return;
  busy = true;
  save.disabled = true;
  cancel.disabled = true;
  showResult(config.verification ? 'Checking this statement on your device…' : 'Saving on this device…');
  const values = Object.fromEntries([...inputs].map(([key, input]) => [key, input.value]));
  let body = JSON.stringify({values});
  for (const key of Object.keys(values)) values[key] = '';
  try {
    const response = await fetch('/submit', {
      method: 'POST', mode: 'same-origin', credentials: 'omit', cache: 'no-store',
      headers: {'Content-Type': 'application/json', 'X-MoneyLens-Setup': config.token}, body,
    });
    body = '';
    if (response.status === 409) {
      const check = await fetch('/status', {mode: 'same-origin', credentials: 'omit', cache: 'no-store'});
      if (check.ok && (await check.json()).saved === true) { complete(); return; }
    }
    const status = await response.json();
    if (status.code === 'unlock_failed' || status.code === 'attempts_exhausted') {
      showResult(status.code === 'unlock_failed'
        ? 'These details didn’t open this statement. Nothing was saved. Check the instructions above and try again.'
        : 'These details still don’t open this statement. Nothing was saved. Return to setup to review the instructions before trying again.', true);
      save.disabled = status.code === 'attempts_exhausted';
      cancel.disabled = false;
      return;
    }
    if (!response.ok || status.saved !== true) throw new Error('not_saved');
    complete();
  } catch {
    body = '';
    showResult('Couldn’t confirm the save. Your entries are still here. Retry; an existing saved file will never be overwritten.', true);
    save.disabled = false;
    cancel.disabled = false;
  } finally { busy = false; }
});
cancel.addEventListener('click', () => {
  if (busy) return;
  clear();
  form.hidden = true;
  showResult('Cancelled. No details were submitted. You can close this tab.');
});
window.addEventListener('pagehide', clear);
window.addEventListener('pageshow', event => { if (event.persisted) clear(); });

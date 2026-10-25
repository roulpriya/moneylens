import './style.css';

const setupTabs = [...document.querySelectorAll('[data-setup-tab]')];
function selectSetupTab(selected, moveFocus = false) {
  setupTabs.forEach((tab) => {
    const active = tab === selected;
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    document.getElementById(tab.getAttribute('aria-controls')).hidden = !active;
  });
  if (moveFocus) selected.focus();
}
setupTabs.forEach((tab, index) => {
  tab.addEventListener('click', () => selectSetupTab(tab));
  tab.addEventListener('keydown', (event) => {
    const targets = {
      ArrowRight: (index + 1) % setupTabs.length,
      ArrowLeft: (index - 1 + setupTabs.length) % setupTabs.length,
      Home: 0,
      End: setupTabs.length - 1,
    };
    if (!Object.hasOwn(targets, event.key)) return;
    event.preventDefault();
    selectSetupTab(setupTabs[targets[event.key]], true);
  });
});

document.querySelectorAll('[data-copy]').forEach((button) => {
  button.addEventListener('click', async () => {
    const code = document.getElementById(button.dataset.copy);
    const status = document.getElementById('copy-status');
    const label = button.querySelector('span');
    try {
      await navigator.clipboard.writeText(code.textContent.trim());
      label.textContent = 'Copied!';
      status.textContent = 'Installation command copied to clipboard.';
    } catch {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(code);
      selection.removeAllRanges();
      selection.addRange(range);
      label.textContent = 'Selected';
      status.textContent = 'Automatic copy is unavailable. The command is selected; use your copy shortcut.';
    }
    window.setTimeout(() => { label.textContent = 'Copy'; }, 2500);
  });
});

import './style.css';

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

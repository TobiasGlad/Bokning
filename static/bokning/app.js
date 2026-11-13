(() => {
  'use strict';
  const menu = document.querySelector('[data-menu]');
  const pane = document.getElementById('folder-pane');
  const mobileLayout = window.matchMedia('(max-width: 760px)');
  const setMenu = (open, returnFocus = false) => {
    const expanded = mobileLayout.matches ? open : true;
    document.body.classList.toggle('menu-open', mobileLayout.matches && open);
    menu?.setAttribute('aria-expanded', String(expanded));
    menu?.setAttribute('aria-label', expanded ? 'Stäng menyn' : 'Öppna menyn');
    if (pane) pane.inert = !expanded;
    if (returnFocus) menu?.focus();
  };
  menu?.addEventListener('click', () => setMenu(!document.body.classList.contains('menu-open')));
  mobileLayout.addEventListener('change', () => setMenu(false));
  setMenu(false);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && mobileLayout.matches && document.body.classList.contains('menu-open')) setMenu(false, true);
  });
  document.addEventListener('click', event => {
    if (mobileLayout.matches && document.body.classList.contains('menu-open') && !pane?.contains(event.target) && !menu?.contains(event.target)) setMenu(false);
  });
  document.querySelectorAll('[data-password]').forEach(button => button.addEventListener('click', () => {
    const input = document.getElementById(button.dataset.password);
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    button.textContent = show ? 'Dölj' : 'Visa';
    button.setAttribute('aria-label', show ? 'Dölj lösenord' : 'Visa lösenord');
  }));
  document.querySelectorAll('form[data-confirm]').forEach(form => form.addEventListener('submit', event => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  }));
  document.querySelectorAll('form').forEach(form => form.addEventListener('submit', event => {
    if (!event.defaultPrevented && form.method.toLowerCase() === 'post') {
      const button = event.submitter;
      if (button) { button.disabled = true; button.classList.add('submitting'); }
    }
  }));
  let installPrompt;
  const buttons = document.querySelectorAll('[data-install]');
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault(); installPrompt = event;
    buttons.forEach(button => { button.hidden = false; });
  });
  buttons.forEach(button => button.addEventListener('click', async () => {
    if (installPrompt) { await installPrompt.prompt(); installPrompt = null; buttons.forEach(b => { b.hidden = true; }); }
  }));
  if ('serviceWorker' in navigator && window.isSecureContext) {
    navigator.serviceWorker.register('/bokning/sw.js', { scope: '/bokning/' }).catch(() => {});
  }
})();

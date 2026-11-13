(() => {
  'use strict';
  const menu = document.querySelector('[data-menu]');
  menu?.addEventListener('click', () => {
    const open = document.body.classList.toggle('menu-open');
    menu.setAttribute('aria-expanded', String(window.matchMedia('(max-width: 760px)').matches ? open : !open));
  });
  const mobileLayout = window.matchMedia('(max-width: 760px)');
  if (menu) menu.setAttribute('aria-expanded', String(!mobileLayout.matches));
  mobileLayout.addEventListener('change', () => {
    document.body.classList.remove('menu-open');
    menu?.setAttribute('aria-expanded', String(!mobileLayout.matches));
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && window.matchMedia('(max-width: 760px)').matches) {
      document.body.classList.remove('menu-open'); menu?.setAttribute('aria-expanded', 'false');
    }
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

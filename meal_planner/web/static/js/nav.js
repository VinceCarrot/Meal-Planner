// Page switching without importing app.js (avoids circular module imports).
export function openPage(name, ...args) {
  window.dispatchEvent(new CustomEvent('open-page', { detail: { name, args } }));
}

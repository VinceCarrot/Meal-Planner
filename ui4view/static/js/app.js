// Entry point: load the current menu once and hand it to the menu module.

import { showMenu, showError } from '../modules/menu/menu.js';

async function start() {
  try {
    const response = await fetch('api/menu');
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new Error((data && (data.detail || data.error)) || `HTTP ${response.status}`);
    showMenu(data);
  } catch (err) {
    showError(err.message || String(err));
  }
}

start();

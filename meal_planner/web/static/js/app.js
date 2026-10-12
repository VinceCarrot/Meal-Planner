// Entry point: sidebar navigation. Each page module exports `show()`, called
// every time its page is opened, so it always displays fresh data.

import { showPlan } from '../modules/plan/plan.js';
import { showMenus } from '../modules/menus/menus.js';
import { showConstraints } from '../modules/constraints/constraints.js';
import { showDishes } from '../modules/dishes/dishes.js';
import { showReview } from '../modules/review/review.js';
import { showIngredients } from '../modules/ingredients/ingredients.js';
import { showSettings } from '../modules/settings/settings.js';

const PAGES = {
  plan: showPlan,
  menus: showMenus,
  constraints: showConstraints,
  dishes: showDishes,
  review: showReview,
  ingredients: showIngredients,
  settings: showSettings,
};

function openPage(name, ...args) {
  if (!PAGES[name]) name = 'plan';
  for (const key of Object.keys(PAGES)) {
    document.getElementById(`page_${key}`).classList.toggle('active', key === name);
    document.querySelector(`#sidebar [data-page="${key}"]`).classList.toggle('active', key === name);
  }
  if (location.hash !== `#${name}`) history.replaceState(null, '', `#${name}`);
  PAGES[name](...args);
}

document.querySelectorAll('#sidebar [data-page]').forEach((button) => {
  button.addEventListener('click', () => openPage(button.dataset.page));
});

window.addEventListener('open-page', (e) => openPage(e.detail.name, ...e.detail.args));

openPage(location.hash.slice(1) || 'plan');

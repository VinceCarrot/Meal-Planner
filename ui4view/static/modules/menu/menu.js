// Four-week menu: week tabs, one card per dinner, recipe panel on click.
// All text is inserted as text, never as HTML.

const DISH_TYPES = { vegetarian: '素菜', mixed: '荤素搭配', meat: '大荤', soup: '汤' };

let data;
let week = 1;

function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child !== null && child !== undefined && child !== false) node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

const $ = (id) => document.getElementById(id);
const short = (iso) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`;
const tag = (type) => (type ? h('span', { class: `tag tag-${type}` }, DISH_TYPES[type] || type) : null);

export function showError(text) {
  $('menu_root').replaceChildren(h('div', { class: 'message error' }, `无法读取菜单：${text}`));
}

export function showMenu(payload) {
  data = payload;
  if (!data.menu) {
    $('week_tabs').replaceChildren();
    $('menu_root').replaceChildren(h('div', { class: 'empty' },
      h('p', {}, '还没有菜单。'),
      h('p', { class: 'hint' }, '在本机的晚餐计划程序里生成并保存菜单后，刷新这个页面即可看到。')));
    return;
  }
  const m = data.menu;
  $('menu_period').textContent = `${short(m.start_date)} – ${short(m.end_date)} · 只读`;
  const current = m.weeks.find((w) => w.dinners.some((d) => d.is_today));
  week = current ? current.n : 1;
  render();
}

function render() {
  const m = data.menu;
  $('week_tabs').replaceChildren(...m.weeks.map((w) => h('button', {
    'aria-selected': String(w.n === week),
    onclick: () => { week = w.n; render(); },
  }, `第 ${w.n} 周`)));
  const dinners = m.weeks[week - 1].dinners;
  $('menu_root').replaceChildren(dinners.length
    ? h('div', { class: 'days' }, dinners.map(dayCard))
    : h('p', { class: 'hint' }, '这一周没有安排晚餐。'));
}

function dayCard(dinner) {
  return h('article', { class: dinner.is_today ? 'day today' : 'day' },
    h('div', { class: 'day-head' },
      h('b', {}, dinner.weekday),
      h('span', { class: 'date' }, short(dinner.date)),
      dinner.is_today ? h('span', { class: 'chip-today' }, '今天') : null),
    h('ul', { class: 'dishes' }, dinner.dishes.map((d) => h('li', {},
      h('button', { class: 'dish', onclick: () => showRecipe(d.dish_id) }, tag(d.dish_type), d.name_zh)))));
}

function showRecipe(dishId) {
  const r = data.recipes[dishId];
  if (!r) return;
  const root = $('recipe_root');
  root.replaceChildren(h('div', { class: 'recipe' },
    h('div', { class: 'recipe-head' },
      h('h2', {}, r.name_zh, ' ', tag(r.dish_type)),
      h('button', { class: 'close', onclick: () => root.replaceChildren() }, '收起')),
    r.name_en ? h('p', { class: 'hint' }, r.name_en) : null,
    r.missing ? h('p', { class: 'hint' }, '菜品库里已经没有这道菜的做法。') : null,
    r.servings ? h('p', { class: 'hint' }, `${r.servings} 人份`) : null,
    r.ingredients.length ? h('h3', {}, '食材') : null,
    r.ingredients.length ? h('ul', { class: 'ingredients' }, r.ingredients.map((l) => h('li', {},
      h('span', {}, l.name),
      h('span', { class: 'qty' }, [l.quantity != null ? `${l.quantity} ${l.unit || ''}` : '', l.note ? `（${l.note}）` : ''].join(' ').trim())))) : null,
    r.steps.length ? h('h3', {}, '做法') : null,
    r.steps.length ? h('ol', {}, r.steps.map((s) => h('li', {}, s))) : null));
  root.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

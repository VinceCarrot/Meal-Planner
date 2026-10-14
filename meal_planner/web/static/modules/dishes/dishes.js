// Approved dish catalogue: browse, add manually, edit, delete.

import { get, post, put, del } from '../../js/api.js';
import { h, fill, label, dishTypeTag, showError, toast, LABELS } from '../../js/ui.js';
import { editDish } from '../../js/dish_editor.js';

let root;
let messages;
let list;
let detail;
let typeFilter;
let search;
let dishes = [];
let ingredients = [];
let shownId = null; // dish whose detail panel is open

export async function showDishes() {
  if (!root) build();
  await refresh();
}

function build() {
  root = document.getElementById('dishes_root');
  messages = h('div');
  list = h('div');
  detail = h('div');
  typeFilter = h('select', { onchange: renderList }, h('option', { value: '' }, '全部类型'),
    Object.keys(LABELS.dish_type).map((t) => h('option', { value: t }, label('dish_type', t))));
  search = h('input', { placeholder: '搜索名称', oninput: renderList });
  fill(root,
    messages,
    h('div', { class: 'row' }, typeFilter, search, h('span', { class: 'spacer' }),
      h('button', { class: 'primary', onclick: addDish }, '+ 新增菜品')),
    detail,
    list);
}

async function refresh() {
  try {
    [dishes, ingredients] = await Promise.all([get('/api/dishes'), get('/api/ingredients')]);
    renderList();
  } catch (err) {
    showError(messages, err);
  }
}

const ingredientName = (id) => (ingredients.find((i) => i.ingredient_id === id) || {}).name_zh || id;

function kcalText(d) {
  const c = d.calories;
  if (c.complete) return `${c.known_kcal} kcal${c.per_serving_kcal != null ? `（每份 ${c.per_serving_kcal}）` : ''}`;
  return `≥ ${c.known_kcal} kcal（数据不全）`;
}

function renderList() {
  const text = search.value.trim();
  const shown = dishes.filter((d) => (!typeFilter.value || d.dish_type === typeFilter.value) && (!text || d.name_zh.includes(text)));
  fill(list, h('p', { class: 'hint' }, `共 ${dishes.length} 道，显示 ${shown.length} 道`),
    h('table', {},
      h('tr', {}, ['ID', '名称', '类型', '主料', '做法 / 口味', '估算热量', '来源', ''].map((t) => h('th', {}, t))),
      shown.map((d) => h('tr', { class: 'clickable', onclick: () => renderDetail(d) },
        h('td', {}, d.dish_id),
        h('td', {}, d.name_zh),
        h('td', {}, dishTypeTag(d.dish_type)),
        h('td', {}, d.style.main_ingredients.map(ingredientName).join('、')),
        h('td', {}, [label('cooking_method', d.style.cooking_method), ...d.style.flavours.map((f) => label('flavour', f))].filter(Boolean).join(' · ')),
        h('td', {}, kcalText(d)),
        h('td', {}, label('source', d.source)),
        h('td', {}, h('button', { class: 'small danger', onclick: (e) => { e.stopPropagation(); deleteDish(d); } }, '删除'))))));
}

async function deleteDish(d) {
  if (!window.confirm(`删除菜品 ${d.name_zh}（${d.dish_id}）？删除后无法恢复；已保存的菜单或反馈用到这道菜时无法删除。`)) return;
  fill(messages);
  try {
    await del(`/api/dishes/${d.dish_id}`);
    toast(`已删除 ${d.name_zh}`);
    if (shownId === d.dish_id) { shownId = null; fill(detail); }
  } catch (err) {
    showError(messages, err);
  }
  await refresh();
}

export function dishDetail(d, ingredientsList) {
  const name = (id) => (ingredientsList.find((i) => i.ingredient_id === id) || {}).name_zh || id;
  return h('div', {},
    h('h4', {}, d.name_zh, ' ', dishTypeTag(d.dish_type), d.name_en ? h('span', { class: 'hint' }, ` ${d.name_en}`) : null),
    h('ul', {}, d.ingredients.map((l) => h('li', {},
      l.ingredient_id ? name(l.ingredient_id) : h('span', { class: 'unmatched' }, `未匹配：${l.unmatched_name}`),
      l.quantity != null ? ` ${l.quantity} ${l.unit || ''}` : '', l.note ? `（${l.note}）` : ''))),
    h('ol', {}, d.steps.map((s) => h('li', {}, s))),
    h('p', { class: 'hint' }, `份数：${d.servings ?? '未填'}；估算热量：${d.calories.complete ? `${d.calories.known_kcal} kcal` : `至少 ${d.calories.known_kcal} kcal，缺少：${d.calories.missing.join('；')}`}`),
    d.uncertainty_notes ? h('p', { class: 'warn' }, `不确定之处：${d.uncertainty_notes}`) : null,
    d.source_url ? h('p', { class: 'hint' }, `来源链接：${d.source_url}`) : null);
}

function renderDetail(d) {
  shownId = d.dish_id;
  fill(detail, h('div', { class: 'panel' },
    dishDetail(d, ingredients),
    h('div', { class: 'row' },
      h('button', { onclick: () => editExisting(d) }, '编辑'),
      h('button', { class: 'danger', onclick: () => deleteDish(d) }, '删除'),
      h('button', { onclick: () => { shownId = null; fill(detail); } }, '收起'))));
}

async function addDish() {
  const dish = await editDish(null, ingredients, '新增菜品', { analyse: true, requireMatched: true });
  if (!dish) return;
  try {
    const created = await post('/api/dishes', dish);
    toast(`已添加 ${created.name_zh}（${created.dish_id}）`);
    await refresh();
    renderDetail(created);
  } catch (err) {
    showError(messages, err);
  }
}

async function editExisting(d) {
  const dish = await editDish(d, ingredients, `编辑 ${d.name_zh}`, { requireMatched: true });
  if (!dish) return;
  try {
    const saved = await put(`/api/dishes/${d.dish_id}`, dish);
    toast('已保存');
    await refresh();
    renderDetail(saved);
  } catch (err) {
    showError(messages, err);
  }
}

// Ingredient master data, edited only by the user.

import { get, post, put, del } from '../../js/api.js';
import { h, fill, label, showError, toast, LABELS } from '../../js/ui.js';

let root;
let messages;
let form;
let table;
let ingredients = [];

export async function showIngredients() {
  if (!root) {
    root = document.getElementById('ingredients_root');
    messages = h('div');
    form = h('div');
    table = h('div');
    fill(root, messages, h('div', { class: 'row' }, h('button', { class: 'primary', onclick: () => renderForm(null) }, '+ 新增食材')), form, table);
  }
  await refresh();
}

async function refresh() {
  try {
    ingredients = await get('/api/ingredients');
    renderTable();
  } catch (err) {
    showError(messages, err);
  }
}

const unitsText = (units) => Object.entries(units || {}).map(([u, g]) => `${u}=${g}`).join(', ');

function parseUnits(text) {
  const result = {};
  for (const part of text.split(/[,，;；]/).map((s) => s.trim()).filter(Boolean)) {
    const [unit, grams] = part.split('=').map((s) => s.trim());
    if (!unit || !(Number(grams) > 0)) throw new Error(`无法识别“${part}”，格式应为 个=150`);
    result[unit] = Number(grams);
  }
  return result;
}

function renderTable() {
  fill(table, h('table', {},
    h('tr', {}, ['ID', '中文名', '英文名', '别名', '分类', 'kcal/100g', '每单位克重', '备注', ''].map((t) => h('th', {}, t))),
    ingredients.map((i) => h('tr', {},
      h('td', {}, i.ingredient_id),
      h('td', {}, i.name_zh),
      h('td', {}, i.name_en || ''),
      h('td', {}, i.aliases.join('、')),
      h('td', {}, label('category', i.category)),
      h('td', {}, i.kcal_per_100g ?? h('span', { class: 'warn' }, '未填')),
      h('td', {}, unitsText(i.grams_per_unit)),
      h('td', {}, i.notes || ''),
      h('td', {},
        h('button', { class: 'small', onclick: () => renderForm(i) }, '编辑'), ' ',
        h('button', {
          class: 'small danger',
          onclick: async () => {
            if (!window.confirm(`删除食材 ${i.name_zh}？仍被菜品使用时无法删除。`)) return;
            fill(messages);
            try { await del(`/api/ingredients/${i.ingredient_id}`); toast('已删除'); } catch (err) { showError(messages, err); }
            refresh();
          },
        }, '删除'))))));
}

// While Claude analyses a name, every button on the page is disabled so that the
// form cannot be saved, closed or replaced before the answer arrives.
function setLocked(on) {
  for (const b of root.querySelectorAll('button')) b.disabled = on;
}

function renderForm(existing) {
  const i = existing || { ingredient_id: 'ing_', name_zh: '', name_en: '', aliases: [], category: 'vegetable', kcal_per_100g: null, grams_per_unit: {}, notes: '' };
  const id = h('input', { value: i.ingredient_id, disabled: Boolean(existing), placeholder: 'ing_英文小写_下划线' });
  const nameZh = h('input', { value: i.name_zh, placeholder: '例如：西兰花', onkeydown: (e) => { if (e.key === 'Enter') analyse(); } });
  const nameEn = h('input', {
    value: i.name_en || '',
    oninput: (e) => {
      if (!existing) id.value = `ing_${e.target.value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '')}`;
    },
  });
  const aliases = h('input', { value: i.aliases.join('、'), placeholder: '用顿号分隔' });
  const category = h('select', {}, Object.keys(LABELS.category).map((c) => h('option', { value: c, selected: i.category === c }, label('category', c))));
  const kcal = h('input', { type: 'number', step: 'any', min: 0, value: i.kcal_per_100g ?? '' });
  const units = h('input', { value: unitsText(i.grams_per_unit), placeholder: '个=150, 勺=15' });
  const notes = h('input', { value: i.notes || '' });
  const field = (text, input) => h('div', { class: 'field' }, h('span', {}, text), input);
  const filled = [nameEn, aliases, category, kcal, units, notes];
  const status = h('div');
  const analyseButton = h('button', { onclick: () => analyse() }, '分析');

  async function analyse() {
    if (analyseButton.disabled) return;
    fill(status);
    if (!nameZh.value.trim()) {
      fill(status, h('div', { class: 'message warning' }, '请先填写中文名'));
      return;
    }
    setLocked(true);
    analyseButton.textContent = '分析中…';
    for (const input of [nameZh, ...filled]) input.readOnly = true;
    category.disabled = true;
    fill(status, h('div', { class: 'inline-busy' }, h('div', { class: 'spinner' }),
      `正在调用 Claude 分析“${nameZh.value.trim()}”，通常需要十几秒，请稍候…`));
    try {
      const { ingredient: s, warnings } = await post('/api/ingredients/suggest',
        { name_zh: nameZh.value.trim(), ingredient_id: existing ? existing.ingredient_id : null });
      if (!existing) id.value = s.ingredient_id;
      nameEn.value = s.name_en || '';
      aliases.value = s.aliases.join('、');
      category.value = s.category;
      kcal.value = s.kcal_per_100g ?? '';
      units.value = unitsText(s.grams_per_unit);
      notes.value = s.notes || '';
      fill(status, h('div', { class: warnings.length ? 'message warning' : 'message info' },
        '已填好建议内容，请检查后再保存。',
        warnings.length ? h('ul', {}, warnings.map((w) => h('li', {}, w))) : null));
    } catch (err) {
      fill(status);
      showError(status, err);
    } finally {
      for (const input of [nameZh, ...filled]) input.readOnly = false;
      category.disabled = false;
      analyseButton.textContent = '分析';
      setLocked(false);
    }
  }

  fill(form, h('div', { class: 'panel' },
    h('h3', {}, existing ? `编辑 ${i.name_zh}` : '新增食材'),
    h('div', { class: 'row analyse-row' }, field('中文名', nameZh), analyseButton,
      h('span', { class: 'hint' }, '只需填中文名，点“分析”由 Claude 填写其余内容，保存前可修改')),
    status,
    h('div', { class: 'row' },
      field('ID（创建后不可改）', id), field('英文名', nameEn), field('别名', aliases), field('分类', category)),
    h('div', { class: 'row' }, field('kcal / 100g', kcal), field('每单位克重', units), field('备注', notes)),
    h('div', { class: 'row' },
      h('button', {
        class: 'primary',
        onclick: async () => {
          fill(messages);
          try {
            const data = {
              ingredient_id: id.value.trim(),
              name_zh: nameZh.value.trim(),
              name_en: nameEn.value.trim() || null,
              aliases: aliases.value.split(/[、,，]/).map((s) => s.trim()).filter(Boolean),
              category: category.value,
              kcal_per_100g: kcal.value === '' ? null : Number(kcal.value),
              grams_per_unit: parseUnits(units.value),
              notes: notes.value.trim() || null,
            };
            if (existing) await put(`/api/ingredients/${i.ingredient_id}`, data);
            else await post('/api/ingredients', data);
            toast('已保存');
            fill(form);
            refresh();
          } catch (err) {
            showError(messages, err);
          }
        },
      }, '保存'),
      h('button', { onclick: () => fill(form) }, '取消'))));
}

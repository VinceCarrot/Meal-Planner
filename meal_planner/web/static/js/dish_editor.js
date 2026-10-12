// Dish form used for manual dishes and for editing candidates.
// Resolves with the edited dish object, or null if cancelled. The server validates it.

import { h, fill, label, openModal, LABELS } from './ui.js';

export function editDish(dish, ingredients, title) {
  const d = structuredClone(dish || {
    name_zh: '', name_en: '', dish_type: 'vegetarian', servings: 4, ingredients: [],
    steps: [], style: { main_ingredients: [], cooking_method: null, flavours: [], cuisine: null },
  });
  d.style = d.style || { main_ingredients: [], flavours: [] };
  const byId = Object.fromEntries(ingredients.map((i) => [i.ingredient_id, i]));

  return new Promise((resolve) => {
    const lines = h('div');
    const mains = h('div');
    const name = h('input', { value: d.name_zh, placeholder: '中文名' });
    const nameEn = h('input', { value: d.name_en || '', placeholder: '英文名（可选）' });
    const type = h('select', {}, Object.keys(LABELS.dish_type).map((t) => h('option', { value: t, selected: d.dish_type === t }, label('dish_type', t))));
    const servings = h('input', { type: 'number', min: 1, value: d.servings ?? '' });
    const steps = h('textarea', { rows: 6 }, (d.steps || []).join('\n'));
    const method = h('select', {}, h('option', { value: '' }, '（未填）'),
      Object.keys(LABELS.cooking_method).map((m) => h('option', { value: m, selected: d.style.cooking_method === m }, label('cooking_method', m))));
    const flavours = Object.keys(LABELS.flavour).map((f) => h('input', { type: 'checkbox', value: f, checked: (d.style.flavours || []).includes(f) }));
    const cuisine = h('input', { value: d.style.cuisine || '', placeholder: '例如：家常、川菜' });
    const kcal = h('input', { type: 'number', min: 0, value: d.calories_kcal ?? '', placeholder: '可选' });
    const notes = h('textarea', { rows: 2 }, d.uncertainty_notes || '');
    const error = h('div');

    const ingredientSelect = (line) => h('select', {
      onchange: (e) => {
        line.ingredient_id = e.target.value || null;
        if (line.ingredient_id) line.unmatched_name = null;
        renderMains();
      },
    },
    h('option', { value: '' }, line.unmatched_name ? `（未匹配：${line.unmatched_name}）请选择食材` : '请选择食材'),
    ingredients.map((i) => h('option', { value: i.ingredient_id, selected: line.ingredient_id === i.ingredient_id }, `${i.name_zh}（${i.ingredient_id}）`)));

    function renderLines() {
      fill(lines, d.ingredients.map((line, n) => h('div', { class: 'row' },
        ingredientSelect(line),
        line.unmatched_name && !line.ingredient_id ? h('span', { class: 'unmatched' }, '未匹配') : null,
        h('input', { type: 'number', step: 'any', min: 0, value: line.quantity ?? '', placeholder: '用量', oninput: (e) => { line.quantity = e.target.value === '' ? null : Number(e.target.value); } }),
        h('input', { value: line.unit || '', placeholder: '单位 g/个', size: 6, oninput: (e) => { line.unit = e.target.value || null; } }),
        h('input', { value: line.note || '', placeholder: '备注 如 适量', size: 10, oninput: (e) => { line.note = e.target.value || null; } }),
        h('button', { class: 'small danger', onclick: () => { d.ingredients.splice(n, 1); renderLines(); renderMains(); } }, '删除'))));
    }

    function renderMains() {
      const used = [...new Set(d.ingredients.map((l) => l.ingredient_id).filter(Boolean))];
      d.style.main_ingredients = (d.style.main_ingredients || []).filter((m) => used.includes(m));
      fill(mains, used.length ? used.map((id) => h('label', {},
        h('input', {
          type: 'checkbox',
          checked: d.style.main_ingredients.includes(id),
          onchange: (e) => {
            d.style.main_ingredients = e.target.checked ? [...d.style.main_ingredients, id] : d.style.main_ingredients.filter((m) => m !== id);
          },
        }), byId[id] ? byId[id].name_zh : id)) : h('span', { class: 'hint' }, '先添加食材'));
    }

    function collect() {
      const result = {
        ...d,
        name_zh: name.value.trim(),
        name_en: nameEn.value.trim() || null,
        dish_type: type.value,
        servings: servings.value ? Number(servings.value) : null,
        steps: steps.value.split('\n').map((s) => s.trim()).filter(Boolean),
        calories_kcal: kcal.value === '' ? null : Number(kcal.value),
        uncertainty_notes: notes.value.trim() || null,
        style: {
          main_ingredients: d.style.main_ingredients,
          cooking_method: method.value || null,
          flavours: flavours.filter((f) => f.checked).map((f) => f.value),
          cuisine: cuisine.value.trim() || null,
        },
      };
      if (result.calories_kcal == null) result.calorie_basis = null;
      else if (!result.calorie_basis) result.calorie_basis = 'estimated';
      delete result.calories;
      return result;
    }

    const close = openModal(
      h('h3', { style: 'margin-top:0' }, title),
      h('div', { class: 'row' },
        h('div', { class: 'field' }, h('span', {}, '名称'), name),
        h('div', { class: 'field' }, h('span', {}, '英文名'), nameEn),
        h('div', { class: 'field' }, h('span', {}, '类型'), type),
        h('div', { class: 'field' }, h('span', {}, '份数'), servings),
        h('div', { class: 'field' }, h('span', {}, '整道菜热量 kcal'), kcal)),
      h('h3', {}, '食材'), lines,
      h('button', { class: 'small', onclick: () => { d.ingredients.push({ ingredient_id: null, quantity: null, unit: 'g', note: null }); renderLines(); } }, '+ 添加食材'),
      h('h3', {}, '做法步骤（每行一步）'), steps,
      h('h3', {}, '风格特征（用于相似度计算）'),
      h('div', { class: 'row' }, '主料：', mains),
      h('div', { class: 'row' }, '做法：', method, '菜系：', cuisine),
      h('div', { class: 'row' }, '口味：', flavours.map((f) => h('label', {}, f, label('flavour', f.value)))),
      h('h3', {}, '不确定之处'), notes,
      error,
      h('div', { class: 'row' },
        h('span', { class: 'spacer' }),
        h('button', { onclick: () => { close(); resolve(null); } }, '取消'),
        h('button', {
          class: 'primary',
          onclick: () => {
            const result = collect();
            const missing = result.ingredients.some((l) => !l.ingredient_id && !l.unmatched_name);
            if (!result.name_zh || !result.ingredients.length || missing) {
              fill(error, h('div', { class: 'message error' }, '请填写名称，并为每一行选择食材。'));
              return;
            }
            close();
            resolve(result);
          },
        }, '确定')));
    renderLines();
    renderMains();
  });
}

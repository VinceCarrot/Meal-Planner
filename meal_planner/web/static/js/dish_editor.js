// Dish form used for manual dishes and for editing candidates.
// Resolves with the edited dish object, or null if cancelled. The server validates it.
// options.analyse: show the "分析" button and "联网搜索做法" box (Claude fills the form from the name and
// method text, optionally from a web search; ADR-023) and the reference-link field.
// options.requireMatched: every ingredient line must reference the catalogue (approved dishes).

import { post } from './api.js';
import { h, fill, label, openModal, showError, sortIngredients, LABELS } from './ui.js';

const NUMBERING = /^\s*(?:第?[0-9一二三四五六七八九十]+(?:步[.、:：]?|[、:：)）]|\.(?!\d))|步骤\s*[0-9一二三四五六七八九十]+[.、:：]?|[(（][0-9]+[)）]|[-*•·])\s*/;

export const stepsFromText = (text) => text.split('\n').map((s) => s.replace(NUMBERING, '').trim()).filter(Boolean);

export function editDish(dish, ingredients, title, { analyse = false, requireMatched = false } = {}) {
  let d = structuredClone(dish || {
    name_zh: '', name_en: '', dish_type: 'vegetarian', servings: 4, ingredients: [],
    steps: [], style: { main_ingredients: [], cooking_method: null, flavours: [], cuisine: null },
  });
  d.style = d.style || { main_ingredients: [], flavours: [] };
  const byId = Object.fromEntries(ingredients.map((i) => [i.ingredient_id, i]));
  const sorted = sortIngredients(ingredients);

  return new Promise((resolve) => {
    const lines = h('div');
    const mains = h('div');
    const name = h('input', { value: d.name_zh, placeholder: '例如：番茄炒蛋', style: 'width:100%' });
    const steps = h('textarea', {
      rows: 10,
      placeholder: analyse
        ? '可以直接粘贴或随手写做法，不需要每行一步；点“分析”会整理成每行一步。\n留空则由 Claude 按常见做法生成。'
        : '每行一步',
    }, (d.steps || []).join('\n'));
    const nameEn = h('input', { value: d.name_en || '', placeholder: '英文名（可选）' });
    const type = h('select', {}, Object.keys(LABELS.dish_type).map((t) => h('option', { value: t }, label('dish_type', t))));
    const servings = h('input', { type: 'number', min: 1, value: d.servings ?? '' });
    const method = h('select', {}, h('option', { value: '' }, '（未填）'),
      Object.keys(LABELS.cooking_method).map((m) => h('option', { value: m }, label('cooking_method', m))));
    const flavours = Object.keys(LABELS.flavour).map((f) => h('input', { type: 'checkbox', value: f }));
    const cuisine = h('input', { placeholder: '例如：家常、川菜' });
    const kcal = h('input', { type: 'number', min: 0, value: d.calories_kcal ?? '', placeholder: '可选' });
    const notes = h('textarea', { rows: 2 });
    const sourceUrl = h('input', { value: d.source_url || '', placeholder: 'https://…（可选）', style: 'width:100%' });
    const webSearch = h('input', { type: 'checkbox' });
    const webSearchLabel = h('label', { title: '只在做法步骤留空时使用：让 Claude 先上网搜索菜谱再整理' }, webSearch, '联网搜索做法');
    const syncWebSearch = () => {
      const hasSteps = Boolean(steps.value.trim());
      webSearch.disabled = hasSteps;
      if (hasSteps) webSearch.checked = false;
      webSearchLabel.classList.toggle('muted', hasSteps);
    };
    steps.addEventListener('input', syncWebSearch);
    const status = h('div');
    const error = h('div');
    const field = (text, input, style) => h('div', { class: 'field', style }, h('span', {}, text), input);

    function setFields() {
      type.value = d.dish_type;
      method.value = d.style.cooking_method || '';
      flavours.forEach((f) => { f.checked = (d.style.flavours || []).includes(f.value); });
      cuisine.value = d.style.cuisine || '';
      notes.value = d.uncertainty_notes || '';
    }

    const ingredientSelect = (line) => h('select', {
      onchange: (e) => {
        line.ingredient_id = e.target.value || null;
        if (line.ingredient_id) line.unmatched_name = null;
        renderLines();
        renderMains();
      },
    },
    h('option', { value: '' }, line.unmatched_name ? `（未匹配：${line.unmatched_name}）请选择食材` : '请选择食材'),
    sorted.map((i) => h('option', { value: i.ingredient_id, selected: line.ingredient_id === i.ingredient_id, title: i.ingredient_id },
      `${label('category', i.category)} - ${i.name_zh}`)));

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
        steps: stepsFromText(steps.value),
        calories_kcal: kcal.value === '' ? null : Number(kcal.value),
        uncertainty_notes: notes.value.trim() || null,
        source_url: analyse ? sourceUrl.value.trim() || null : d.source_url ?? null,
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

    const analyseButton = h('button', { class: 'primary', onclick: () => runAnalyse() }, '分析');
    const cancelButton = h('button', { onclick: () => { close(); resolve(null); } }, '取消');
    const okButton = h('button', { class: 'primary', onclick: () => confirm() }, '确定');

    async function runAnalyse() {
      fill(status);
      const nameZh = name.value.trim();
      if (!nameZh) {
        fill(status, h('div', { class: 'message warning' }, '请先填写中文名'));
        return;
      }
      if (d.ingredients.length && !window.confirm('分析结果会替换已填写的食材、做法和其他内容，继续吗？')) return;
      const stepsText = steps.value.trim();
      const search = !stepsText && webSearch.checked;
      const busy = [analyseButton, cancelButton, okButton, webSearch];
      busy.forEach((b) => { b.disabled = true; });
      name.readOnly = true;
      steps.readOnly = true;
      analyseButton.textContent = '分析中…';
      fill(status, h('div', { class: 'inline-busy' }, h('div', { class: 'spinner' }),
        stepsText ? `正在调用 Claude 整理做法并分析“${nameZh}”，通常需要二三十秒，请稍候…`
          : search ? `正在让 Claude 联网搜索“${nameZh}”的菜谱并整理，通常需要一分钟左右，请稍候…`
            : `正在调用 Claude 生成“${nameZh}”的做法，通常需要二三十秒，请稍候…`));
      try {
        const { dish: s, sources, warnings } = await post('/api/dishes/suggest',
          { name_zh: nameZh, steps_text: stepsText, web_search: search });
        d = { ...d, ...s, style: { ...s.style } };
        name.value = s.name_zh;
        steps.value = s.steps.join('\n');
        nameEn.value = s.name_en || '';
        servings.value = s.servings ?? '';
        kcal.value = '';
        sourceUrl.value = s.source_url || '';
        setFields();
        renderLines();
        renderMains();
        fill(status, h('div', { class: warnings.length ? 'message warning' : 'message info' },
          '已填好建议内容，所有项目都可以修改，请检查后再点“确定”。',
          warnings.length ? h('ul', {}, warnings.map((w) => h('li', {}, w))) : null,
          sources.length ? h('div', {}, '参考链接：', h('ul', {}, sources.map((u) => h('li', {},
            h('a', { href: u, target: '_blank', rel: 'noopener noreferrer' }, u))))) : null));
      } catch (err) {
        fill(status);
        showError(status, err);
      } finally {
        busy.forEach((b) => { b.disabled = false; });
        syncWebSearch();
        name.readOnly = false;
        steps.readOnly = false;
        analyseButton.textContent = '分析';
      }
    }

    function confirm() {
      const result = collect();
      const missing = result.ingredients.some((l) => !l.ingredient_id && !l.unmatched_name);
      if (!result.name_zh || !result.ingredients.length || missing) {
        fill(error, h('div', { class: 'message error' }, '请填写名称，并为每一行选择食材。'));
        return;
      }
      const unmatched = result.ingredients.filter((l) => !l.ingredient_id).map((l) => l.unmatched_name);
      if (requireMatched && unmatched.length) {
        fill(error, h('div', { class: 'message error' },
          `以下食材不在食材库中：${unmatched.join('、')}。请为它们选择食材库中的食材、删除该行，或先到“食材库”添加。`));
        return;
      }
      close();
      resolve(result);
    }

    const close = openModal(
      h('h3', { style: 'margin-top:0' }, title),
      field('中文名', name, 'margin-right:0'),
      field(analyse ? '做法步骤（可选，不需要每行一步）' : '做法步骤（每行一步）', steps, 'margin-right:0'),
      analyse ? h('div', { class: 'row analyse-row' }, analyseButton, webSearchLabel,
        h('span', { class: 'hint' }, '只填中文名：由 Claude 生成做法（勾选“联网搜索做法”则先上网查菜谱）；也填了做法：整理成每行一步。其余内容一并填好，都可以再修改。')) : null,
      status,
      h('h3', {}, '基本信息'),
      h('div', { class: 'row' },
        field('英文名', nameEn),
        field('类型', type),
        field('份数', servings),
        field('整道菜热量 kcal', kcal)),
      analyse ? field('参考链接', sourceUrl, 'margin-right:0') : null,
      h('h3', {}, '食材'), lines,
      h('button', { class: 'small', onclick: () => { d.ingredients.push({ ingredient_id: null, quantity: null, unit: 'g', note: null }); renderLines(); } }, '+ 添加食材'),
      h('h3', {}, '风格特征（用于相似度计算）'),
      h('div', { class: 'row' }, '主料：', mains),
      h('div', { class: 'row' }, '做法：', method, '菜系：', cuisine),
      h('div', { class: 'row' }, '口味：', flavours.map((f) => h('label', {}, f, label('flavour', f.value)))),
      h('h3', {}, '不确定之处'), notes,
      error,
      h('div', { class: 'row' }, h('span', { class: 'spacer' }), cancelButton, okButton));
    setFields();
    syncWebSearch();
    renderLines();
    renderMains();
  });
}

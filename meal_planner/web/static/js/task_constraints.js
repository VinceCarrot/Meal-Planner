// Task-only constraints (for one generation or one adjustment): enter text,
// parse with Claude, adjust strictness and explicit overrides, check conflicts.
// Generation and adjustment each create their own editor, so their inputs stay separate.

import { post } from './api.js';
import { h, fill, badge, label, describeExecution, showError } from './ui.js';

export function constraintTable(list, { persistent = [], onChange, onRemove } = {}) {
  const editable = Boolean(onChange);
  const overrides = (c) => h('div', {}, persistent.map((p) => h('label', { title: p.description },
    h('input', {
      type: 'checkbox',
      checked: c.overrides.includes(p.constraint_id),
      onchange: (e) => {
        c.overrides = e.target.checked ? [...c.overrides, p.constraint_id] : c.overrides.filter((x) => x !== p.constraint_id);
        onChange();
      },
    }), p.constraint_id)));
  const headers = ['ID', '描述', '类型', '状态', '解释 / 说明', ...(editable ? ['本次替代长期约束', ''] : [])];
  return h('table', {},
    h('tr', {}, headers.map((t) => h('th', {}, t))),
    list.map((c, i) => h('tr', {},
      h('td', {}, c.constraint_id),
      h('td', {}, c.description),
      h('td', {}, editable
        ? h('select', { onchange: (e) => { c.strictness = e.target.value; onChange(); } },
          ['hard', 'soft'].map((s) => h('option', { value: s, selected: c.strictness === s }, label('strictness', s))))
        : label('strictness', c.strictness)),
      h('td', {}, badge(c.status || c.parse_status)),
      h('td', {}, describeExecution(c.execution), c.parse_notes ? h('div', { class: 'hint' }, c.parse_notes) : null),
      editable ? h('td', {}, overrides(c)) : null,
      editable ? h('td', {}, h('button', { class: 'small danger', onclick: () => onRemove(i) }, '移除')) : null)));
}

export function taskConstraintEditor({ task, placeholder }) {
  const state = { inputs: [''], parsed: [], parsedFrom: [], persistent: [] };
  const inputsBox = h('div');
  const parsedBox = h('div');
  const checkBox = h('div');
  const element = h('div', {},
    inputsBox,
    h('div', { class: 'row' },
      h('button', { onclick: () => { state.inputs.push(''); renderInputs(); } }, '+ 添加一条'),
      h('button', { onclick: parse }, '用 Claude 解析')),
    parsedBox,
    checkBox);

  const texts = () => state.inputs.map((t) => t.trim()).filter(Boolean);
  const isCurrent = () => JSON.stringify(texts()) === JSON.stringify(state.parsedFrom);

  function renderInputs() {
    fill(inputsBox, state.inputs.map((text, i) => h('div', { class: 'row' },
      h('input', { value: text, style: 'flex:1', placeholder, oninput: (e) => { state.inputs[i] = e.target.value; renderParsed(); } }),
      h('button', { class: 'small danger', onclick: () => { state.inputs.splice(i, 1); renderInputs(); renderParsed(); } }, '删除'))));
  }

  function renderParsed() {
    if (!isCurrent()) {
      fill(parsedBox, texts().length ? h('div', { class: 'hint' }, '输入后请点击“用 Claude 解析”。') : null);
      fill(checkBox);
      return;
    }
    fill(parsedBox, state.parsed.length ? constraintTable(state.parsed, {
      persistent: state.persistent,
      onChange: check,
      onRemove: (i) => { state.parsed.splice(i, 1); renderParsed(); check(); },
    }) : null);
  }

  async function parse() {
    fill(checkBox);
    if (!texts().length) {
      state.parsed = [];
      state.parsedFrom = [];
      renderParsed();
      return check();
    }
    try {
      state.parsed = await post('/api/task-constraints/parse', { task, items: texts().map((d) => ({ description: d })) }, '正在用 Claude 解析约束…');
      state.parsedFrom = texts();
      renderParsed();
      await check();
    } catch (err) {
      showError(checkBox, err);
    }
  }

  async function check() {
    try {
      const eff = await post('/api/constraints/effective', { task, task_constraints: state.parsed });
      fill(checkBox, eff.issues.length
        ? h('div', { class: 'message warning' }, '需要先处理：',
          h('ul', {}, eff.issues.map((i) => h('li', {}, `${i.constraint_ids.join('、')}：${i.message}`))),
          h('div', { class: 'hint' }, '冲突可以勾选“本次替代长期约束”来明确处理，或修改文字后重新解析。'))
        : h('div', { class: 'message info' }, '约束检查通过。'));
    } catch (err) {
      fill(checkBox);
      showError(checkBox, err);
    }
  }

  renderInputs();
  return {
    element,
    setPersistent(list) { state.persistent = list; renderParsed(); },
    parsed: () => state.parsed,
    // A reason the current input cannot be used yet, or null.
    problem: () => (texts().length && !isCurrent() ? `请先解析${label('task', task)}的附加约束。` : null),
  };
}

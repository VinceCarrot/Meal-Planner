// Persistent constraints: add, edit, enable/disable, delete, parse.

import { get, post, put, del } from '../../js/api.js';
import { h, fill, badge, label, describeExecution, showError, toast } from '../../js/ui.js';

const TASKS = ['menu_generation', 'menu_adjustment'];
let root;
let messages;
let table;

export async function showConstraints() {
  if (!root) build();
  await refresh();
}

function build() {
  root = document.getElementById('constraints_root');
  const text = h('textarea', { placeholder: '用一两句话描述，例如：每顿饭三到四个菜，其中一个汤' });
  const scopes = TASKS.map((t) => h('input', { type: 'checkbox', checked: true, value: t }));
  messages = h('div');
  table = h('div');
  fill(root,
    messages,
    h('div', { class: 'panel' },
      h('h3', {}, '新增长期约束'),
      text,
      h('div', { class: 'row' },
        '适用于：', TASKS.map((t, i) => h('label', {}, scopes[i], label('task', t))),
        h('span', { class: 'spacer' }),
        h('button', {
          class: 'primary',
          onclick: async () => {
            const scope = scopes.filter((s) => s.checked).map((s) => s.value);
            if (!text.value.trim() || !scope.length) return;
            await run(() => post('/api/constraints', { description: text.value, scope }));
            text.value = '';
          },
        }, '添加'))),
    h('div', { class: 'row' },
      h('button', { onclick: () => run(() => post('/api/constraints/parse', {}, '正在用 Claude 解析未解析的约束…'), '解析完成') }, '用 Claude 解析所有“未解析”的约束'),
      h('button', {
        onclick: async () => {
          let ids;
          try {
            ids = (await get('/api/constraints')).filter((c) => !['unparsed', 'executable'].includes(c.parse_status)).map((c) => c.constraint_id);
          } catch (err) {
            showError(messages, err);
            return;
          }
          if (!ids.length) { toast('没有需要重新解析的约束'); return; }
          if (window.confirm(`用 Claude 重新解析 ${ids.join('、')}？原来的解释会被替换。`)) {
            run(() => post('/api/constraints/parse', { constraint_ids: ids }, '正在用 Claude 重新解析约束…'), '重新解析完成');
          }
        },
      }, '重新解析“不支持 / 近似 / 需澄清”的约束'),
      h('span', { class: 'hint' }, '解析结果由程序校验；无法表达的约束会如实标为“不支持”或“需澄清”。')),
    table);
}

async function run(action, doneText) {
  fill(messages);
  try {
    await action();
    if (doneText) toast(doneText);
  } catch (err) {
    showError(messages, err);
  }
  await refresh();
}

async function refresh() {
  try {
    render(await get('/api/constraints'));
  } catch (err) {
    showError(messages, err);
  }
}

function render(constraints) {
  if (!constraints.length) {
    fill(table, h('p', { class: 'hint' }, '还没有长期约束。'));
    return;
  }
  fill(table, h('table', {},
    h('tr', {}, ['ID', '描述', '适用于', '类型', '启用', '解析状态', '解释 / 说明', ''].map((t) => h('th', {}, t))),
    constraints.map((c) => h('tr', {},
      h('td', {}, c.constraint_id),
      h('td', {}, c.description),
      h('td', {}, TASKS.map((t) => h('label', {},
        h('input', {
          type: 'checkbox',
          checked: c.scope.includes(t),
          onchange: (e) => {
            const scope = e.target.checked ? [...c.scope, t] : c.scope.filter((s) => s !== t);
            if (scope.length) run(() => put(`/api/constraints/${c.constraint_id}`, { scope }));
            else refresh();
          },
        }), label('task', t)))),
      h('td', {}, h('select', { onchange: (e) => run(() => put(`/api/constraints/${c.constraint_id}`, { strictness: e.target.value })) },
        ['hard', 'soft'].map((s) => h('option', { value: s, selected: c.strictness === s }, label('strictness', s))))),
      h('td', {}, h('input', { type: 'checkbox', checked: c.active, onchange: (e) => run(() => put(`/api/constraints/${c.constraint_id}`, { active: e.target.checked })) })),
      h('td', {}, badge(c.parse_status)),
      h('td', {}, describeExecution(c.execution), c.parse_notes ? h('div', { class: 'hint' }, c.parse_notes) : null),
      h('td', {},
        h('button', {
          class: 'small',
          onclick: () => {
            const description = window.prompt('修改描述（修改后需要重新解析）', c.description);
            if (description && description.trim() !== c.description) run(() => put(`/api/constraints/${c.constraint_id}`, { description: description.trim() }));
          },
        }, '改描述'),
        ' ',
        h('button', {
          class: 'small',
          onclick: () => run(() => post('/api/constraints/parse', { constraint_ids: [c.constraint_id] }, `正在用 Claude 重新解析 ${c.constraint_id}…`), '重新解析完成'),
        }, '重新解析'),
        ' ',
        h('button', {
          class: 'small danger',
          onclick: () => { if (window.confirm(`删除约束 ${c.constraint_id}？`)) run(() => del(`/api/constraints/${c.constraint_id}`)); },
        }, '删除'))))));
}

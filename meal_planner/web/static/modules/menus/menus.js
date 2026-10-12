// Saved menus and their versions; replacing a dish creates a new version.

import { get, post } from '../../js/api.js';
import { h, fill, badge, describeExecution, label, showError, showMessage, toast, weekday } from '../../js/ui.js';
import { statusBanner, menuGrid, reportTable } from '../../js/menu_view.js';
import { taskConstraintEditor } from '../../js/task_constraints.js';

const TASK = 'menu_adjustment';
const SCOPES = { dish: '只换这道菜', dinner: '重排这一餐', week: '调整这一周', menu: '调整整份菜单' };
const FEEDBACK = [
  ['', '不记录（只是想换换）'],
  ['this_menu', '不喜欢，仅针对这份菜单'],
  ['future_menus', '不喜欢，以后的菜单也尽量避免'],
  ['persistent', '长期不喜欢'],
];

let root;
let listBox;
let detailBox;
let editor;
let adjust; // {menu, target: {date, dish}, proposal}

export async function showMenus(menuId) {
  if (!root) {
    root = document.getElementById('menus_root');
    listBox = h('div', { class: 'panel' });
    detailBox = h('div');
    editor = taskConstraintEditor({ task: TASK, placeholder: '只用于这次调整，例如：这次换成清淡一点的' });
    fill(root, listBox, detailBox);
  }
  try {
    renderList(await get('/api/menus'));
    const persistent = (await get('/api/constraints')).filter((c) => c.active && c.scope.includes(TASK));
    editor.setPersistent(persistent);
    if (menuId) await openMenu(menuId);
  } catch (err) {
    fill(listBox);
    showError(listBox, err);
  }
}

function renderList(menus) {
  if (!menus.length) {
    fill(listBox, h('p', { class: 'hint' }, '还没有保存的菜单。'));
    return;
  }
  fill(listBox, h('table', {},
    h('tr', {}, ['菜单', '起始日期', '版本数', '最新版本状态', '保存时间', '说明'].map((t) => h('th', {}, t))),
    menus.map((m) => h('tr', { class: 'clickable', onclick: () => openMenu(m.menu_id) },
      h('td', {}, m.menu_id),
      h('td', {}, m.start_date),
      h('td', {}, String(m.versions.length)),
      h('td', {}, m.status ? badge(m.status) : ''),
      h('td', {}, m.created_at.replace('T', ' ')),
      h('td', {}, m.change_note || '')))));
}

async function openMenu(menuId, version) {
  try {
    const menu = await get(`/api/menus/${menuId}${version ? `?version=${version}` : ''}`);
    adjust = { menu, target: null, proposal: null };
    renderMenu();
  } catch (err) {
    fill(detailBox);
    showError(detailBox, err);
  }
}

const changedSet = (changes) => new Set((changes || []).flatMap((c) => c.added.map((d) => `${c.date}|${d.dish_id}`)));

function changeList(changes) {
  return h('ul', {}, changes.map((c) => h('li', {},
    `${c.date} ${weekday(c.date)}：`,
    c.removed.length ? `去掉 ${c.removed.map((d) => d.name_zh).join('、')}` : '',
    c.removed.length && c.added.length ? '；' : '',
    c.added.length ? `换上 ${c.added.map((d) => d.name_zh).join('、')}` : '')));
}

function renderMenu() {
  const { menu } = adjust;
  const report = menu.validation_report;
  const versionSelect = h('select', { onchange: (e) => openMenu(menu.menu_id, e.target.value) },
    menu.versions.map((v) => h('option', { value: v, selected: v === menu.version }, `第 ${v} 版`)));
  fill(detailBox,
    h('div', { class: 'panel' },
      h('div', { class: 'row' },
        h('h3', { style: 'margin:0' }, `${menu.menu_id}（${menu.start_date} 起）`),
        versionSelect,
        h('span', { class: 'spacer' }),
        h('span', { class: 'hint' }, `保存于 ${menu.created_at.replace('T', ' ')}`)),
      menu.change_note ? h('p', {}, `说明：${menu.change_note}`) : null,
      menu.based_on_version ? h('div', {}, h('span', { class: 'hint' }, `基于第 ${menu.based_on_version} 版的改动：`), changeList(menu.changes || [])) : null,
      h('p', {}, `就餐者：${menu.diners.map((d) => `${d.description} × ${d.count}`).join('，')}`),
      report ? statusBanner(report.status) : null,
      h('p', { class: 'hint' }, '点击某道菜可以替换它。'),
      menuGrid(menu.dinners, {
        onDish: (dinner, dish) => { adjust.target = { date: dinner.date, dish }; adjust.proposal = null; renderMenu(); },
        highlight: changedSet(menu.changes),
        target: adjust.target ? `${adjust.target.date}|${adjust.target.dish.dish_id}` : null,
      })),
    adjust.target ? adjustPanel() : null,
    h('div', { class: 'panel' }, h('h3', {}, '本版本的约束检查结果'), reportTable(report)),
    h('details', { class: 'panel' },
      h('summary', {}, `本版本使用的约束（${menu.constraint_snapshot.length} 条）`),
      h('table', {}, menu.constraint_snapshot.map((c) => h('tr', {},
        h('td', {}, c.constraint_id), h('td', {}, label('source', c.source)), h('td', {}, c.description),
        h('td', {}, label('strictness', c.strictness)), h('td', {}, describeExecution(c.execution)))))));
}

function adjustPanel() {
  const { target, proposal } = adjust;
  const feedback = h('select', {}, FEEDBACK.map(([value, text]) => h('option', { value, selected: adjust.feedback === value }, text)));
  const feedbackNote = h('input', { placeholder: '原因（可选），例如：太油', value: adjust.feedbackNote || '' });
  feedback.onchange = () => { adjust.feedback = feedback.value; };
  feedbackNote.oninput = () => { adjust.feedbackNote = feedbackNote.value; };
  const messages = h('div');
  return h('div', { class: 'panel' },
    h('h3', {}, `替换 ${target.date} ${weekday(target.date)} 的「${target.dish.name_zh}」`),
    h('div', { class: 'row' }, '反馈：', feedback, feedbackNote),
    h('p', { class: 'hint' }, '“不喜欢”不会从菜品库删除这道菜；以后的菜单会尽量避开它（软约束）。'),
    h('h3', {}, '这次调整的附加约束（只用于这次调整）'),
    editor.element,
    h('div', { class: 'row' },
      h('button', { class: 'primary', onclick: () => propose(messages) }, '生成替换方案'),
      h('button', { onclick: () => { adjust.target = null; adjust.proposal = null; renderMenu(); } }, '取消'),
      h('span', { class: 'hint' }, '先只换这道菜；不行时才会逐步扩大到这一餐、这一周、整份菜单。')),
    messages,
    proposal ? proposalView(proposal) : null);
}

async function propose(messages) {
  fill(messages);
  if (editor.problem()) {
    showMessage(messages, 'warning', editor.problem());
    return;
  }
  try {
    adjust.proposal = await post(`/api/menus/${adjust.menu.menu_id}/adjust/propose`, {
      version: adjust.menu.version,
      date: adjust.target.date,
      dish_id: adjust.target.dish.dish_id,
      task_constraints: editor.parsed(),
    }, '正在计算替换方案…');
    renderMenu();
  } catch (err) {
    showError(messages, err);
  }
}

function proposalView(p) {
  const note = h('input', { style: 'flex:1', value: `替换 ${adjust.target.date} 的${adjust.target.dish.name_zh}` });
  const messages = h('div');
  return h('div', {},
    h('h3', {}, '替换方案'),
    h('ul', {}, p.attempts.map((a) => h('li', {}, `${SCOPES[a.scope]}：`, badge(a.status), a.message ? ` ${a.message}` : ''))),
    p.dinners.length
      ? h('div', {},
        statusBanner(p.status),
        p.scope !== 'dish' ? h('div', { class: 'message warning' }, `只换这道菜无法满足约束，方案的调整范围是“${SCOPES[p.scope]}”。`) : null,
        h('div', {}, '改动：', changeList(p.changes)),
        menuGrid(p.dinners, { highlight: changedSet(p.changes) }),
        reportTable(p.report),
        h('div', { class: 'row' }, '修改说明：', note,
          h('button', { class: 'primary', onclick: () => saveProposal(note.value, messages) }, '确认并保存为新版本')),
        messages)
      : statusBanner(p.status, ['在所有范围内都没有找到满足约束的替换方案，菜单没有改动。']));
}

async function saveProposal(changeNote, messages) {
  fill(messages);
  const { menu, target, proposal } = adjust;
  try {
    const saved = await post(`/api/menus/${menu.menu_id}/adjust/save`, {
      version: menu.version,
      dinners: proposal.dinners.map((d) => ({ date: d.date, dish_ids: d.dishes.map((x) => x.dish_id) })),
      task_constraints: editor.parsed(),
      change_note: changeNote,
      feedback: adjust.feedback ? { dish_id: target.dish.dish_id, scope: adjust.feedback, note: adjust.feedbackNote || null } : null,
    });
    toast(`已保存为第 ${saved.version} 版（${label('status', saved.status)}）`);
    await showMenus(menu.menu_id);
  } catch (err) {
    showError(messages, err);
  }
}

// Menu generation: diners, persistent + task constraints, planning, saving.

import { get, post, put } from '../../js/api.js';
import { h, fill, badge, label, describeExecution, showError, showMessage, toast, nextMonday } from '../../js/ui.js';
import { statusBanner, menuGrid, reportTable } from '../../js/menu_view.js';
import { openPage } from '../../js/nav.js';

const TASK = 'menu_generation';
const state = {
  diners: [],
  inputs: [''], // task constraint texts
  parsed: [], // parsed task constraints (Constraint objects)
  parsedFrom: null, // inputs the parsed list was made from
  persistent: [],
  result: null,
};
let root;
let els;

export async function showPlan() {
  if (!root) build();
  try {
    state.persistent = (await get('/api/constraints')).filter((c) => c.active && c.scope.includes(TASK));
    if (!state.diners.length) state.diners = (await get('/api/preferences')).default_diners;
  } catch (err) {
    showError(els.status, err);
  }
  renderDiners();
  renderPersistent();
  renderTaskConstraints();
}

function build() {
  root = document.getElementById('plan_root');
  els = {
    status: h('div'),
    start: h('input', { type: 'date', value: nextMonday() }),
    diners: h('div'),
    persistent: h('div'),
    inputs: h('div'),
    parsed: h('div'),
    effective: h('div'),
    result: h('div'),
  };
  fill(root,
    els.status,
    h('div', { class: 'panel' },
      h('h3', {}, '基本信息'),
      h('div', { class: 'row' }, h('label', {}, '起始周一：', els.start),
        h('span', { class: 'hint' }, '计划覆盖从这天开始的四周，每周一到周五。')),
      h('h3', {}, '就餐者'),
      els.diners),
    h('div', { class: 'panel' },
      h('h3', {}, '长期约束（自动适用）'),
      els.persistent,
      h('p', { class: 'hint' }, '在“长期约束”页可以增删和修改。')),
    h('div', { class: 'panel' },
      h('h3', {}, '本次附加约束（只用于这一次生成，不会保存为长期约束）'),
      els.inputs,
      h('div', { class: 'row' },
        h('button', { onclick: () => { state.inputs.push(''); renderInputs(); } }, '+ 添加一条'),
        h('button', { onclick: parseTaskConstraints }, '用 Claude 解析附加约束')),
      els.parsed,
      els.effective),
    h('div', { class: 'row' },
      h('button', { class: 'primary', onclick: plan }, '生成菜单'),
      h('span', { class: 'hint' }, '求解通常需要几秒到半分钟。')),
    els.result);
  renderInputs();
}

// --- Diners --------------------------------------------------------------------

function renderDiners() {
  fill(els.diners,
    state.diners.map((d, i) => h('div', { class: 'row' },
      h('input', { value: d.description, placeholder: '例如：成年女性', oninput: (e) => { d.description = e.target.value; } }),
      h('input', { type: 'number', min: 1, value: d.count, oninput: (e) => { d.count = Number(e.target.value); } }),
      h('span', {}, '人'),
      h('button', { class: 'small danger', onclick: () => { state.diners.splice(i, 1); renderDiners(); } }, '删除'))),
    h('div', { class: 'row' },
      h('button', { class: 'small', onclick: () => { state.diners.push({ description: '', count: 1 }); renderDiners(); } }, '+ 添加'),
      h('button', { class: 'small', onclick: saveDefaultDiners }, '设为默认就餐者')));
}

async function saveDefaultDiners() {
  try {
    await put('/api/preferences/diners', { diners: state.diners });
    toast('已保存为默认就餐者');
  } catch (err) {
    showError(els.status, err);
  }
}

// --- Constraints -----------------------------------------------------------------

function constraintRows(list, { editable = false } = {}) {
  return h('table', {},
    h('tr', {}, ['ID', '描述', '类型', '状态', '解释 / 说明', editable ? '本次替代长期约束' : null, editable ? '' : null]
      .filter((t) => t !== null).map((t) => h('th', {}, t))),
    list.map((c, i) => h('tr', {},
      h('td', {}, c.constraint_id),
      h('td', {}, c.description),
      h('td', {}, editable
        ? h('select', { onchange: (e) => { c.strictness = e.target.value; checkEffective(); } },
          ['hard', 'soft'].map((s) => h('option', { value: s, selected: c.strictness === s }, label('strictness', s))))
        : label('strictness', c.strictness)),
      h('td', {}, badge(c.parse_status)),
      h('td', {}, describeExecution(c.execution), c.parse_notes ? h('div', { class: 'hint' }, c.parse_notes) : null),
      editable ? h('td', {}, overrideSelect(c)) : null,
      editable ? h('td', {}, h('button', { class: 'small danger', onclick: () => { state.parsed.splice(i, 1); renderParsed(); checkEffective(); } }, '移除')) : null)));
}

function overrideSelect(c) {
  return h('div', {}, state.persistent.map((p) => h('label', { title: p.description },
    h('input', {
      type: 'checkbox',
      checked: c.overrides.includes(p.constraint_id),
      onchange: (e) => {
        c.overrides = e.target.checked ? [...c.overrides, p.constraint_id] : c.overrides.filter((x) => x !== p.constraint_id);
        checkEffective();
      },
    }), p.constraint_id)));
}

function renderPersistent() {
  fill(els.persistent, state.persistent.length ? constraintRows(state.persistent) : h('p', { class: 'hint' }, '还没有长期约束。'));
}

function renderInputs() {
  fill(els.inputs, state.inputs.map((text, i) => h('div', { class: 'row' },
    h('input', { value: text, style: 'flex:1', placeholder: '例如：这次每顿都要有鱼；这次不要汤', oninput: (e) => { state.inputs[i] = e.target.value; renderTaskConstraints(); } }),
    h('button', { class: 'small danger', onclick: () => { state.inputs.splice(i, 1); renderInputs(); renderTaskConstraints(); } }, '删除'))));
}

const inputTexts = () => state.inputs.map((t) => t.trim()).filter(Boolean);
const parsedIsCurrent = () => JSON.stringify(inputTexts()) === JSON.stringify(state.parsedFrom || []);

function renderTaskConstraints() {
  if (!parsedIsCurrent() && state.parsed.length) {
    fill(els.parsed, h('div', { class: 'message warning' }, '附加约束的文字已修改，请重新解析。'));
    fill(els.effective);
    return;
  }
  renderParsed();
}

function renderParsed() {
  fill(els.parsed, state.parsed.length ? constraintRows(state.parsed, { editable: true }) : null);
}

async function parseTaskConstraints() {
  fill(els.status);
  const texts = inputTexts();
  if (!texts.length) {
    state.parsed = [];
    state.parsedFrom = [];
    renderParsed();
    return checkEffective();
  }
  try {
    state.parsed = await post('/api/task-constraints/parse', { task: TASK, items: texts.map((d) => ({ description: d })) }, '正在用 Claude 解析附加约束…');
    state.parsedFrom = texts;
    renderParsed();
    await checkEffective();
  } catch (err) {
    showError(els.status, err);
  }
}

async function checkEffective() {
  try {
    const eff = await post('/api/constraints/effective', { task: TASK, task_constraints: state.parsed });
    fill(els.effective, eff.issues.length
      ? h('div', { class: 'message warning' }, '生成前需要处理：',
        h('ul', {}, eff.issues.map((i) => h('li', {}, `${i.constraint_ids.join('、')}：${i.message}`))),
        h('div', { class: 'hint' }, '冲突可以通过勾选“本次替代长期约束”明确处理，或修改约束文字后重新解析。'))
      : h('div', { class: 'message info' }, '约束检查通过，可以生成菜单。'));
  } catch (err) {
    fill(els.effective);
    showError(els.effective, err);
  }
}

// --- Planning and saving -------------------------------------------------------------

async function plan() {
  fill(els.status);
  if (inputTexts().length && !parsedIsCurrent()) {
    showMessage(els.status, 'warning', '请先解析本次附加约束。');
    return;
  }
  try {
    state.result = await post('/api/menus/plan', { start_date: els.start.value, task_constraints: state.parsed }, '正在生成菜单…');
    state.startDate = els.start.value;
    renderResult();
  } catch (err) {
    fill(els.result);
    showError(els.result, err);
  }
}

function renderResult() {
  const r = state.result;
  const note = h('input', { placeholder: '版本说明（可选）', style: 'flex:1' });
  fill(els.result,
    h('h3', {}, '生成结果'),
    statusBanner(r.status, r.messages),
    r.gaps.length ? gapsPanel(r.gaps) : null,
    r.relaxation_candidates.length
      ? h('div', { class: 'message warning' }, `单独放宽以下任意一条硬约束即可排出菜单（是否放宽由你决定）：${r.relaxation_candidates.join('、')}`)
      : null,
    r.dinners.length ? menuGrid(r.dinners) : null,
    r.solver ? h('p', { class: 'hint' }, `求解 ${r.solver.seconds} 秒（${r.solver.status}）`,
      r.repair && r.repair.steps ? `，局部调整 ${r.repair.steps} 次，惩罚分 ${r.repair.penalty_before} → ${r.repair.penalty_after}` : '',
      r.penalty_total != null ? `；总惩罚分 ${r.penalty_total}` : '') : null,
    r.report ? h('h3', {}, '约束检查结果') : null,
    reportTable(r.report),
    r.dinners.length ? h('div', { class: 'panel' },
      h('div', { class: 'row' }, note, h('button', { class: 'primary', onclick: () => save(note.value) }, '保存菜单'))) : null);
}

function gapsPanel(gaps) {
  return h('div', { class: 'panel' },
    h('h3', {}, '菜品库缺口'),
    gaps.map((g) => h('div', { class: 'row' },
      h('span', { style: 'flex:1' }, g.description),
      h('button', { onclick: () => generateFor(g) }, `让 Claude 生成 ${g.suggested_count} 道${g.dish_type ? label('dish_type', g.dish_type) : '菜'}候选`))),
    h('p', { class: 'hint' }, '生成的候选菜需要在“候选审核”页通过后才会进入菜品库，然后再重新生成菜单。'));
}

async function generateFor(gap) {
  try {
    const result = await post('/api/candidates/generate', {
      requests: [{ dish_type: gap.dish_type, count: gap.suggested_count, reason: gap.description }],
      task_constraints: state.parsed,
    }, '正在用 Claude 生成候选菜（可能需要一两分钟）…');
    toast(`已生成 ${result.added.length} 道候选菜，${result.rejected.length} 道未通过校验`);
    openPage('review');
  } catch (err) {
    showError(els.result, err);
  }
}

async function save(changeNote) {
  const r = state.result;
  if (r.status !== 'feasible' && !window.confirm(`当前状态是“${label('status', r.status)}”，确定要保存吗？`)) return;
  try {
    const saved = await post('/api/menus', {
      start_date: state.startDate,
      diners: state.diners,
      dinners: r.dinners.map((d) => ({ date: d.date, dish_ids: d.dishes.map((x) => x.dish_id) })),
      task_constraints: state.parsed,
      change_note: changeNote,
    });
    toast(`已保存为 ${saved.menu_id}（第 ${saved.version} 版，${label('status', saved.status)}）`);
    openPage('menus', saved.menu_id);
  } catch (err) {
    showError(els.result, err);
  }
}

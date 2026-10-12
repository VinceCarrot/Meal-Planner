// Rendering shared by the plan and menu-history pages: status banner, the
// 4 x 5 dinner grid and the per-constraint validation report.

import { h, badge, label, dishTypeTag, weekday } from './ui.js';

const STATUS_TEXT = {
  feasible: '所有约束都已检查，硬约束全部满足。',
  feasible_with_unresolved: '硬约束全部满足，但有约束只能近似检查或无法评估，请查看下方结果。',
  best_effort: '这是尽力方案：至少有一条硬约束未满足或无法检查，请查看下方结果。',
  infeasible: '在当前菜品库和硬约束下无法排出菜单。',
  no_solution_found: '在时间限制内没有找到菜单，是否可行尚不确定，可在设置中延长时间后重试。',
  blocked: '需要先处理下面的约束问题。',
};

export function statusBanner(status, messages = []) {
  const kind = { feasible: 'info', feasible_with_unresolved: 'warning', no_solution_found: 'warning' }[status] || 'error';
  return h('div', { class: `message ${kind}` },
    h('div', {}, badge(status), ' ', STATUS_TEXT[status] || ''),
    messages.length ? h('ul', {}, messages.map((m) => h('li', {}, m))) : null);
}

// `dinners`: [{date, dishes: [{dish_id, name_zh, dish_type}], known_kcal, kcal_complete}]
// `onDish(dinner, dish)`: optional click handler (used to pick a dish to replace).
// `highlight`: optional set of "date|dish_id" strings to mark.
export function menuGrid(dinners, { onDish, highlight } = {}) {
  const weeks = [];
  for (let i = 0; i < dinners.length; i += 5) weeks.push(dinners.slice(i, i + 5));
  return h('table', { class: 'menu-grid' },
    h('tr', {}, h('th', {}, ''), ['周一', '周二', '周三', '周四', '周五'].map((d) => h('th', {}, d))),
    weeks.map((week, w) => h('tr', {},
      h('th', {}, `第 ${w + 1} 周`),
      week.map((dinner) => h('td', {},
        h('div', { class: 'menu-date' }, `${dinner.date.slice(5)} ${weekday(dinner.date)}`),
        h('ul', { class: 'menu-dishes' }, dinner.dishes.map((dish) => h('li', {
          class: [onDish ? 'pickable' : '', highlight && highlight.has(`${dinner.date}|${dish.dish_id}`) ? 'changed' : ''].join(' '),
          title: dish.dish_id,
          onclick: onDish ? () => onDish(dinner, dish) : null,
        }, dishTypeTag(dish.dish_type), dish.name_zh))),
        dinner.known_kcal != null
          ? h('div', { class: 'menu-kcal' }, `约 ${Math.round(dinner.known_kcal)} kcal`, dinner.kcal_complete ? '' : '（数据不全）')
          : null)))));
}

export function reportTable(report) {
  if (!report) return null;
  const rows = report.results.map((r) => h('tr', {},
    h('td', {}, r.constraint_id),
    h('td', {}, r.description),
    h('td', {}, label('strictness', r.strictness)),
    h('td', {}, badge(r.status)),
    h('td', {}, r.detail, r.violations.length
      ? h('details', {}, h('summary', {}, `查看 ${r.violations.length} 条`), h('ul', {}, r.violations.map((v) => h('li', {}, v))))
      : null),
    h('td', {}, r.penalty ? String(r.penalty) : '')));
  return h('div', {},
    report.structural_errors.length
      ? h('div', { class: 'message error' }, '菜单结构问题：', h('ul', {}, report.structural_errors.map((e) => h('li', {}, e))))
      : null,
    h('table', {},
      h('tr', {}, ['ID', '约束', '类型', '结果', '说明', '惩罚分'].map((t) => h('th', {}, t))),
      rows),
    report.disliked_servings.length
      ? h('p', { class: 'warn' }, `包含你标记过不喜欢的菜（惩罚分 ${report.preference_penalty}）：${report.disliked_servings.join('；')}`)
      : null,
    h('p', { class: 'hint' }, '热量为根据食材数据的粗略估算，仅供参考；“数据不全”表示部分食材缺少用量或热量数据。'));
}

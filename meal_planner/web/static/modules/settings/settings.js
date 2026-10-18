// Settings: model per LLM task, similarity weights, planner and candidate parameters.

import { get, put } from '../../js/api.js';
import { h, fill, label, showError, toast } from '../../js/ui.js';

const MODELS = [['', '账号默认（通常是 Opus）'], ['sonnet', 'Sonnet（更快、更省额度）'], ['opus', 'Opus'], ['haiku', 'Haiku（最快）']];

const WEIGHTS = {
  main_ingredients: '主料', ingredients: '食材组合（不含调料）', cooking_method: '做法', flavours: '口味', cuisine: '菜系',
};
// [name, how the planner uses it]
const PLANNER = {
  time_limit_s: ['求解时间上限（秒）',
    '排菜时求解器搜索的时间。越长越可能找到扣分更少的菜单，但要等更久；时间到了还没找到可行菜单，会显示“未找到方案”。'],
  workers: ['求解线程数', '求解器同时使用的 CPU 线程数，一般不超过电脑的核心数。'],
  default_dish_similarity_threshold: ['默认菜品相似度阈值',
    '相似度约束没写具体数值时使用（0–1）。两道菜相似度高于此值即算“相似”：硬约束下，约束时间窗口内不会同时出现；软约束下，每出现一对就扣分。数值越小越严格。'],
  default_meal_similarity_threshold: ['默认整餐相似度阈值',
    '同上，但比较两顿晚餐整体：把两顿的菜按最相似的逐对配对，相似度相加后除以菜多的那顿的菜数。高于此值的两顿饭算“相似”。'],
  penalty_soft_count: ['菜数偏差扣分',
    '软约束“每顿几道菜”或“某类菜几道”：某顿每多一道或少一道，扣这么多分。'],
  penalty_soft_exclusion: ['用到排除食材扣分',
    '软约束“尽量不用某食材”：含该食材的菜每排上一次，扣这么多分。'],
  penalty_soft_repeat: ['重复菜扣分',
    '软约束“N 周内不重复”：窗口内同一道菜每重复一对（包括与之前菜单重复），扣这么多分。'],
  penalty_shared_ingredient: ['同顿食材重复扣分',
    '软约束“每顿饭的食材不要重复”：同一顿里每有一对菜用了同一种食材，扣这么多分。'],
  penalty_dish_similarity: ['相似菜扣分',
    '软的菜品相似度约束：窗口内每有一对相似的菜，扣“此值 × 相似度”分。'],
  penalty_meal_similarity: ['相似晚餐扣分',
    '软的整餐相似度约束：窗口内每有两顿相似的晚餐，扣“此值 × 整餐相似度”分。'],
  penalty_disliked: ['不喜欢的菜扣分',
    '你反馈过不喜欢的菜不会被禁止，但每排上一次扣这么多分。想让它几乎不出现，就调大。'],
  penalty_change: ['调整时换掉原菜扣分',
    '调整菜单且范围扩大到整顿、整周或整个菜单时，每换掉一道原有的菜扣这么多分。越大越倾向保留原菜。'],
  repair_max_steps: ['整餐相似度修复最多步数',
    '求解后再逐道替换菜品、降低整餐相似度的最多尝试次数。设为 0 表示不做这一步。'],
};
const CANDIDATES = { factor: '候选数量倍数（× 缺口）', minimum: '每次至少生成几道' };

let root;

export async function showSettings() {
  root = root || document.getElementById('settings_root');
  try {
    render(await get('/api/settings'));
  } catch (err) {
    fill(root);
    showError(root, err);
  }
}

function numberInputs(values, names) {
  return Object.entries(names).map(([key, text]) => {
    const input = h('input', { type: 'number', step: 'any', value: values[key], oninput: (e) => { values[key] = Number(e.target.value); } });
    return h('div', { class: 'field' }, h('span', {}, text), input);
  });
}

// One parameter per line: name, input, explanation.
function describedInputs(values, names) {
  return Object.entries(names).map(([key, [text, help]]) => h('label', { class: 'param-row' },
    h('span', { class: 'param-name' }, text),
    h('input', { type: 'number', step: 'any', value: values[key], oninput: (e) => { values[key] = Number(e.target.value); } }),
    h('span', { class: 'param-help' }, help)));
}

function render(settings) {
  const messages = h('div');
  const modelRows = Object.keys(settings.models).map((task) => {
    const current = settings.models[task] || '';
    const options = MODELS.some(([v]) => v === current) ? MODELS : [...MODELS, [current, current]];
    return h('div', { class: 'row' },
      h('span', { style: 'width:120px' }, label('llm_task', task)),
      h('select', { onchange: (e) => { settings.models[task] = e.target.value || null; } },
        options.map(([value, text]) => h('option', { value, selected: value === current }, text))));
  });
  fill(root,
    messages,
    h('div', { class: 'panel' }, h('h3', {}, '各任务使用的模型'), modelRows,
      h('p', { class: 'hint' }, '通过本机的 Claude Code 命令行调用，使用你的 Claude 订阅。')),
    h('div', { class: 'panel' }, h('h3', {}, '菜品相似度权重'), h('div', { class: 'row' }, numberInputs(settings.similarity_weights, WEIGHTS)),
      h('p', { class: 'hint' }, '缺失的特征不参与计算，剩余权重按比例重新分配。')),
    h('div', { class: 'panel' }, h('h3', {}, '规划参数与惩罚分'),
      h('p', { class: 'hint' }, '规划器先保证所有硬约束，再在满足硬约束的菜单里挑总扣分最少的。下面的“扣分”只对软约束和偏好起作用，数值之间的相对大小决定哪条更优先。'),
      describedInputs(settings.planner, PLANNER)),
    h('div', { class: 'panel' }, h('h3', {}, '候选菜生成'), h('div', { class: 'row' }, numberInputs(settings.candidates, CANDIDATES))),
    h('div', { class: 'row' }, h('button', {
      class: 'primary',
      onclick: async () => {
        fill(messages);
        try {
          render(await put('/api/settings', settings));
          toast('设置已保存');
        } catch (err) {
          showError(messages, err);
        }
      },
    }, '保存设置')));
}

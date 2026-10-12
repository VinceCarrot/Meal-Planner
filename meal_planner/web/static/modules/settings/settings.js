// Settings: model per LLM task, similarity weights, planner and candidate parameters.

import { get, put } from '../../js/api.js';
import { h, fill, label, showError, toast } from '../../js/ui.js';

const MODELS = [['', '账号默认（通常是 Opus）'], ['sonnet', 'Sonnet（更快、更省额度）'], ['opus', 'Opus'], ['haiku', 'Haiku（最快）']];

const WEIGHTS = {
  main_ingredients: '主料', ingredients: '食材组合（不含调料）', cooking_method: '做法', flavours: '口味', cuisine: '菜系',
};
const PLANNER = {
  time_limit_s: '求解时间上限（秒）',
  workers: '求解线程数',
  default_dish_similarity_threshold: '默认菜品相似度阈值',
  default_meal_similarity_threshold: '默认整餐相似度阈值',
  penalty_soft_count: '软约束：菜数偏差（每道每餐）',
  penalty_soft_exclusion: '软约束：用到排除食材（每次）',
  penalty_soft_repeat: '软约束：窗口内重复（每对）',
  penalty_dish_similarity: '菜品相似（× 相似度，每对）',
  penalty_meal_similarity: '整餐相似（× 相似度，每对）',
  penalty_disliked: '不喜欢的菜（每次）',
  repair_max_steps: '局部调整最多步数',
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
    h('div', { class: 'panel' }, h('h3', {}, '规划参数与惩罚分'), h('div', { class: 'row' }, numberInputs(settings.planner, PLANNER))),
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

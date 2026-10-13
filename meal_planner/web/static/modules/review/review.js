// Batch review of candidate dishes: approve, edit, reject; plus manual generation.

import { get, post } from '../../js/api.js';
import { h, fill, label, badge, showError, showMessage, toast, LABELS } from '../../js/ui.js';
import { editDish } from '../../js/dish_editor.js';
import { dishDetail } from '../dishes/dishes.js';

let root;
let messages;
let pendingBox;
let rejectedBox;
let ingredients = [];
let decisions = {}; // dish_id -> {action: 'approve'|'reject'|'', edited: dish|null}

export async function showReview() {
  if (!root) build();
  await refresh();
}

function build() {
  root = document.getElementById('review_root');
  messages = h('div');
  pendingBox = h('div');
  rejectedBox = h('div');
  const type = h('select', {}, h('option', { value: '' }, '任意类型'),
    Object.keys(LABELS.dish_type).map((t) => h('option', { value: t }, label('dish_type', t))));
  const count = h('input', { type: 'number', min: 1, max: 30, value: 5 });
  const reason = h('input', { placeholder: '想要什么样的菜（可选）', style: 'flex:1' });
  const videoUrl = h('input', { placeholder: 'https://www.bilibili.com/video/BV… 或 https://www.youtube.com/watch?v=…', style: 'flex:1' });
  fill(root,
    messages,
    h('div', { class: 'panel' },
      h('h3', {}, '让 Claude 生成候选菜'),
      h('div', { class: 'row' }, type, count, '道', reason,
        h('button', { onclick: () => generate(type.value, Number(count.value), reason.value) }, '生成')),
      h('p', { class: 'hint' }, '只会使用食材库里的食材；用到食材库没有的食材时会标为“未匹配”，需要你处理后才能通过。')),
    h('div', { class: 'panel' },
      h('h3', {}, '从视频导入菜谱'),
      h('div', { class: 'row' }, videoUrl, h('button', { onclick: () => importVideo(videoUrl.value) }, '导入')),
      h('p', { class: 'hint' }, '读取视频的标题、简介和字幕（不下载视频），由 Claude 提取菜谱。没有字幕的视频只能根据简介提取；目前不支持语音识别。')),
    pendingBox,
    rejectedBox);
}

async function refresh() {
  try {
    const [pending, ingredientList] = await Promise.all([get('/api/pending'), get('/api/ingredients')]);
    ingredients = ingredientList;
    decisions = Object.fromEntries(pending.pending.map((d) => [d.dish_id, decisions[d.dish_id] || { action: '', edited: null }]));
    render(pending);
  } catch (err) {
    showError(messages, err);
  }
}

function render({ pending, rejected }) {
  fill(pendingBox,
    h('h3', {}, `待审候选（${pending.length}）`),
    pending.length ? null : h('p', { class: 'hint' }, '没有待审的候选菜。'),
    pending.map((d) => card(d)),
    pending.length ? h('div', { class: 'row' },
      h('button', { onclick: () => setAll('approve') }, '全部标为通过'),
      h('button', { onclick: () => setAll('reject') }, '全部标为拒绝'),
      h('span', { class: 'spacer' }),
      h('button', { class: 'primary', onclick: submit }, '提交审核决定')) : null);
  fill(rejectedBox, rejected.length
    ? h('details', { class: 'panel' }, h('summary', {}, `已拒绝（${rejected.length}）`),
      rejected.map((d) => h('div', {}, badge('rejected'), ` ${d.dish_id} ${d.name_zh}`)))
    : null);
}

function card(original) {
  const decision = decisions[original.dish_id];
  const d = decision.edited ? { ...original, ...decision.edited } : original;
  const unmatched = d.ingredients.some((l) => l.unmatched_name && !l.ingredient_id);
  const radio = (value, text) => h('label', {},
    h('input', {
      type: 'radio', name: `decision_${d.dish_id}`, value, checked: decision.action === value,
      onchange: () => { decision.action = value; },
    }), text);
  return h('div', { class: 'card' },
    h('div', { class: 'row' },
      h('strong', {}, d.dish_id), badge('pending'),
      h('span', { class: 'hint' }, label('source', d.source)),
      decision.edited ? h('span', { class: 'badge' }, '已修改，未提交') : null,
      h('span', { class: 'spacer' }),
      radio('approve', '通过'), radio('reject', '拒绝'), radio('', '暂不处理'),
      h('button', { class: 'small', onclick: () => edit(original) }, '编辑')),
    unmatched ? h('div', { class: 'message warning' }, '有食材不在食材库中：请编辑并选择对应食材，或先到“食材库”添加该食材。') : null,
    dishDetail(d, ingredients));
}

function setAll(action) {
  Object.values(decisions).forEach((dec) => { dec.action = action; });
  refresh();
}

async function edit(original) {
  const decision = decisions[original.dish_id];
  const edited = await editDish(decision.edited || original, ingredients, `编辑候选：${original.name_zh}`);
  if (!edited) return;
  decision.edited = edited;
  refresh();
}

async function submit() {
  fill(messages);
  const list = Object.entries(decisions)
    .filter(([, dec]) => dec.action || dec.edited)
    .map(([dishId, dec]) => ({ dish_id: dishId, action: dec.action || 'edit', edited: dec.edited }));
  if (!list.length) {
    showMessage(messages, 'warning', '还没有做任何决定。');
    return;
  }
  try {
    await post('/api/review', { decisions: list });
    decisions = {};
    toast(`已提交 ${list.length} 项审核决定`);
  } catch (err) {
    showError(messages, err);
  }
  await refresh();
}

async function generate(dishType, count, reason) {
  fill(messages);
  try {
    const result = await post('/api/candidates/generate', {
      requests: [{ dish_type: dishType || null, count, reason: reason || '扩充菜品库' }],
    }, '正在用 Claude 生成候选菜（可能需要一两分钟）…');
    showMessage(messages, 'info', `生成了 ${result.added.length} 道候选菜。`,
      result.rejected.map(([name, why]) => `未通过校验：${name}（${why}）`));
  } catch (err) {
    showError(messages, err);
  }
  await refresh();
}

const TEXT_SOURCES = { subtitles: '上传者字幕', auto_captions: '自动生成字幕', description: '仅视频简介' };

async function importVideo(url) {
  fill(messages);
  if (!url.trim()) return;
  try {
    const result = await post('/api/videos/import', { url }, '正在读取视频字幕并提取菜谱…');
    const unmatched = result.dish.ingredients.filter((l) => l.unmatched_name && !l.ingredient_id).length;
    showMessage(messages, 'info', `已从《${result.title}》导入候选菜「${result.dish.name_zh}」（依据：${TEXT_SOURCES[result.text_source]}）。`,
      [unmatched ? `${unmatched} 种食材不在食材库中，需要处理后才能通过` : '所有食材都已匹配到食材库',
        ...(result.truncated ? ['视频文字过长，只使用了前一部分'] : [])]);
  } catch (err) {
    showError(messages, err);
  }
  await refresh();
}

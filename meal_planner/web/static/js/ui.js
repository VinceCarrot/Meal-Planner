// DOM helpers and Chinese labels. All text is inserted as text, never as HTML,
// because names, notes and recipes may come from AI output.

export function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key === 'value') node.value = value;
    else if (key === 'checked' || key === 'selected' || key === 'disabled' || key === 'multiple') node[key] = true;
    else node.setAttribute(key, value === true ? '' : value);
  }
  append(node, children);
  return node;
}

function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : String(child));
  }
}

export function fill(node, ...children) {
  node.replaceChildren();
  append(node, children);
  return node;
}

export const LABELS = {
  status: {
    feasible: '可行', feasible_with_unresolved: '可行（有未确认项）', best_effort: '尽力方案（有硬约束未满足）',
    infeasible: '不可行', no_solution_found: '未找到方案', blocked: '需先处理约束',
    passed: '通过', failed: '未满足', not_evaluable: '无法评估', approximated: '近似', conflict: '冲突',
    overridden: '本次被替代', unparsed: '未解析', executable: '可执行', needs_clarification: '需澄清',
    unsupported: '不支持', pending: '待审', approved: '已通过', rejected: '已拒绝',
  },
  strictness: { hard: '硬约束', soft: '软约束' },
  dish_type: { vegetarian: '素菜', mixed: '荤素搭配', meat: '大荤', soup: '汤' },
  // Key order is the display order of ingredient categories.
  category: {
    meat: '畜肉', poultry: '禽肉', seafood: '水产', egg: '蛋', soy: '豆制品', leafy_green: '绿叶菜', vegetable: '蔬菜', aromatic: '调味菜',
    mushroom: '菌菇', grain: '主食/谷物', seasoning: '调料', other: '其他',
  },
  cooking_method: {
    stir_fry: '炒', steam: '蒸', braise: '红烧/焖', stew: '炖/煲', boil: '煮/汆', deep_fry: '炸',
    pan_fry: '煎', roast: '烤', cold_mix: '凉拌', other: '其他',
  },
  flavour: {
    light: '清淡', salty_savory: '咸鲜', soy_sauce: '酱香', sweet_sour: '酸甜', sour: '酸', sweet: '甜',
    spicy: '辣', numbing_spicy: '麻辣', garlicky: '蒜香', fish_fragrant: '鱼香', other: '其他',
  },
  task: { menu_generation: '生成菜单', menu_adjustment: '调整菜单' },
  source: { manual: '手动录入', ai_generated: 'AI 生成', video_imported: '视频导入', persistent: '长期', task: '本次' },
  llm_task: { constraint_parsing: '约束解析', dish_generation: '候选菜生成', video_extraction: '视频菜谱提取', translation: '翻译', ingredient_analysis: '食材分析', dish_analysis: '菜品分析' },
  weekday: ['周一', '周二', '周三', '周四', '周五', '周六', '周日'],
};

export function label(group, value) {
  if (value === null || value === undefined) return '';
  return (LABELS[group] && LABELS[group][value]) || value;
}

// Ingredients ordered by category (LABELS.category order), then by Chinese name.
export function sortIngredients(list) {
  const rank = Object.fromEntries(Object.keys(LABELS.category).map((c, n) => [c, n]));
  const r = (i) => rank[i.category] ?? Infinity;
  return [...list].sort((a, b) => r(a) - r(b) || a.name_zh.localeCompare(b.name_zh, 'zh'));
}

export function badge(status) {
  return h('span', { class: `badge badge-${status}` }, label('status', status));
}

export function dishTypeTag(type) {
  return type ? h('span', { class: `tag tag-${type}` }, label('dish_type', type)) : null;
}

export function weekday(isoDate) {
  const d = new Date(`${isoDate}T00:00:00`);
  return LABELS.weekday[(d.getDay() + 6) % 7];
}

// Human-readable summary of a constraint's structured interpretation.
const SIMILARITY_FEATURE = {
  overall: '整体相似度', main_ingredients: '主料相似度', ingredients: '食材相似度',
  cooking_method: '做法相同', flavours: '口味相似度', cuisine: '菜系相同',
};

export function describeExecution(e) {
  if (!e) return '';
  const range = (min, max) => (min != null && max != null ? (min === max ? `${min}` : `${min}–${max}`) : min != null ? `至少 ${min}` : `至多 ${max}`);
  const when = (w) => (w && w.length ? `每${w.map((d) => LABELS.weekday[d - 1]).join('、')}` : '每餐');
  const counted = (r) => {
    switch (r.type) {
      case 'dish_count': return `${range(r.min, r.max)} 道菜`;
      case 'dish_type_count': return `${label('dish_type', r.dish_type)} ${range(r.min, r.max)} 道`;
      case 'matching_dish_count': {
        const what = [...(r.contains_categories || []).map((c) => label('category', c)), ...(r.contains_ingredient_ids || [])].join('、');
        const among = r.dish_types && r.dish_types.length ? `（只算${r.dish_types.map((t) => label('dish_type', t)).join('、')}）` : '';
        if (!what) return `菜 ${range(r.min, r.max)} 道${among}`;
        return `${r.as_main_ingredient ? '以' : '用到'}${what}${r.as_main_ingredient ? '为主料' : ''}的菜 ${range(r.min, r.max)} 道${among}`;
      }
      default: return r.type;
    }
  };
  switch (e.type) {
    case 'dish_count':
    case 'dish_type_count':
    case 'matching_dish_count':
      return `${when(e.weekdays)} ${counted(e)}`;
    case 'any_of': return `${when(e.weekdays)}满足其一：${e.alternatives.map(counted).join('；或 ')}`;
    case 'ingredient_exclusion':
      return `不用：${[...(e.categories || []).map((c) => label('category', c)), ...(e.ingredient_ids || [])].join('、')}`;
    case 'no_shared_ingredients': {
      const only = e.only_categories && e.only_categories.length ? `，只看${e.only_categories.map((c) => label('category', c)).join('、')}` : '';
      const ignored = e.ignore_categories && e.ignore_categories.length ? `（不算${e.ignore_categories.map((c) => label('category', c)).join('、')}${only}）` : only ? `（${only.slice(1)}）` : '';
      return `同一顿饭里的菜不用同一种食材${ignored}`;
    }
    case 'exact_repeat_window': return `${e.weeks} 周内同一道菜不重复`;
    case 'dish_similarity': {
      const days = e.window_days ?? e.window_weeks * 7;
      const scope = days === 1 ? '同一顿饭里' : days === 2 && !e.same_dinner ? '相邻两天' : `${e.same_dinner ? '同一顿及' : ''}${days} 天内`;
      const skip = e.skip_dish_types && e.skip_dish_types.length ? `（不比较${e.skip_dish_types.map((t) => label('dish_type', t)).join('、')}）` : '';
      return `${scope}菜品${SIMILARITY_FEATURE[e.feature || 'overall']}不超过 ${e.max_similarity ?? '默认阈值'}${skip}`;
    }
    case 'meal_similarity':
      return `${e.window_weeks} 周内整餐相似度不超过 ${e.max_similarity ?? '默认阈值'}`;
    default: return e.type;
  }
}

export function showMessage(container, kind, text, issues = []) {
  const box = h('div', { class: `message ${kind}` }, text, issues.length ? h('ul', {}, issues.map((i) => h('li', {}, i))) : null);
  container.append(box);
  return box;
}

export function showError(container, err) {
  return showMessage(container, 'error', err.message || String(err), err.issues || []);
}

let toastTimer;
export function toast(text) {
  const box = document.getElementById('toast');
  box.textContent = text;
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.hidden = true; }, 3000);
}

// Show content in the modal dialog; returns a function that closes it.
export function openModal(...children) {
  const modal = document.getElementById('modal');
  fill(document.getElementById('modal_box'), children);
  modal.hidden = false;
  return () => { modal.hidden = true; fill(document.getElementById('modal_box')); };
}

export function nextMonday(from = new Date()) {
  const d = new Date(from.getFullYear(), from.getMonth(), from.getDate());
  d.setDate(d.getDate() + ((8 - d.getDay()) % 7 || 7));
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

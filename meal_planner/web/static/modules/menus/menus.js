// Saved menus and their versions.

import { get } from '../../js/api.js';
import { h, fill, badge, describeExecution, label, showError } from '../../js/ui.js';
import { statusBanner, menuGrid, reportTable } from '../../js/menu_view.js';

let root;
let listBox;
let detailBox;

export async function showMenus(menuId) {
  if (!root) {
    root = document.getElementById('menus_root');
    listBox = h('div', { class: 'panel' });
    detailBox = h('div');
    fill(root, listBox, detailBox);
  }
  try {
    renderList(await get('/api/menus'));
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

export async function openMenu(menuId, version) {
  try {
    const menu = await get(`/api/menus/${menuId}${version ? `?version=${version}` : ''}`);
    renderMenu(menu);
  } catch (err) {
    fill(detailBox);
    showError(detailBox, err);
  }
}

function renderMenu(menu) {
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
      h('p', {}, `就餐者：${menu.diners.map((d) => `${d.description} × ${d.count}`).join('，')}`),
      report ? statusBanner(report.status) : null,
      menuGrid(menu.dinners)),
    h('div', { class: 'panel' }, h('h3', {}, '保存时的约束检查结果'), reportTable(report)),
    h('details', { class: 'panel' },
      h('summary', {}, `本版本使用的约束（${menu.constraint_snapshot.length} 条）`),
      h('table', {}, menu.constraint_snapshot.map((c) => h('tr', {},
        h('td', {}, c.constraint_id), h('td', {}, label('source', c.source)), h('td', {}, c.description),
        h('td', {}, label('strictness', c.strictness)), h('td', {}, describeExecution(c.execution)))))));
}

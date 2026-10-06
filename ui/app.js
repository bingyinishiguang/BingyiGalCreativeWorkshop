const $ = id => document.getElementById(id);

//装饰层不接收鼠标事件，避免拦截图片选择。
//仍然显式写 data-theme，因为整套样式是「浅色默认 + [data-theme="dark"] 覆盖」结构。
document.documentElement.setAttribute('data-theme', 'dark');

let brandData = null;
let catalog = {};
const mode = 'normal';
let previewUrl = '';
let previewSerial = 0;
let previewController = null;
let zoom = 'fit';
let customQueue = [];
let customJobId = sessionStorage.getItem('bingyiBatchJob') || '';
let customRunning = Boolean(customJobId);
let batchObserver = null;
let batchInspect = null;
let batchView = 'face';
let batchBackground = 'light';
let batchImageSerial = 0;
let faceObserver = null;
let activePage = 'workbench';
let libraryItems = [];
let librarySelected = null;
let librarySerial = 0;
let librarySearchTimer = null;
let libraryTrash = false;
let libraryPendingAction = null;
let appSettings = null;

//冰晶自绘下拉菜单
const iceSelectRegistry = new WeakMap();
let openIceSelect = null;

const ICE_SELECT_META = {
  game: { icon: '▱', label: '作品' },
  character: { icon: '♙', label: '角色' },
  body: { icon: '◇', label: '身体、服装与姿势' },
  face: { icon: '✦', label: '表情' },
  'library-game': { icon: '▱', label: '图库作品' },
  'library-character': { icon: '♙', label: '图库角色' },
  'library-tag': { icon: '⌁', label: '图库标签' },
};

function closeIceSelect(controller, { restoreFocus = false } = {}) {
  if (!controller || !controller.open) return;
  controller.open = false;
  controller.root.classList.remove('is-open', 'drop-up');
  controller.root.closest('.field')?.classList.remove('ice-select-field-open');
  controller.menu.hidden = true;
  controller.button.setAttribute('aria-expanded', 'false');
  controller.button.removeAttribute('aria-activedescendant');
  if (openIceSelect === controller) openIceSelect = null;
  if (restoreFocus) controller.button.focus();
}

function activeIceOption(controller, index, { scroll = true } = {}) {
  const options = Array.from(controller.menu.querySelectorAll('.ice-select-option:not(:disabled)'));
  if (!options.length) return;
  controller.activeIndex = Math.max(0, Math.min(options.length - 1, index));
  options.forEach((option, optionIndex) => option.classList.toggle('is-active', optionIndex === controller.activeIndex));
  const active = options[controller.activeIndex];
  controller.button.setAttribute('aria-activedescendant', active.id);
  if (scroll) active.scrollIntoView({ block: 'nearest' });
}

function chooseIceOption(controller, value) {
  if (controller.select.disabled || controller.select.value === value) {
    closeIceSelect(controller, { restoreFocus: true });
    return;
  }
  controller.select.value = value;
  controller.refresh();
  closeIceSelect(controller, { restoreFocus: true });
  controller.select.dispatchEvent(new Event('change', { bubbles: true }));
}

function openIceSelectMenu(controller) {
  if (controller.select.disabled) return;
  if (openIceSelect && openIceSelect !== controller) closeIceSelect(openIceSelect);
  controller.refresh();
  controller.open = true;
  openIceSelect = controller;
  controller.root.classList.add('is-open');
  controller.root.closest('.field')?.classList.add('ice-select-field-open');
  controller.menu.hidden = false;
  controller.button.setAttribute('aria-expanded', 'true');

  const enabled = Array.from(controller.menu.querySelectorAll('.ice-select-option:not(:disabled)'));
  const selectedIndex = Math.max(0, enabled.findIndex(option => option.dataset.value === controller.select.value));
  activeIceOption(controller, selectedIndex, { scroll: false });

  const rect = controller.root.getBoundingClientRect();
  const expectedHeight = Math.min(286, Math.max(52, enabled.length * 40 + 14));
  const spaceBelow = window.innerHeight - rect.bottom - 14;
  const spaceAbove = rect.top - 14;
  controller.root.classList.toggle('drop-up', spaceBelow < expectedHeight && spaceAbove > spaceBelow);
  requestAnimationFrame(() => activeIceOption(controller, controller.activeIndex));
}

function enhanceIceSelect(select) {
  if (!select || iceSelectRegistry.has(select)) return;
  const meta = ICE_SELECT_META[select.id] || { icon: '◇', label: '选择' };
  const root = document.createElement('div');
  root.className = 'ice-select';
  root.dataset.selectId = select.id;

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'ice-select-trigger';
  button.setAttribute('role', 'combobox');
  button.setAttribute('aria-haspopup', 'listbox');
  button.setAttribute('aria-expanded', 'false');
  button.setAttribute('aria-label', meta.label);

  const icon = document.createElement('span');
  icon.className = 'ice-select-icon';
  icon.textContent = meta.icon;
  icon.setAttribute('aria-hidden', 'true');
  const value = document.createElement('span');
  value.className = 'ice-select-value';
  const arrow = document.createElement('span');
  arrow.className = 'ice-select-arrow';
  arrow.setAttribute('aria-hidden', 'true');
  button.append(icon, value, arrow);

  const menu = document.createElement('div');
  menu.className = 'ice-select-menu';
  menu.id = `ice-select-menu-${select.id}`;
  menu.setAttribute('role', 'listbox');
  menu.setAttribute('aria-label', meta.label);
  menu.hidden = true;
  button.setAttribute('aria-controls', menu.id);

  select.parentNode.insertBefore(root, select);
  root.append(select, button, menu);
  select.classList.add('ice-select-native');
  select.tabIndex = -1;
  select.setAttribute('aria-hidden', 'true');

  const controller = {
    select, root, button, menu, value,
    open: false,
    activeIndex: 0,
    typeahead: '',
    typeaheadTimer: 0,
    refresh: null,
  };

  controller.refresh = () => {
    const selected = select.selectedOptions[0] || select.options[0];
    value.textContent = selected?.textContent || '暂无可选项';
    value.title = value.textContent;
    button.disabled = select.disabled;
    root.classList.toggle('is-disabled', select.disabled);
    menu.replaceChildren();
    Array.from(select.options).forEach((option, optionIndex) => {
      const item = document.createElement('button');
      item.type = 'button';
      item.id = `${menu.id}-option-${optionIndex}`;
      item.className = 'ice-select-option';
      item.dataset.value = option.value;
      item.disabled = option.disabled;
      item.setAttribute('role', 'option');
      item.setAttribute('aria-selected', option.value === select.value ? 'true' : 'false');
      item.classList.toggle('is-selected', option.value === select.value);
      const mark = document.createElement('span');
      mark.className = 'ice-select-option-mark';
      mark.textContent = '✦';
      mark.setAttribute('aria-hidden', 'true');
      const text = document.createElement('span');
      text.textContent = option.textContent;
      item.append(mark, text);
      item.onclick = () => chooseIceOption(controller, option.value);
      menu.append(item);
    });
  };

  iceSelectRegistry.set(select, controller);
  controller.refresh();

  button.onclick = () => controller.open ? closeIceSelect(controller) : openIceSelectMenu(controller);
  button.onkeydown = event => {
    const enabled = Array.from(menu.querySelectorAll('.ice-select-option:not(:disabled)'));
    if (!controller.open && ['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', ' '].includes(event.key)) {
      event.preventDefault();
      openIceSelectMenu(controller);
      if (event.key === 'End') activeIceOption(controller, enabled.length - 1);
      if (event.key === 'ArrowUp') activeIceOption(controller, Math.max(0, enabled.length - 1));
      return;
    }
    if (!controller.open) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      closeIceSelect(controller, { restoreFocus: true });
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      activeIceOption(controller, controller.activeIndex + 1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      activeIceOption(controller, controller.activeIndex - 1);
    } else if (event.key === 'Home') {
      event.preventDefault();
      activeIceOption(controller, 0);
    } else if (event.key === 'End') {
      event.preventDefault();
      activeIceOption(controller, enabled.length - 1);
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      const active = enabled[controller.activeIndex];
      if (active) chooseIceOption(controller, active.dataset.value);
    } else if (event.key === 'Tab') {
      closeIceSelect(controller);
    } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      clearTimeout(controller.typeaheadTimer);
      controller.typeahead += event.key.toLocaleLowerCase();
      controller.typeaheadTimer = setTimeout(() => { controller.typeahead = ''; }, 650);
      const index = enabled.findIndex(option => option.textContent.trim().toLocaleLowerCase().startsWith(controller.typeahead));
      if (index >= 0) activeIceOption(controller, index);
    }
  };

  new MutationObserver(controller.refresh).observe(select, { childList: true, subtree: true, attributes: true });
}

function syncIceSelect(select) {
  iceSelectRegistry.get(select)?.refresh();
}

function initIceSelects() {
  Object.keys(ICE_SELECT_META).forEach(id => enhanceIceSelect($(id)));
  document.addEventListener('pointerdown', event => {
    if (openIceSelect && !openIceSelect.root.contains(event.target)) closeIceSelect(openIceSelect);
  });
  window.addEventListener('resize', () => closeIceSelect(openIceSelect));
  document.querySelectorAll('dialog').forEach(dialog => dialog.addEventListener('close', () => closeIceSelect(openIceSelect)));
}

function fillSelect(select, values, emptyText) {
  select.replaceChildren();
  if (!values.length) {
    const option = new Option(emptyText, '');
    select.add(option);
    select.disabled = true;
    syncIceSelect(select);
    return;
  }
  select.disabled = false;
  for (const value of values) select.add(new Option(value, value));
  syncIceSelect(select);
}

function currentGame() { return catalog[$('game').value]; }
function currentCharacter() { return currentGame()?.characters[$('character').value]; }
function currentCategory() { return 'normal'; }
function bodyNames(character) {
  return Object.keys(character.bodies).filter(body => character.bodyCategories[body] === currentCategory());
}

//HTML 转义：把来自后端/文件名/用户输入的文本安全地放进 innerHTML。
function escapeHtml(value) {
  return String(value === null || value === undefined ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function setStatus(message) { $('status').textContent = message; }

//延迟显示空态；新预览到位时取消计时，避免切换表情时闪烁。
const EMPTY_STATE_DELAY_MS = 400;
let emptyStateTimer = 0;

function hideEmptyState() {
  if (emptyStateTimer) {
    clearTimeout(emptyStateTimer);
    emptyStateTimer = 0;
  }
  $('empty-state').hidden = true;
}

function scheduleEmptyState() {
  if (emptyStateTimer) clearTimeout(emptyStateTimer);
  emptyStateTimer = setTimeout(() => {
    emptyStateTimer = 0;
    //期间如果已经有预览了，就不要把空态压上去
    if (!$('preview').hidden) return;
    $('empty-state').hidden = false;
  }, EMPTY_STATE_DELAY_MS);
}

function clearPreview() {
  previewSerial++;
  if (previewController) previewController.abort();
  previewController = null;
  zoom = 'fit';
  explicitUserZoom = false;
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = '';
  $('preview').removeAttribute('src');
  $('preview').hidden = true;
  scheduleEmptyState();
  $('preview-size').textContent = '';
  $('download').disabled = true;
  $('save-library').disabled = true;
  $('export-status').textContent = '';
  $('save-library-status').textContent = '';
  $('canvas-viewport').classList.remove('can-pan');
  applyZoom();
}

function refreshGames() {
  clearPreview();
  fillSelect($('game'), Object.keys(catalog).filter(game =>
    Object.values(catalog[game].characters).some(character => bodyNames(character).length)
  ), '当前类别没有作品');
  changeGame();
}

function changeGame() {
  const characters = currentGame()?.characters || {};
  fillSelect($('character'), Object.keys(characters).filter(name => bodyNames(characters[name]).length), '没有可用角色');
  changeCharacter();
}

function changeCharacter() {
  const character = currentCharacter();
  fillSelect($('body'), character ? bodyNames(character) : [], '没有可用组合');
  changeBody();
}

function changeBody() {
  const character = currentCharacter();
  fillSelect($('face'), character?.bodies[$('body').value] || [], '没有可用表情');
  syncFaceControls();
  showPreview();
}

function faceOptions() {
  return Array.from($('face').options).map(option => option.value).filter(Boolean);
}

function syncFaceControls() {
  const options = faceOptions();
  const index = options.indexOf($('face').value);
  $('face-prev').disabled = index <= 0;
  $('face-next').disabled = index < 0 || index >= options.length - 1;
  $('face-browse').disabled = options.length === 0;
  $('face-count').textContent = options.length ? `${options.length} 个可选` : '';
}

function stepFace(direction) {
  const options = faceOptions();
  const next = options.indexOf($('face').value) + direction;
  if (next < 0 || next >= options.length) return;
  $('face').value = options[next];
  syncIceSelect($('face'));
  syncFaceControls();
  showPreview();
}

function filterFaceGrid() {
  const query = $('face-search').value.trim().toLocaleLowerCase();
  let visible = 0;
  for (const button of $('face-grid').querySelectorAll('button')) {
    button.hidden = !button.textContent.toLocaleLowerCase().includes(query);
    if (!button.hidden) visible++;
  }
  $('face-empty').hidden = visible !== 0;
  $('face-result-count').textContent = `${visible} 个结果`;
  $('face-grid').scrollTop = 0;
}

function openFacePicker() {
  const options = faceOptions();
  if (!options.length) return;
  const grid = $('face-grid');
  if (faceObserver) faceObserver.disconnect();
  grid.replaceChildren();
  const observer = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const button = entry.target;
      button.querySelector('img').src = button.dataset.src;
      observer.unobserve(button);
    }
  }, { root: grid, rootMargin: '120px' });
  faceObserver = observer;
  for (const name of options) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'face-tile';
    const imageWrap = document.createElement('span');
    imageWrap.className = 'face-tile-image';
    const image = document.createElement('img');
    image.alt = '';
    image.hidden = true;
    const loading = document.createElement('span');
    loading.textContent = '加载中…';
    image.onload = () => { image.hidden = false; loading.hidden = true; };
    image.onerror = () => { loading.textContent = '预览失败'; };
    imageWrap.append(image, loading);
    const label = document.createElement('span');
    label.className = 'face-tile-name';
    label.textContent = name;
    button.append(imageWrap, label);
    button.title = name;
    button.setAttribute('aria-label', `选择表情 ${name}`);
    button.classList.toggle('active', name === $('face').value);
    button.setAttribute('aria-pressed', name === $('face').value);
    const query = new URLSearchParams({ game: $('game').value, character: $('character').value, body: $('body').value, face: name });
    if (mode === 'special') query.set('special', '1');
    button.dataset.src = '/api/expression-preview?' + query;
    button.onclick = () => {
      $('face').value = name;
      syncIceSelect($('face'));
      $('face-dialog').close();
      syncFaceControls();
      showPreview();
    };
    grid.append(button);
    observer.observe(button);
  }
  $('face-search').value = '';
  filterFaceGrid();
  $('face-dialog').showModal();
  $('face-search').focus();
}

function params() {
  const query = new URLSearchParams({
    game: $('game').value,
    character: $('character').value,
    body: $('body').value,
    face: $('face').value,
  });
  if (mode === 'special') query.set('special', '1');
  return query;
}

function updateSelectionSummary() {
  const values = [$('character').value, $('body').value, $('face').value].filter(Boolean);
  $('selection-summary').textContent = values.length ? values.join(' / ') : '当前类别没有可用组合';
}

async function showPreview() {
  clearPreview();
  //换组合 = 回到「适应窗口」：不让上一次的 100%/放大 状态把新立绘顶出画布
  explicitUserZoom = false;
  updateSelectionSummary();
  const serial = previewSerial;
  if (!$('game').value || !$('character').value || !$('body').value || !$('face').value) {
    setStatus('当前类别没有可用组合');
    return;
  }
  setStatus('正在合成预览…');
  const controller = new AbortController();
  previewController = controller;
  try {
    const response = await fetch('/api/preview?' + params(), { signal: controller.signal });
    if (serial !== previewSerial) return;
    if (!response.ok) throw new Error(await response.text());
    const blob = await response.blob();
    if (serial !== previewSerial) return;
    previewUrl = URL.createObjectURL(blob);
    const image = $('preview');
    image.onload = () => {
      if (serial !== previewSerial) return;
      image.hidden = false;
      //新图到了：取消"延迟显示空态"，空态从头到尾不出现（避免空态闪现）
      hideEmptyState();
      $('download').disabled = false;
      $('save-library').disabled = false;
      $('preview-size').textContent = `${image.naturalWidth} × ${image.naturalHeight} px`;
      $('export-status').textContent = '';
      applyZoom();
      setStatus('预览已就绪');
    };
    image.onerror = () => { if (serial === previewSerial) setStatus('预览图无法显示，请重新选择组合'); };
    image.src = previewUrl;
  } catch (error) {
    if (serial === previewSerial && error.name !== 'AbortError') setStatus('预览失败：' + error.message);
  } finally {
    if (previewController === controller) previewController = null;
  }
}

function fittedZoom() {
  const image = $('preview');
  const viewport = $('canvas-viewport');
  if (!image.naturalWidth || !image.naturalHeight) return 1;
  return Math.min(1, (viewport.clientWidth - 50) / image.naturalWidth, (viewport.clientHeight - 50) / image.naturalHeight);
}

//新预览默认适应窗口，手动缩放只对当前预览有效。
let explicitUserZoom = false;

function applyZoom() {
  const image = $('preview');
  const inner = $('canvas-inner');
  const viewport = $('canvas-viewport');
  const fitted = zoom === 'fit' || !explicitUserZoom;
  const scale = fitted ? fittedZoom() : zoom;
  inner.classList.toggle('fit', fitted);
  image.style.width = image.naturalWidth ? `${Math.max(1, Math.round(image.naturalWidth * scale))}px` : '';
  image.style.height = image.naturalHeight ? `${Math.max(1, Math.round(image.naturalHeight * scale))}px` : '';
  $('zoom-fit').classList.toggle('active', fitted);
  $('zoom-actual').classList.toggle('active', zoom === 1 && explicitUserZoom);
  $('zoom-fit').setAttribute('aria-pressed', fitted);
  $('zoom-actual').setAttribute('aria-pressed', zoom === 1 && explicitUserZoom);
  $('zoom-level').textContent = image.naturalWidth ? `${Math.round(scale * 100)}%` : '—';
  viewport.classList.toggle('can-pan', !fitted && !image.hidden);
}

function setZoom(value) {
  explicitUserZoom = true;
  zoom = value === 'fit' ? 'fit' : Math.max(.1, Math.min(4, value));
  if (zoom === 'fit') explicitUserZoom = false;
  applyZoom();
}

function updateMode() {
  $('library-mode-note').textContent = '当前只显示普通立绘';
}

function switchPage(page) {
  //切换前校验目标页面，避免所有页面同时隐藏。
  if (!['workbench', 'library', 'settings', 'tools', 'backgrounds', 'audio', 'roughcut', 'localtts'].includes(page)) page = 'workbench';
  if (page === activePage) return;
  activePage = page;
  $('workbench-page').hidden = page !== 'workbench';
  $('library-page').hidden = page !== 'library';
  $('settings-page').hidden = page !== 'settings';
  const tools = $('tools-page');
  if (tools) tools.hidden = page !== 'tools';
  $('backgrounds-page').hidden = page !== 'backgrounds';
  $('audio-page').hidden = page !== 'audio';
  $('roughcut-page').hidden = page !== 'roughcut';
  $('localtts-page').hidden = page !== 'localtts';
  document.querySelector('.app-shell').classList.toggle('library-active', page === 'library');
  $('settings-button').classList.toggle('active', page === 'settings');
  if (page === 'settings') $('settings-button').setAttribute('aria-current', 'page');
  else $('settings-button').removeAttribute('aria-current');
  for (const [name, id] of [['workbench', 'nav-workbench'], ['library', 'nav-library'],
                            ['backgrounds', 'nav-backgrounds'], ['audio','nav-audio'], ['tools', 'nav-tools']]) {
    const button = $(id);
    if (!button) continue;
    button.classList.toggle('active', page === name);
    if (page === name) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
  if (page === 'library') resetLibraryView();
  else if (page === 'settings') {
    //进设置页永远从分组列表开始，不要停在上次打开的子页面。
    closeSettingsPanel();
    $('settings-page').scrollTop = 0;
    loadSettings();
  }
  else if (!$('preview').hidden) applyZoom();
  window.scrollTo(0, 0);
  window.dispatchEvent(new CustomEvent('workshop-page', {detail: page}));
}

function singleSaveMode() {
  return document.querySelector('input[name="single-save-mode"]:checked').value;
}

function syncSettingsFields() {
  const folderMode = singleSaveMode() === 'folder';
  $('single-folder-field').hidden = !folderMode;
  $('open-single-path').hidden = !folderMode;
  $('open-batch-path').disabled = Boolean(appSettings && $('batch-path').value.trim() !== appSettings.batchPath);
  $('download').textContent = '导出立绘';
}

function renderSettings(data) {
  appSettings = data;
  document.querySelector(`input[name="single-save-mode"][value="${data.singleMode}"]`).checked = true;
  $('single-path').value = data.singlePath;
  $('single-path').placeholder = `留空使用默认位置：${data.defaultSinglePath || ''}`;
  $('batch-path').value = data.batchPath;
  $('drag-path').value = data.dragPath || '';
  $('drag-path').placeholder = `留空使用默认位置：${data.defaultDragPath || ''}`;
  $('drag-default-note').textContent = `当前生效：${data.effectiveDragPath || data.defaultDragPath || ''}`
    + '（默认永不自动清理）';
  $('open-drag-path').disabled = Boolean($('drag-path').value.trim() !== (data.dragPath || ''));
  $('batch-default-note').textContent = `留空使用默认位置：${data.defaultBatchPath}`;
  $('settings-status').textContent = '设置已就绪';
  syncSettingsFields();
  refreshSettingsRowValues();
}

async function loadSettings() {
  $('settings-status').textContent = '正在读取设置…';
  try {
    const response = await fetch('/api/settings');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '设置读取失败');
    renderSettings(data);
  } catch (error) {
    $('settings-status').textContent = '读取失败：' + error.message;
  }
}

async function autoSaveSettings() {
  //设置读取失败时禁止保存，避免用空表单覆盖已有路径。
  if (!appSettings) return;
  try {
    const response = await fetch('/api/settings', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ singleMode: singleSaveMode(), singlePath: $('single-path').value.trim(), batchPath: $('batch-path').value.trim(), dragPath: $('drag-path').value.trim() }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '保存失败');
    renderSettings(data);
    const moved = Number(data.movedDragFiles || 0);
    if (moved > 0) {
      $('drag-status').textContent = `已搬移 ${moved} 个文件到新拖出目录；剪映 / PR 里需要重新链接素材`;
      $('settings-status').textContent = '设置已保存，之后的导出会使用新路径';
    } else {
      $('settings-status').textContent = '设置已保存，之后的导出会使用新路径';
    }
  } catch (error) {
    $('settings-status').textContent = '保存失败：' + error.message;
  }
}

let autoSaveTimer = null;
function scheduleAutoSave() {
  $('settings-status').textContent = '正在保存…';
  clearTimeout(autoSaveTimer);
  autoSaveTimer = setTimeout(autoSaveSettings, 300);
}

async function cleanupDragFolder() {
  const label = $('drag-status');
  if (!window.confirm('清理拖出文件夹？\n\n删除后，已经拖进剪映 / PR 的工程会显示"媒体丢失"，需要重新拖一次。\n这个操作不会自动发生，只有你点确认才会删。')) return;
  label.textContent = '正在清理…';
  try {
    const response = await fetch('/api/settings/cleanup-drag', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '清理失败');
    label.textContent = data.removed > 0
      ? `已清理 ${data.removed} 个文件（${data.dir}）`
      : '拖出文件夹已经是空的';
  } catch (error) {
    label.textContent = '清理失败：' + error.message;
  }
}

//立绘库清理（未入库的孤儿文件）
let libraryOrphanCount = 0;

function formatBytes(bytes) {
  if (!bytes) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

function resetLibraryOrphanUI(statusText) {
  libraryOrphanCount = 0;
  $('library-orphan-status').textContent = statusText;
  $('library-orphan-list').replaceChildren();
  $('library-orphan-clean').hidden = true;
  $('library-orphan-cancel').hidden = true;
  $('library-orphan-scan').disabled = false;
}

async function scanLibraryOrphans() {
  const scanButton = $('library-orphan-scan');
  scanButton.disabled = true;
  $('library-orphan-status').textContent = '正在扫描…（只查看，不会删任何东西）';
  $('library-orphan-list').replaceChildren();
  $('library-orphan-clean').hidden = true;
  $('library-orphan-cancel').hidden = true;
  try {
    const response = await fetch('/api/library/orphans', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'scan' }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '扫描失败');
    libraryOrphanCount = data.total || 0;
    if (!libraryOrphanCount) {
      resetLibraryOrphanUI('没发现未入库的文件，立绘库是干净的。');
      return;
    }
    $('library-orphan-status').textContent =
      `发现 ${libraryOrphanCount} 个未入库文件，占用 ${formatBytes(data.bytes)}`
      + `（图片 ${data.images} 个、缩略图 ${data.thumbs} 个）。确认后才会删除。`;
    //预览前若干个名字，让用户能核对一眼
    const list = document.createElement('div');
    list.className = 'settings-description';
    for (const name of data.preview || []) {
      const line = document.createElement('div');
      line.textContent = name;
      list.append(line);
    }
    if (libraryOrphanCount > (data.preview || []).length) {
      const more = document.createElement('div');
      more.textContent = `…还有 ${libraryOrphanCount - data.preview.length} 个`;
      list.append(more);
    }
    $('library-orphan-list').replaceChildren(list);
    $('library-orphan-clean').hidden = false;
    $('library-orphan-clean').textContent = `确认清理这 ${libraryOrphanCount} 个`;
    $('library-orphan-cancel').hidden = false;
  } catch (error) {
    resetLibraryOrphanUI('扫描失败：' + error.message);
  } finally {
    scanButton.disabled = false;
  }
}

async function cleanLibraryOrphans() {
  if (!libraryOrphanCount) return;
  if (!window.confirm(
    `清理 ${libraryOrphanCount} 个未入库文件？\n\n`
    + '这些文件在立绘库里本来就不显示、也点不到，删掉不会影响你已保存的立绘。\n'
    + '只会删立绘库目录（images / thumbs）里的文件，别的目录一律不动。')) return;
  const cleanButton = $('library-orphan-clean');
  cleanButton.disabled = true;
  $('library-orphan-status').textContent = '正在清理…';
  try {
    const response = await fetch('/api/library/orphans', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'clean' }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '清理失败');
    //再扫一次核对结果（后端 clean 也是重新扫的，不信任前端列表）
    const again = await fetch('/api/library/orphans', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'scan' }),
    });
    const after = await again.json();
    resetLibraryOrphanUI(
      `已清理 ${data.removed} 个文件，释放 ${formatBytes(data.bytes)}。`
      + (after.total ? `还剩 ${after.total} 个（可能是刚写入不久的，稍后再扫一次）。` : '立绘库现在很干净。'));
  } catch (error) {
    $('library-orphan-status').textContent = '清理失败：' + error.message;
    cleanButton.disabled = false;
  }
}

async function openSettingsFolder(target) {
  $('settings-status').textContent = '正在打开文件夹…';
  try {
    const response = await fetch('/api/settings/open-folder', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '无法打开文件夹');
    $('settings-status').textContent = `已打开：${data.path}`;
  } catch (error) {
    $('settings-status').textContent = '打开失败：' + error.message;
  }
}

//三种路径设置的 DOM id 映射（单张/批量/拖出），避免到处写三目表达式。
const PATH_TARGETS = {
  single: { choose: 'choose-single-path', input: 'single-path' },
  batch: { choose: 'choose-batch-path', input: 'batch-path' },
  drag: { choose: 'choose-drag-path', input: 'drag-path' },
};

async function chooseSettingsFolder(target) {
  const targetIds = PATH_TARGETS[target] || PATH_TARGETS.batch;
  const button = $(targetIds.choose);
  button.disabled = true;
  $('settings-status').textContent = '请在弹出的窗口中选择文件夹…';
  try {
    const response = await fetch('/api/settings/choose-folder', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '选择文件夹失败');
    if (data.path) {
      $(targetIds.input).value = data.path;
      syncSettingsFields();
      scheduleAutoSave();
    } else $('settings-status').textContent = '已取消选择';
  } catch (error) {
    $('settings-status').textContent = '选择失败：' + error.message;
  } finally {
    button.disabled = false;
  }
}

function setLibrarySelect(select, values, label, previous = '') {
  select.replaceChildren(new Option(label, ''));
  for (const value of values) select.add(new Option(value, value));
  select.value = values.includes(previous) ? previous : '';
  syncIceSelect(select);
}

function refreshLibraryFilters() {
  const previousGame = $('library-game').value;
  const previousCharacter = $('library-character').value;
  const games = Object.keys(catalog).filter(game => Object.values(catalog[game].characters).some(character =>
    Object.values(character.bodyCategories).some(category => (category !== 'normal') === (mode === 'special'))
  ));
  setLibrarySelect($('library-game'), games, '全部作品', previousGame);
  const characters = $('library-game').value
    ? Object.keys(catalog[$('library-game').value].characters).filter(name =>
      Object.values(catalog[$('library-game').value].characters[name].bodyCategories).some(category =>
        (category !== 'normal') === (mode === 'special')))
    : [];
  setLibrarySelect($('library-character'), characters, '全部角色', previousCharacter);
}

function libraryImageUrl(id, thumb = false) {
  const query = new URLSearchParams({ id });
  if (mode === 'special') query.set('special', '1');
  if (libraryTrash) query.set('trash', '1');
  if (thumb) query.set('size', 'thumb');
  return '/api/library/image?' + query;
}

function clearLibraryDetail() {
  librarySelected = null;
  $('library-detail-preview').removeAttribute('src');
  $('library-detail-content').hidden = true;
  $('library-detail-empty').hidden = false;
  $('library-action-status').textContent = '';
}

function selectLibraryItem(item) {
  librarySelected = item;
  $('library-detail-empty').hidden = true;
  $('library-detail-content').hidden = false;
  $('library-detail-preview').hidden = item.missing;
  $('library-detail-missing').hidden = !item.missing;
  if (!item.missing) $('library-detail-preview').src = libraryImageUrl(item.id);
  else $('library-detail-preview').removeAttribute('src');
  $('library-detail-name').textContent = item.displayName || `${item.character} / ${item.face}`;
  $('library-detail-meta').textContent = `${item.game} · ${item.width} × ${item.height} px · ${item.savedAt.replace('T', ' ')}`;
  $('library-detail-pose').textContent = `${item.body} / ${item.face}${item.tags.length ? ' · ' + item.tags.join(' · ') : ''}`;
  $('library-edit-name').value = item.displayName;
  $('library-edit-note').value = item.note;
  $('library-edit-tags').value = item.tags.join(', ');
  $('library-edit-favorite').checked = item.favorite;
  $('library-edit-form').hidden = libraryTrash;
  $('library-active-actions').hidden = libraryTrash;
  $('library-trash-actions').hidden = !libraryTrash;
  $('library-reveal').disabled = item.missing;
  $('library-action-status').textContent = item.missing ? '索引仍在，但图片文件已丢失。再次保存同一立绘可自动修复。' : '';
  for (const tile of $('library-grid').querySelectorAll('.library-tile')) {
    tile.classList.toggle('active', tile.dataset.id === item.id);
  }
}

function appendLibraryItems(items) {
  const grid = $('library-grid');
  for (const item of items) {
    const tile = document.createElement('button');
    tile.type = 'button';
    tile.className = 'library-tile';
    tile.dataset.id = item.id;
    tile.title = `${item.game} / ${item.character} / ${item.body} / ${item.face}`;
    const visual = document.createElement('div');
    visual.className = 'library-tile-image';
    if (item.missing) {
      const missing = document.createElement('span');
      missing.className = 'library-missing-badge';
      missing.textContent = '文件丢失';
      visual.append(missing);
    } else {
      const image = document.createElement('img');
      image.src = libraryImageUrl(item.id, true);
      image.alt = '';
      image.loading = 'lazy';
      visual.append(image);
    }
    const name = document.createElement('strong');
    name.textContent = `${item.favorite ? '★ ' : ''}${item.displayName || item.character}`;
    const face = document.createElement('span');
    face.textContent = `${item.body} / ${item.face}`;
    tile.append(visual, name, face);
    tile.onclick = () => selectLibraryItem(item);
    grid.append(tile);
  }
}

async function loadLibrary(reset = false) {
  const serial = reset ? ++librarySerial : librarySerial;
  if (reset) {
    libraryItems = [];
    $('library-grid').replaceChildren();
    clearLibraryDetail();
  }
  $('library-count').textContent = '正在读取…';
  $('library-more').hidden = true;
  const query = new URLSearchParams({
    search: $('library-search').value.trim(),
    game: $('library-game').value,
    character: $('library-character').value,
    tag: $('library-tag').value,
    offset: String(libraryItems.length),
  });
  if (mode === 'special') query.set('special', '1');
  if ($('library-favorite').checked) query.set('favorite', '1');
  if (libraryTrash) query.set('trash', '1');
  try {
    const response = await fetch('/api/library?' + query);
    const data = await response.json();
    if (serial !== librarySerial) return;
    if (!response.ok) throw new Error(data.error || '读取立绘库失败');
    libraryItems.push(...data.items);
    appendLibraryItems(data.items);
    const previousTag = $('library-tag').value;
    setLibrarySelect($('library-tag'), data.tags || [], '全部标签', previousTag);
    //作品 / 角色下拉必须以立绘库自己的清单为准。
    setLibrarySelect($('library-game'), data.games || [], '全部作品', $('library-game').value);
    setLibrarySelect($('library-character'), data.characters || [], '全部角色', $('library-character').value);
    $('library-count').textContent = `${data.total} 张立绘`;
    $('library-empty').hidden = data.total !== 0;
    const filtered = $('library-search').value || $('library-game').value || $('library-character').value || $('library-tag').value || $('library-favorite').checked;
    $('library-empty').querySelector('strong').textContent = filtered ? '没有匹配的立绘' : (libraryTrash ? '回收站是空的' : '还没有保存的立绘');
    $('library-empty').querySelector('span').textContent = libraryTrash ? '移到回收站的立绘会显示在这里。' : '回到合成工作台，选择立绘后点击“保存到立绘库”。';
    $('library-more').hidden = libraryItems.length >= data.total;
    if (!librarySelected && libraryItems.length) selectLibraryItem(libraryItems[0]);
  } catch (error) {
    if (serial === librarySerial) $('library-count').textContent = '读取失败：' + error.message;
  }
}

//清掉立绘库的全部筛选条件（导入成功后调用：保证新导入的图一定看得见）。
function clearLibraryFilters() {
  $('library-search').value = '';
  $('library-game').value = '';
  $('library-character').value = '';
  $('library-tag').value = '';
  $('library-favorite').checked = false;
}

function resetLibraryView() {
  librarySerial++;
  libraryItems = [];
  $('library-grid').replaceChildren();
  clearLibraryDetail();
  $('library-more').hidden = true;
  refreshLibraryFilters();
  $('library-view-active').classList.toggle('active', !libraryTrash);
  $('library-view-trash').classList.toggle('active', libraryTrash);
  if (activePage === 'library') loadLibrary(true);
}

async function saveToLibrary() {
  const button = $('save-library');
  const label = $('save-library-status');
  button.disabled = true;
  label.textContent = '正在保存…';
  const savingMode = mode;
  try {
    const response = await fetch('/api/library/save', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ game: $('game').value, character: $('character').value,
        body: $('body').value, face: $('face').value, special: savingMode === 'special' }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '保存失败');
    if (mode === savingMode) {
      if (data.repaired) label.textContent = '已修复立绘库中丢失的图片文件';
      else if (data.duplicate) label.textContent = '这张立绘已经在立绘库中，没有重复保存';
      else label.textContent = '已保存到立绘库，可在“立绘库”中找到';
    }
  } catch (error) {
    if (mode === savingMode) label.textContent = '保存失败：' + error.message;
  } finally {
    button.disabled = $('preview').hidden;
  }
}

async function revealLibraryFile() {
  if (!librarySelected) return;
  $('library-reveal').disabled = true;
  $('library-action-status').textContent = '正在打开文件夹…';
  try {
    const response = await fetch('/api/library/reveal', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: librarySelected.id, special: mode === 'special' }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '无法打开文件夹');
    //打开文件夹的同时把这张图选中，方便自己复制到别处。
    $('library-action-status').textContent = data.selected
      ? `已打开并选中：${data.path}`
      : `已打开文件夹：${data.path}`;
  } catch (error) {
    $('library-action-status').textContent = '打开失败：' + error.message;
  } finally {
    $('library-reveal').disabled = Boolean(librarySelected?.missing);
  }
}

async function saveLibraryMetadata() {
  if (!librarySelected || libraryTrash) return;
  const button = $('library-save-edit');
  button.disabled = true;
  $('library-action-status').textContent = '正在保存资料…';
  try {
    const tags = $('library-edit-tags').value.split(/[,，]/).map(value => value.trim()).filter(Boolean);
    const response = await fetch('/api/library/update', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: librarySelected.id, special: mode === 'special',
        displayName: $('library-edit-name').value, note: $('library-edit-note').value,
        favorite: $('library-edit-favorite').checked, tags }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '保存资料失败');
    librarySelected = data;
    $('library-action-status').textContent = '名称、备注、标签和收藏已保存';
    await loadLibrary(true);
    const refreshed = libraryItems.find(item => item.id === data.id);
    if (refreshed) selectLibraryItem(refreshed);
  } catch (error) {
    $('library-action-status').textContent = '保存失败：' + error.message;
  } finally { button.disabled = false; }
}

function askLibraryAction(kind) {
  if (!librarySelected) return;
  libraryPendingAction = { kind, id: librarySelected.id };
  const permanent = kind === 'delete';
  $('library-confirm-title').textContent = permanent ? '永久删除这张立绘？' : '移到回收站？';
  $('library-confirm-message').textContent = permanent
    ? '图片和资料将被永久删除，无法恢复。'
    : '图片会移到工坊回收站，之后可以恢复。';
  $('library-confirm-submit').textContent = permanent ? '永久删除' : '移到回收站';
  $('library-confirm').showModal();
}

async function runLibraryAction() {
  const action = libraryPendingAction;
  if (!action) return;
  $('library-confirm-submit').disabled = true;
  const endpoint = action.kind === 'trash' ? 'trash' : action.kind;
  try {
    const response = await fetch('/api/library/' + endpoint, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: action.id, special: mode === 'special' }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '操作失败');
    $('library-confirm').close();
    libraryPendingAction = null;
    await loadLibrary(true);
  } catch (error) {
    $('library-confirm-message').textContent = '操作失败：' + error.message;
  } finally { $('library-confirm-submit').disabled = false; }
}

async function restoreLibraryItem() {
  if (!librarySelected) return;
  $('library-action-status').textContent = '正在恢复…';
  try {
    const response = await fetch('/api/library/restore', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: librarySelected.id, special: mode === 'special' }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '恢复失败');
    await loadLibrary(true);
  } catch (error) { $('library-action-status').textContent = '恢复失败：' + error.message; }
}

async function openLibraryRoot() {
  $('library-count').textContent = '正在打开文件夹…';
  try {
    const response = await fetch('/api/settings/open-folder', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target: 'library' }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '无法打开文件夹');
    $('library-count').textContent = '已打开立绘库文件夹';
  } catch (error) { $('library-count').textContent = '打开失败：' + error.message; }
}

async function exportCurrent() {
  const button = $('download');
  const label = $('export-status');
  const openFolderBtn = $('open-export-folder');
  button.disabled = true;
  label.textContent = '正在准备 PNG…';
  if (openFolderBtn) openFolderBtn.hidden = true;
  try {
    if (!appSettings) throw new Error('设置尚未读取完成，请稍后重试');
    //WebView2 的静默下载用户根本找不到文件。浏览器下载仍作为可选模式保留。
    if (appSettings.singleMode === 'folder') {
      const response = await fetch('/api/export-file', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ game: $('game').value, character: $('character').value,
          body: $('body').value, face: $('face').value, special: mode === 'special' }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '无法保存图片');
      //显示实际保存路径，便于定位导出文件。
      const savedPath = data.path || data.dir;
      label.innerHTML = '';
      label.append(`已保存：${data.name || savedPath}`);
      if (data.path) {
        const hint = document.createElement('span');
        hint.className = 'export-path';
        hint.textContent = data.path;
        hint.title = data.path;
        label.append(document.createElement('br'), hint);
      }
      if (openFolderBtn) { openFolderBtn.hidden = false; openFolderBtn.dataset.dir = data.dir || ''; }
      setStatus('已保存到磁盘');
      return;
    }
    const response = await fetch('/api/export?' + params());
    if (!response.ok) throw new Error(await response.text());
    const blob = await response.blob();
    const encodedName = response.headers.get('Content-Disposition')?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
    const filename = encodedName ? decodeURIComponent(encodedName) : `${$('character').value}_${$('face').value}.png`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    label.textContent = '已发送到浏览器下载，请查看下载列表';
  } catch (error) {
    label.textContent = '导出失败：' + error.message;
  } finally {
    button.disabled = $('preview').hidden;
  }
}

function customKey(item) {
  return JSON.stringify([item.game, item.character, item.body, item.face]);
}

function batchImageUrl(item, detail = false) {
  const query = new URLSearchParams(item);
  if (detail) query.set('size', 'detail');
  return '/api/expression-preview?' + query;
}

function showBatchInspector(item) {
  batchInspect = item;
  batchImageSerial++;
  const serial = batchImageSerial;
  const image = $('batch-inspector-image');
  image.hidden = true;
  $('batch-inspector-empty').hidden = false;
  $('batch-inspector-empty').textContent = item ? '正在加载预览…' : '请选择表情';
  $('batch-inspector-title').textContent = item ? `表情 ${item.face}` : '表情预览';
  $('batch-inspector-hint').textContent = item ? `${item.character} / ${item.body}` : '点击左侧图片查看';
  $('batch-view-face').classList.toggle('active', batchView === 'face');
  $('batch-view-full').classList.toggle('active', batchView === 'full');
  for (const button of $('batch-face-grid').querySelectorAll('.batch-face-image')) {
    button.classList.toggle('active', button.dataset.face === item?.face);
  }
  if (!item) return;
  image.onload = () => {
    if (serial !== batchImageSerial) return;
    image.hidden = false;
    $('batch-inspector-empty').hidden = true;
  };
  image.onerror = () => {
    if (serial === batchImageSerial) $('batch-inspector-empty').textContent = '预览失败，请换一个表情重试';
  };
  image.src = batchView === 'face' ? batchImageUrl(item, true) : '/api/preview?' + new URLSearchParams(item);
}

function setBatchView(view) {
  batchView = view;
  showBatchInspector(batchInspect);
}

function toggleBatchBackground() {
  batchBackground = batchBackground === 'light' ? 'dark' : 'light';
  $('batch-inspector-visual').classList.toggle('light', batchBackground === 'light');
  $('batch-inspector-visual').classList.toggle('dark', batchBackground === 'dark');
  $('batch-bg-toggle').textContent = batchBackground === 'light' ? '深色背景' : '浅色背景';
}

function renderCustomQueue() {
  const list = $('batch-queue');
  list.replaceChildren();
  customQueue.forEach((item, index) => {
    const row = document.createElement('div');
    row.className = 'batch-queue-row';
    const text = document.createElement('span');
    text.textContent = `${item.game} / ${item.character} / ${item.body} / ${item.face}`;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.textContent = '移除';
    remove.disabled = customRunning;
    remove.setAttribute('aria-label', `移除第 ${index + 1} 张`);
    remove.onclick = () => { customQueue.splice(index, 1); renderCustomQueue(); };
    row.append(text, remove);
    list.append(row);
  });
  $('batch-count').textContent = customQueue.length || '';
  $('batch-count').hidden = customQueue.length === 0;
  if ($('batch-library-quick')) {
    $('batch-library-quick').disabled = customQueue.length === 0 || Boolean(libraryBatchId);
  }
  $('batch-queue-empty').hidden = customQueue.length > 0;
  $('batch-clear').disabled = customRunning || customQueue.length === 0;
  $('batch-start').disabled = customRunning || customQueue.length === 0;
  $('batch-start').textContent = customRunning ? '正在合成…' : `开始批量合成（${customQueue.length} 张）`;
  if ($('batch-library-save')) {
    $('batch-library-save').disabled = customQueue.length === 0 || Boolean(libraryBatchId);
    $('batch-library-save').textContent = libraryBatchId
      ? '正在入库…' : `批量保存到立绘库（${customQueue.length} 张）`;
  }
  sessionStorage.setItem('bingyiBatchQueue', JSON.stringify(customQueue));
}

function renderBatchPicker() {
  const game = $('game').value;
  const character = $('character').value;
  const body = $('body').value;
  const faces = mode === 'normal' ? currentCharacter()?.bodies[body] || [] : [];
  $('batch-pose-label').textContent = faces.length ? `${character} / ${body}` : '当前没有可添加的普通组合';
  const grid = $('batch-face-grid');
  if (batchObserver) batchObserver.disconnect();
  grid.replaceChildren();
  const observer = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const button = entry.target;
      const image = button.querySelector('img');
      image.src = button.dataset.src;
      observer.unobserve(button);
    }
  }, { root: grid, rootMargin: '120px' });
  batchObserver = observer;
  faces.forEach(face => {
    const card = document.createElement('div');
    card.className = 'batch-face-card';
    const preview = document.createElement('button');
    preview.className = 'batch-face-image';
    preview.type = 'button';
    preview.dataset.face = face;
    preview.dataset.src = batchImageUrl({ game, character, body, face });
    preview.setAttribute('aria-label', `查看表情 ${face}`);
    const image = document.createElement('img');
    image.alt = '';
    image.onerror = () => { preview.replaceChildren(document.createTextNode('预览失败')); };
    preview.append(image);
    preview.onclick = () => {
      const checkbox = card.querySelector('input[type="checkbox"]');
      if (!checkbox || checkbox.disabled) return;
      checkbox.checked = !checkbox.checked;
      updateBatchPickCount();
      //同时让右侧大图跟着切换，方便"勾一张看一眼"
      showBatchInspector({ game, character, body, face });
    };
    const label = document.createElement('label');
    label.className = 'batch-face-check';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.value = face;
    checkbox.disabled = customRunning;
    checkbox.checked = face === $('face').value;
    checkbox.onchange = updateBatchPickCount;
    const syncCardState = () => {
      card.classList.toggle('picked', checkbox.checked);
      preview.setAttribute('aria-pressed', checkbox.checked ? 'true' : 'false');
      preview.setAttribute('aria-label', `${checkbox.checked ? '取消选择' : '选择'}表情 ${face}`);
    };
    checkbox.addEventListener('change', syncCardState);
    label.append(checkbox, document.createTextNode(face));
    card.append(preview, label);
    grid.append(card);
    syncCardState();
    observer.observe(preview);
  });
  $('batch-select-all').disabled = customRunning || !faces.length;
  $('batch-select-none').disabled = customRunning || !faces.length;
  updateBatchPickCount();
  showBatchInspector(faces.length ? { game, character, body, face: faces.includes($('face').value) ? $('face').value : faces[0] } : null);
}

function updateBatchPickCount() {
  const grid = $('batch-face-grid');
  const count = grid.querySelectorAll('input:checked').length;
  $('batch-pick-count').textContent = `已选 ${count} 个`;
  $('batch-add').disabled = customRunning || count === 0;
  //卡片上的"已勾选"外观也要跟上（点图勾选、全选/清空都会走到这里）。
  grid.querySelectorAll('.batch-face-card').forEach(card => {
    const checkbox = card.querySelector('input[type="checkbox"]');
    card.classList.toggle('picked', Boolean(checkbox && checkbox.checked));
  });
}

function selectBatchFaces(checked) {
  $('batch-face-grid').querySelectorAll('input').forEach(input => { input.checked = checked; });
  updateBatchPickCount();
}

function addBatchFaces() {
  const base = { game: $('game').value, character: $('character').value, body: $('body').value };
  if (customQueue.length >= 500) { $('batch-result').textContent = '清单已达 500 张上限，无法继续添加。'; return; }
  const existing = new Set(customQueue.map(customKey));
  let added = 0;
  for (const input of $('batch-face-grid').querySelectorAll('input:checked')) {
    const item = { ...base, face: input.value };
    if (existing.has(customKey(item))) continue;
    if (customQueue.length >= 500) break;
    customQueue.push(item);
    existing.add(customKey(item));
    added++;
  }
  renderCustomQueue();
  $('batch-result').textContent = added ? `已加入 ${added} 张。关闭窗口可继续挑选其他姿势或作品。` : '所选表情已在清单中，或已达到 500 张上限。';
}

async function pollCustomBatch() {
  if (!customJobId) return;
  try {
    const response = await fetch('/api/custom-batch?id=' + encodeURIComponent(customJobId));
    const job = await response.json();
    if (response.status === 404) {
      customJobId = '';
      customRunning = false;
      sessionStorage.removeItem('bingyiBatchJob');
      renderCustomQueue();
      renderBatchPicker();
      $('batch-result').textContent = job.error || '任务记录不存在，请重新启动批量合成';
      return;
    }
    if (!response.ok) throw new Error(job.error || '进度读取失败');
    $('batch-progress-bar').hidden = false;
    $('batch-progress-bar').max = job.total;
    $('batch-progress-bar').value = job.completed;
    $('batch-progress').textContent = `${job.completed} / ${job.total} 张`;
    $('batch-errors').replaceChildren();
    if (job.errors.length) {
      $('batch-errors').hidden = false;
      job.errors.forEach(message => {
        const line = document.createElement('p');
        line.textContent = message;
        $('batch-errors').append(line);
      });
    } else $('batch-errors').hidden = true;
    if (job.state === 'running') {
      $('batch-result').textContent = job.current ? `正在处理：${job.current}` : '正在准备导出目录…';
      setTimeout(pollCustomBatch, 700);
      return;
    }
    customJobId = '';
    customRunning = false;
    sessionStorage.removeItem('bingyiBatchJob');
    const completedWithoutErrors = job.state === 'finished' && job.succeeded === job.total;
    if (completedWithoutErrors) customQueue = [];
    renderCustomQueue();
    renderBatchPicker();
    $('batch-result').textContent = job.state === 'finished'
      ? `完成：成功 ${job.succeeded} 张，失败 ${job.total - job.succeeded} 张。${completedWithoutErrors ? '待导出清单已清空。' : '清单已保留，方便检查失败项。'}文件和清单位于 ${job.output}`
      : `批量任务中断。已完成 ${job.completed} / ${job.total} 张；请查看下方原因和 ${job.output}`;
  } catch (error) {
    $('batch-result').textContent = `进度暂时无法读取：${error.message}。程序若仍在运行，稍后会继续查询。`;
    if (customJobId) setTimeout(pollCustomBatch, 2500);
  }
}

async function startCustomBatch() {
  if (!customQueue.length || customRunning) return;
  customRunning = true;
  renderCustomQueue();
  renderBatchPicker();
  $('batch-result').textContent = '正在提交清单…';
  $('batch-errors').hidden = true;
  try {
    const response = await fetch('/api/custom-batch', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items: customQueue }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '批量任务无法启动');
    customJobId = data.id;
    sessionStorage.setItem('bingyiBatchJob', customJobId);
    pollCustomBatch();
  } catch (error) {
    customRunning = false;
    renderCustomQueue();
    renderBatchPicker();
    $('batch-result').textContent = '启动失败：' + error.message;
  }
}

//图库批量保存负责入库与标签，磁盘批量导出使用独立入口。
let libraryBatchId = '';

async function startLibraryBatch() {
  if (!customQueue.length) return;
  const button = $('batch-library-save');
  const status = $('batch-library-status');
  button.disabled = true;
  status.textContent = '正在提交入库清单…';
  try {
    const response = await fetch('/api/library/batch-save', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items: customQueue, label: $('batch-library-label').value.trim() }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '入库任务无法启动');
    libraryBatchId = data.id;
    $('batch-library-bar').hidden = false;
    $('batch-library-bar').max = Math.max(1, data.total);
    $('batch-library-bar').value = 0;
    pollLibraryBatch();
  } catch (error) {
    status.textContent = '入库失败：' + error.message;
    button.disabled = false;
  }
}

async function pollLibraryBatch() {
  if (!libraryBatchId) return;
  const status = $('batch-library-status');
  const button = $('batch-library-save');
  try {
    const response = await fetch('/api/library/batch-status', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: libraryBatchId }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '查询失败');
    $('batch-library-bar').value = data.completed || 0;
    if (data.state === 'running') {
      status.textContent = `正在入库 ${data.completed}/${data.total}：${data.current || ''}`;
      setTimeout(pollLibraryBatch, 400);
      return;
    }
    libraryBatchId = '';
    button.disabled = false;
    if (data.state === 'failed') {
      status.textContent = '入库中断：' + (data.errors?.[data.errors.length - 1] || '未知原因');
      return;
    }
    const created = data.created || 0;
    const duplicate = data.duplicate || 0;
    status.textContent = `入库完成：新增 ${created} 张，已存在 ${duplicate} 张（自动打好标签）`
      + (data.manifest ? ` · 清单：${data.manifest}` : '');
    if (data.errors?.length) {
      $('batch-errors').hidden = false;
      $('batch-errors').textContent = data.errors.join('\n');
    }
  } catch (error) {
    status.textContent = '查询失败：' + error.message;
    button.disabled = false;
  }
}

//设置首页只显示分组，详情页保留各控件绑定。
const SETTINGS_PANELS = {
  'panel-single': ['单张立绘', '单张导出的落盘方式与目录。'],
  'panel-batch': ['批量输出', '自选批量合成的输出目录。'],
  'panel-drag': ['拖出文件夹', '拖给剪映 / PR 的 PNG 落点（默认永不自动清理）。'],
  'panel-data': ['数据位置', '立绘库、设置、导出等用户数据的存放位置。'],
  'panel-packs': ['素材包导入', '按作品导入 ZIP 素材包，以及重新扫描素材。'],
  'panel-diagnostics': ['运行体检', '一次检查"能不能正常用"的前提。'],
  'panel-logs': ['日志与诊断包', '日志位置与一键打包。'],
  'panel-about': ['关于与许可', '版本、创作者与使用许可。'],
};

function openSettingsPanel(panelId) {
  const panel = $(panelId);
  if (!panel) return;
  document.querySelectorAll('#settings-page .settings-panel').forEach(node => { node.hidden = node !== panel; });
  $('settings-list').hidden = true;
  $('settings-back').hidden = false;
  const meta = SETTINGS_PANELS[panelId] || ['设置', ''];
  $('settings-title').textContent = meta[0];
  $('settings-subtitle').textContent = meta[1];
  $('settings-subtitle').hidden = !meta[1];
  $('settings-page').scrollTop = 0;
}

function closeSettingsPanel() {
  document.querySelectorAll('#settings-page .settings-panel').forEach(node => { node.hidden = true; });
  $('settings-list').hidden = false;
  $('settings-back').hidden = true;
  $('settings-title').textContent = '设置';
  $('settings-subtitle').textContent = '';
  $('settings-subtitle').hidden = true;
  $('settings-page').scrollTop = 0;
}

//当前值和说明只在对应的设置详情页显示。
function refreshSettingsRowValues() {
  const short = (text, limit = 46) => {
    const value = String(text || '—');
    return value.length > limit ? `…${value.slice(-limit)}` : value;
  };
  if ($('row-value-single')) {
    const folder = appSettings?.singleMode === 'folder';
    $('row-value-single').textContent = folder
      ? `保存到文件夹 · ${short(appSettings?.singlePath || appSettings?.defaultSinglePath)}`
      : '浏览器下载（位置由浏览器决定）';
  }
  if ($('row-value-batch')) $('row-value-batch').textContent = short(appSettings?.effectiveBatchPath || appSettings?.defaultBatchPath);
  if ($('row-value-drag')) $('row-value-drag').textContent = `永不自动清理 · ${short(appSettings?.effectiveDragPath || appSettings?.defaultDragPath)}`;
  if ($('row-value-data')) $('row-value-data').textContent = short(dataDirInfo?.current || '默认位置');
  if ($('row-value-packs')) {
    $('row-value-packs').textContent = packSummary || '查看已导入的素材包与扫描结果';
  }
  if ($('row-value-library-care')) {
    //进入设置时不扫描图库，扫描由明确操作触发。
    $('row-value-library-care').textContent = '清理中断导入留下的未入库文件';
  }
  if ($('row-value-check')) $('row-value-check').textContent = diagnosticsSummary || '点进去开始体检';
  if ($('row-value-logs')) {
    $('row-value-logs').textContent = logPath ? short(logPath) : 'startup.log（每次启动写入）';
  }
  if ($('row-value-about')) {
    const label = (brandData?.versionLabel || '').trim();
    $('row-value-about').textContent =
      `${brandData?.license || 'Apache-2.0'} · v${brandData?.version || '—'}${label ? ' ' + label : ''}`;
  }
}

let dataDirInfo = null;
let packSummary = '';
let diagnosticsSummary = '';
let logPath = '';

$('settings-back').onclick = closeSettingsPanel;
for (const row of document.querySelectorAll('#settings-list [data-settings-open]')) {
  row.onclick = () => openSettingsPanel(row.dataset.settingsOpen);
}
if ($('open-log-path')) {
  $('open-log-path').onclick = async () => {
    try {
      const resp = await fetch('/api/diagnostics');
      const data = await resp.json();
      if (data.logPath) {
        logPath = data.logPath;
        $('log-path').value = data.logPath;
        $('log-note').textContent = `日志：${data.logPath}`;
      }
      //复用"打开文件夹"通道：target=dir 接受任意已存在目录
      const dir = (logPath || '').replace(/[\\/][^\\/]*$/, '');
      const open = await fetch('/api/settings/open-folder', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target: 'dir', path: dir }),
      });
      const result = await open.json();
      $('log-note').textContent = open.ok ? `已打开：${result.path}` : `打开失败：${result.error || open.status}`;
    } catch (error) {
      $('log-note').textContent = '打开失败：' + error.message;
    }
  };
}

$('game').onchange = changeGame;
$('character').onchange = changeCharacter;
$('body').onchange = changeBody;
$('face').onchange = () => { syncFaceControls(); showPreview(); };
$('face-prev').onclick = () => stepFace(-1);
$('face-next').onclick = () => stepFace(1);
$('face-browse').onclick = openFacePicker;
$('close-face').onclick = () => $('face-dialog').close();
$('face-dialog').addEventListener('close', () => faceObserver?.disconnect());
$('face-search').oninput = filterFaceGrid;
$('face-search').onkeydown = event => {
  if (event.key !== 'Enter') return;
  event.preventDefault();
  const first = Array.from($('face-grid').querySelectorAll('button')).find(button => !button.hidden);
  if (first) first.click();
};
$('nav-workbench').onclick = () => switchPage('workbench');
$('nav-library').onclick = () => switchPage('library');
if ($('nav-tools')) $('nav-tools').onclick = () => switchPage('tools');
$('settings-button').onclick = () => switchPage('settings');
//工具箱里「立绘库」那张卡片：跳到对应页面（工具卡片统一用 data-goto 声明去处）
for (const card of document.querySelectorAll('.tool-card[data-goto]')) {
  card.onclick = () => switchPage(card.dataset.goto);
}
$('empty-import').onclick = () => {
  switchPage('settings');
  openSettingsPanel('panel-packs');
};
$('reset-batch-path').onclick = () => { $('batch-path').value = ''; syncSettingsFields(); scheduleAutoSave(); };
$('reset-drag-path').onclick = () => { $('drag-path').value = ''; syncSettingsFields(); scheduleAutoSave(); };
$('open-drag-path').onclick = () => openSettingsFolder('drag');
$('choose-drag-path').onclick = () => chooseSettingsFolder('drag');
$('cleanup-drag-path').onclick = cleanupDragFolder;
$('library-orphan-scan').onclick = scanLibraryOrphans;
$('library-orphan-clean').onclick = cleanLibraryOrphans;
$('library-orphan-cancel').onclick = () => resetLibraryOrphanUI('已取消，什么都没删。');
$('open-single-path').onclick = () => openSettingsFolder('single');
$('open-batch-path').onclick = () => openSettingsFolder('batch');
$('choose-single-path').onclick = () => chooseSettingsFolder('single');
$('choose-batch-path').onclick = () => chooseSettingsFolder('batch');
//拖出路径与其他目录输入共享修改状态监听。
for (const input of document.querySelectorAll('input[name="single-save-mode"], #single-path, #batch-path, #drag-path')) {
  //目录选项变化后防抖保存。
  input.addEventListener('input', () => { syncSettingsFields(); scheduleAutoSave(); });
}
$('download').onclick = exportCurrent;
$('open-export-folder').onclick = async () => {
  const label = $('export-status');
  try {
    const target = $('open-export-folder').dataset.dir ? 'dir' : 'single';
    const response = await fetch('/api/settings/open-folder', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target, path: $('open-export-folder').dataset.dir || '' }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '无法打开文件夹');
    label.textContent = '已打开：' + data.path;
  } catch (error) {
    label.textContent = '打开失败：' + error.message;
  }
};
$('save-library').onclick = saveToLibrary;
$('library-search').oninput = () => {
  clearTimeout(librarySearchTimer);
  librarySearchTimer = setTimeout(() => loadLibrary(true), 180);
};
$('library-game').onchange = () => { refreshLibraryFilters(); loadLibrary(true); };
$('library-character').onchange = () => loadLibrary(true);
$('library-tag').onchange = () => loadLibrary(true);
$('library-favorite').onchange = () => loadLibrary(true);
$('library-more').onclick = () => loadLibrary();
$('library-reveal').onclick = revealLibraryFile;
$('library-save-edit').onclick = saveLibraryMetadata;
$('library-trash').onclick = () => askLibraryAction('trash');
$('library-restore').onclick = restoreLibraryItem;
$('library-delete').onclick = () => askLibraryAction('delete');
$('library-open-root').onclick = openLibraryRoot;
$('library-view-active').onclick = () => { libraryTrash = false; resetLibraryView(); };
$('library-view-trash').onclick = () => { libraryTrash = true; resetLibraryView(); };
$('library-confirm-cancel').onclick = () => { libraryPendingAction = null; $('library-confirm').close(); };
$('library-confirm-submit').onclick = runLibraryAction;
$('open-custom-batch').onclick = () => { renderBatchPicker(); renderCustomQueue(); $('custom-batch-dialog').showModal(); };
$('batch-library-quick').onclick = () => {
  renderBatchPicker();
  renderCustomQueue();
  $('custom-batch-dialog').showModal();
  $('batch-library-save').scrollIntoView({ block: 'nearest' });
  $('batch-library-save').focus();
};
$('close-custom-batch').onclick = () => $('custom-batch-dialog').close();
$('batch-select-all').onclick = () => selectBatchFaces(true);
$('batch-select-none').onclick = () => selectBatchFaces(false);
$('batch-add').onclick = addBatchFaces;
$('batch-clear').onclick = () => { customQueue = []; renderCustomQueue(); $('batch-result').textContent = '清单已清空'; };
$('batch-start').onclick = startCustomBatch;
$('batch-library-save').onclick = startLibraryBatch;
$('batch-view-face').onclick = () => setBatchView('face');
$('batch-view-full').onclick = () => setBatchView('full');
$('batch-bg-toggle').onclick = toggleBatchBackground;
$('zoom-fit').onclick = () => setZoom('fit');
$('zoom-actual').onclick = () => setZoom(1);
$('zoom-out').onclick = () => setZoom((zoom === 'fit' ? fittedZoom() : zoom) / 1.25);
$('zoom-in').onclick = () => setZoom((zoom === 'fit' ? fittedZoom() : zoom) * 1.25);
window.addEventListener('resize', () => { if (!$('preview').hidden) applyZoom(); });
//画布尺寸变化（窗口拖拽、侧栏折叠、浏览器缩放）也要重新适应
//只在"适应窗口"状态下跟随，用户显式放大/100% 时不打扰他。
if (typeof ResizeObserver !== 'undefined') {
  new ResizeObserver(() => {
    if (!$('preview').hidden && !explicitUserZoom) applyZoom();
  }).observe($('canvas-viewport'));
}

let panStart = null;
$('canvas-viewport').addEventListener('pointerdown', event => {
  if (zoom === 'fit' || $('preview').hidden) return;
  const viewport = $('canvas-viewport');
  panStart = { x: event.clientX, y: event.clientY, left: viewport.scrollLeft, top: viewport.scrollTop };
  viewport.setPointerCapture(event.pointerId);
  viewport.classList.add('panning');
});
$('canvas-viewport').addEventListener('pointermove', event => {
  if (!panStart) return;
  const viewport = $('canvas-viewport');
  viewport.scrollLeft = panStart.left - (event.clientX - panStart.x);
  viewport.scrollTop = panStart.top - (event.clientY - panStart.y);
});
for (const eventName of ['pointerup', 'pointercancel', 'lostpointercapture']) {
  $('canvas-viewport').addEventListener(eventName, () => {
    panStart = null;
    $('canvas-viewport').classList.remove('panning');
  });
}

updateMode();
//在 /api/boot 报 ready 之后调用（数据类接口在就绪前会被服务端闸门挡住）。
function parseCustomQueue() {
  try { customQueue = JSON.parse(sessionStorage.getItem('bingyiBatchQueue') || '[]'); } catch { customQueue = []; }
  if (!Array.isArray(customQueue)) customQueue = [];
  renderCustomQueue();
  if (customJobId) pollCustomBatch();
}

async function loadCatalog() {
  const response = await fetch('/api/catalog');
  if (!response.ok) throw new Error('素材目录读取失败');
  catalog = await response.json();
  customQueue = customQueue.filter(item => {
    if (!item || typeof item !== 'object') return false;
    const entry = catalog[item.game]?.characters[item.character];
    return entry?.bodyCategories[item.body] === 'normal' && entry.bodies[item.body]?.includes(item.face);
  });
  renderCustomQueue();
  refreshGames();
  refreshLibraryFilters();
  if (activePage === 'library') loadLibrary(true);
}

//冰翼Gal创作工坊 设置页扩展：品牌填充 / 数据位置 / 素材包导入
async function loadBrand() {
  try {
    const resp = await fetch('/api/brand');
    if (!resp.ok) return;
    brandData = await resp.json();
    if (brandData && brandData.appName) document.title = brandData.appName;
    const v = $('app-version');
      if (v && brandData && brandData.version) {
        //versionLabel 用于内测/正式区分：留空显示「v1.0」，填「内测版」显示「v1.0 内测版」。
        //打安装包时只改 ui/brand.json 一处，前端与安装包名可以共用这个字段。
        const label = (brandData.versionLabel || '').trim();
        v.textContent = 'v' + brandData.version + (label ? ' ' + label : '');
      }
    //关于页同步版权与当前版本使用许可。
    hydrateAboutPanel(brandData);
    //内测期限提示（过期/临近时出现）
    renderBetaNotice(brandData.beta);
    //品牌数据加载后刷新关于页摘要。
    const aboutRow = $('row-value-about');
    if (aboutRow) {
      const rowLabel = (brandData.versionLabel || '').trim();
      aboutRow.textContent = `${brandData.license || 'Apache-2.0'} · v${brandData.version}`
        + (rowLabel ? ' ' + rowLabel : '');
    }
  } catch (e) { /*ignore*/ }
}

//关于与许可
//由 loadBrand() 在顶层调用，保持与当前发行许可同步。
function hydrateAboutPanel(brand) {
  const data = brand || {};
  const appLine = $('about-app-line');
  if (appLine) {
    const label = (data.versionLabel || '').trim();
    appLine.textContent = `${data.appName || '冰翼Gal创作工坊'} v${data.version || '—'}`
      + (label ? ` ${label}` : '')
      + (data.tagline ? ` · ${data.tagline}` : '');
  }
  const copy = $('about-copyright');
  if (copy) copy.textContent = data.copyright || '';
  const license = $('about-license');
  if (license) license.textContent = data.license || 'Apache-2.0';

  const thirdParty = $('about-third-party');
  if (thirdParty) {
    thirdParty.textContent = 'PBD 读取器已重写；当前版本使用新的 PBD 读取器。历史来源与格式资料见第三方声明。'
      + '其余依赖：Pillow（MIT-CMU）、PySide6 / shiboken6（LGPL-3.0）、'
      + 'pywebview（BSD-3-Clause）、pythonnet（MIT）。详见 THIRD_PARTY_NOTICES.md。';
  }
  const openLicense = $('open-license-file');
  //Windows 打开 LICENSE.txt 副本，避免无扩展名文件的关联提示。
  if (openLicense) openLicense.onclick = () => openAboutFile('LICENSE.txt');
  const openThird = $('open-third-party');
  if (openThird) openThird.onclick = () => openAboutFile('THIRD_PARTY_NOTICES.md');
}

//用户的原话是「内测包发给人家，他不卸载怎么办」—— 真实痛点是
function renderBetaNotice(beta) {
  const bar = $('beta-notice');
  const text = $('beta-notice-text');
  if (!bar || !text) return;
  if (!beta || !beta.configured) { bar.hidden = true; return; }
  const label = (brandData?.versionLabel || '').trim();
  const mine = `v${brandData?.version || '—'}${label ? ' ' + label : ''}`;
  let message = '';
  if (beta.expired) {
    message = `这个内测包（${mine}）已过内测期（${beta.deadline}）。`
      + (beta.message || '建议找作者拿新包 —— 你现在遇到的问题可能已经修好了。');
  } else if (beta.warn) {
    message = `内测期还有 ${beta.daysLeft} 天结束（${beta.deadline}）。`
      + '到期后建议换新包，旧版本可能已经修好了你遇到的问题。';
  } else {
    bar.hidden = true;
    return;
  }
  text.textContent = message;          //textContent：不拼 HTML，外部配置不进 DOM 结构
  bar.hidden = false;
  bar.classList.toggle('beta-notice-expired', Boolean(beta.expired));
  const close = $('beta-notice-close');
  if (close) close.onclick = () => { bar.hidden = true; };
  //过期提醒每次启动只弹出一次。
  if (beta.expired && !sessionStorage.getItem('bingyiBetaNoticeShown')) {
    sessionStorage.setItem('bingyiBetaNoticeShown', '1');
    window.alert(`${mine} 已过内测期（${beta.deadline}）。\n\n`
      + (beta.message || '建议找作者拿新包 —— 你现在遇到的问题可能已经修好了。')
      + '\n\n程序仍可正常使用。');
  }
}

async function openAboutFile(name) {
  const thirdParty = $('about-third-party');
  try {
    const response = await fetch('/api/settings/open-folder', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: 'app-file', name }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '打不开');
    if (thirdParty) thirdParty.textContent = `已打开：${data.path}`;
  } catch (error) {
    if (thirdParty) thirdParty.textContent = '打开失败：' + error.message;
  }
}
function bindSettingsExtensions() {
  const dataDirInput = $('data-dir-path');
  const dataDirNote = $('data-dir-note');
  async function refreshDataDir() {
    try {
      const resp = await fetch('/api/data-dir');
      if (!resp.ok) return;
      const info = await resp.json();
      if (dataDirInput) dataDirInput.value = info.current || '';
      if (dataDirNote) dataDirNote.textContent = info.custom
        ? `自定义位置；重启后生效。默认：${info.default}`
        : `默认位置（${info.frozen ? '安装版' : '开发态'}）。`;
      dataDirInfo = info;
      refreshSettingsRowValues();
    } catch (e) { /*ignore*/ }
  }
  const postDataDir = async (body) => {
    try {
      const resp = await fetch('/api/data-dir', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      return await resp.json();
    } catch (e) { return { ok: false, error: '请求失败' }; }
  };
  const chooseDataDir = $('choose-data-dir');
  if (chooseDataDir) chooseDataDir.onclick = async () => {
    const path = prompt('输入新的数据目录路径（复制现有数据过去，不删除原数据）：');
    if (!path) return;
    const r = await postDataDir({ action: 'set', path });
    if (dataDirNote) dataDirNote.textContent = r.ok ? `已设置，重启后生效：${r.current}` : `失败：${r.error || '未知错误'}`;
    refreshDataDir();
  };
  const resetDataDir = $('reset-data-dir');
  if (resetDataDir) resetDataDir.onclick = async () => { await postDataDir({ action: 'reset' }); refreshDataDir(); };
  const openDataDir = $('open-data-dir');
  if (openDataDir) openDataDir.onclick = async () => { await postDataDir({ action: 'open' }); };

  const packPathInput = $('pack-import-path');
  const packStatus = $('pack-import-status');
  const packLinksList = $('pack-links-list');
  const packPreview = $('pack-import-preview');
  const packProgress = $('pack-import-progress');
  const packProgressText = $('pack-import-progress-text');
  const packConfirm = $('pack-import-confirm');
  const packCancel = $('pack-import-cancel');
  let packPickedPath = '';
  function setPackBusy(busy, text) {
    if (packProgress) packProgress.hidden = !busy;
    if (packProgressText) packProgressText.textContent = text || '';
    if (packConfirm) packConfirm.disabled = !!busy;
    if (packCancel) packCancel.disabled = !!busy;
  }
  function clearPackPreview() {
    if (packPreview) { packPreview.hidden = true; packPreview.replaceChildren(); }
    if (packConfirm) packConfirm.hidden = true;
    if (packCancel) packCancel.hidden = true;
    packPickedPath = '';
  }
  async function refreshPackLinks() {
    try {
      const resp = await fetch('/api/packs');
      if (!resp.ok) return;
      const data = await resp.json();
      const packs = data.packs || [];
      if (!packLinksList) return;
      packLinksList.replaceChildren();
      if (!packs.length) {
        const empty = document.createElement('p');
        empty.className = 'settings-description';
        empty.textContent = '暂无已导入的素材包。';
        packLinksList.append(empty);
        return;
      }
      //p.name / p.path 来自数据目录里的「素材链接.json」，是可被手工编辑的文件。
      for (const pack of packs) {
        const row = document.createElement('div');
        row.className = 'pack-link-item';
        const name = document.createElement('span');
        name.textContent = pack.name;
        const meta = document.createElement('span');
        meta.className = 'pack-link-path';
        meta.textContent = pack.source === 'link' ? pack.path : '已导入';
        const isLink = pack.source === 'link';
        const remove = document.createElement('button');
        remove.textContent = isLink ? '移除' : '删除';
        remove.dataset.pack = pack.name;
        remove.onclick = async () => {
          const packName = remove.dataset.pack;
          try {
            if (isLink) {
              await fetch('/api/packs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'remove-link', name: packName }) });
            } else {
              if (!window.confirm('删除素材包「' + packName + '」？该操作不可撤销，需重启程序后生效。')) return;
              const resp = await fetch('/api/packs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'delete', name: packName }) });
              const r = await resp.json();
              if (r && r.error && packStatus) packStatus.textContent = '删除失败：' + r.error;
            }
            refreshPackLinks();
          } catch (e) { /*忽略：刷新一次即可看到真实状态*/ }
        };
        row.append(name, meta, remove);
        packLinksList.append(row);
      }
    } catch (e) { /*ignore*/ }
  }
  const packScanSummary = $('pack-scan-summary');
  async function refreshScanSummary() {
    if (!packScanSummary) return;
    try {
      const resp = await fetch('/api/scan-summary');
      if (!resp.ok) return;
      const s = await resp.json();
      if (!s || s.empty) {
        packScanSummary.textContent = '最近一次扫描：未发现任何可合成素材。';
        return;
      }
      const gameCount = (s.txtGames || 0) + (s.pngCharacters ? 1 : 0) + (s.limeCharacters ? 1 : 0);
      const roleCount = (s.pngCharacters || 0) + (s.limeCharacters || 0) + (s.txtCharacters || 0);
      const rootCount = (s.roots || []).length;
      const warnCount = (s.warnings || []).length;
      packScanSummary.textContent =
        `最近一次扫描：${rootCount} 个素材目录，发现 ${gameCount} 部作品、${roleCount} 个角色` +
        (warnCount ? `，${warnCount} 条警告` : '') + '。';
      packSummary = packScanSummary.textContent;
      refreshSettingsRowValues();
    } catch (e) { /*ignore*/ }
  }
  async function previewPack(path) {
    setPackBusy(true, '正在检查压缩包…');
    if (packStatus) packStatus.textContent = '正在检查压缩包…';
    clearPackPreview();
    try {
      const resp = await fetch('/api/packs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'preview', path }) });
      const r = await resp.json();
      if (!r.ok) {
        setPackBusy(false, '');
        if (packStatus) packStatus.textContent = '无法导入：' + ((r.errors || []).join('；') || '未知错误');
        return;
      }
      packPickedPath = path;
      if (packPreview) {
        packPreview.hidden = false;
        packPreview.replaceChildren();
        const head = document.createElement('p');
        head.className = 'settings-description';
        const games = (r.games || []).length;
        head.textContent = `压缩包「${r.packName}」：约 ${games} 部作品、${r.fileCount} 个文件`
          + (r.existing ? '。该作品已存在，确认后将覆盖更新。' : '。');
        packPreview.append(head);
        if (r.pngChecked) {
          const note = document.createElement('p');
          note.className = 'action-note';
          note.textContent = `纯图片包：抽查 ${r.pngChecked} 张，`
            + (r.pngPositionOk ? '检测到坐标，可用于合成。' : '未检测到坐标。');
          packPreview.append(note);
        }
      }
      if (packConfirm) packConfirm.hidden = false;
      if (packCancel) packCancel.hidden = false;
      if (packStatus) packStatus.textContent = '检查完成，请确认导入。';
      setPackBusy(false, '');
    } catch (e) {
      setPackBusy(false, '');
      if (packStatus) packStatus.textContent = '检查压缩包失败。';
    }
  }
  async function commitPack() {
    if (!packPickedPath) return;
    setPackBusy(true, '正在导入…');
    if (packStatus) packStatus.textContent = '正在导入…';
    try {
      const resp = await fetch('/api/packs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'copy', path: packPickedPath, confirmUpdate: true }) });
      const r = await resp.json();
      if (!r.ok) {
        setPackBusy(false, '');
        if (packStatus) packStatus.textContent = '导入失败：' + ((r.errors || []).join('；') || '未知错误');
        return;
      }
      setPackBusy(false, '');
      clearPackPreview();
      if (packPathInput) packPathInput.value = '';
      refreshPackLinks();
      refreshScanSummary();
      scheduleRestartAfterImport(`导入成功：「${r.packName}」，共 ${r.fileCount} 个文件`);
    } catch (e) {
      setPackBusy(false, '');
      if (packStatus) packStatus.textContent = '导入请求失败。';
    }
  }
  //导入生效需要重启程序（扫描只在启动阶段做）。收尾自动重启
  function triggerAppRestart() {
    fetch('/api/rescan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) }).catch(() => {});
  }
  function hasWorkInProgress() {
    //设置改动还没落盘（300ms 防抖窗口内）。
    if (typeof autoSaveTimer !== 'undefined' && autoSaveTimer) return true;
    //批量处理任务进行中：重启会把它打断。
    if (typeof customRunning !== 'undefined' && customRunning) return true;
    if (typeof customJobId !== 'undefined' && customJobId) return true;
    return false;
  }
  function scheduleRestartAfterImport(message) {
    if (hasWorkInProgress()) {
      if (window.confirm(message + '。\n\n检测到还有进行中的任务（例如批量处理）。现在重启会打断它，确定要立即重启吗？')) {
        triggerAppRestart();
      } else if (packStatus) {
        packStatus.textContent = '导入成功，但已保留当前任务；稍后请手动重启程序让导入生效。';
      }
      return;
    }
    let remain = 3;
    if (packStatus) packStatus.textContent = message + `。程序将在 ${remain} 秒后自动重启以生效…`;
    const timer = setInterval(() => {
      remain -= 1;
      if (remain <= 0) {
        clearInterval(timer);
        triggerAppRestart();
      } else if (packStatus) {
        packStatus.textContent = message + `。程序将在 ${remain} 秒后自动重启以生效…`;
      }
    }, 1000);
  }
  const packConfirmBtn = $('pack-import-confirm');
  if (packConfirmBtn) packConfirmBtn.onclick = () => commitPack();
  const packCancelBtn = $('pack-import-cancel');
  if (packCancelBtn) packCancelBtn.onclick = () => {
    clearPackPreview();
    if (packPathInput) packPathInput.value = '';
    if (packStatus) packStatus.textContent = '已取消。';
  };
  const packChoose = $('pack-import-choose');
  if (packChoose) packChoose.onclick = async () => {
    if (packStatus) packStatus.textContent = '正在打开文件选择框…';
    try {
      const resp = await fetch('/api/settings/choose-pack-dir', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({})
      });
      const r = await resp.json();
      if (r && r.path) {
        if (packPathInput) packPathInput.value = r.path;
        previewPack(r.path);
      } else {
        if (packStatus) packStatus.textContent = '未选择文件。';
      }
    } catch (e) {
      if (packStatus) packStatus.textContent = '打开文件选择框失败。';
    }
  };

  refreshDataDir();
  refreshPackLinks();
  refreshScanSummary();
}

//无边框桌面窗口
function setupDesktopChrome() {
  const root = document.documentElement;
  const shellFlagged = /[?&]shell=desktop/.test(location.search);

  //通过 shell=desktop 标记启用桌面窗口桥接。
  //不依赖 window.pywebview 注入，保证右上角最小化/最大化/关闭按钮始终显示。
  if (shellFlagged && !root.classList.contains('desktop-shell')) {
    root.classList.add('desktop-shell');
  }

  const api = window.pywebview && window.pywebview.api;
  if (!api) {
    //② 轮询兜底：pywebview api 可能晚于页面脚本注入，每 200ms 重试，最多 10 秒。
    if (!window.__bgwShellPoll) {
      let tries = 0;
      window.__bgwShellPoll = setInterval(() => {
        tries += 1;
        if (window.pywebview && window.pywebview.api) {
          clearInterval(window.__bgwShellPoll);
          window.__bgwShellPoll = null;
          setupDesktopChrome();
        } else if (tries >= 50) {
          clearInterval(window.__bgwShellPoll);
          window.__bgwShellPoll = null;
        }
      }, 200);
    }
    return;
  }

  if (window.__bgwShellBound) return;
  window.__bgwShellBound = true;

  try {
    api.log_frontend('pywebview.api 可用; desktop-shell=' + root.classList.contains('desktop-shell') + '; shellFlagged=' + shellFlagged);
  } catch (e) { /*诊断写入失败不影响功能*/ }

  //DWM 非客户区颜色由原生窗口接口同步。
  //原生标题栏与页头保持一致的深色。
  const applyCaptionColor = () => {
    try { api.set_caption_color('#102136'); } catch (e) { /*浏览器回退模式无此接口*/ }
  };
  window.__bgwApplyCaptionColor = applyCaptionColor;
  applyCaptionColor();

  root.classList.add('desktop-shell');

  const header = document.querySelector('.app-header');
  const maxButton = $('window-maximize');

  const applyWindowState = state => {
    const maximized = Boolean(state && state.maximized);
    root.classList.toggle('window-maximized', maximized);
    if (maxButton) {
      maxButton.title = maximized ? '还原' : '最大化';
      maxButton.setAttribute('aria-label', maximized ? '还原' : '最大化');
    }
  };
  const refreshWindowState = async () => {
    try { applyWindowState(await api.get_state()); } catch (e) { /*browser fallback*/ }
  };
  const toggleMaximize = async () => {
    try {
      applyWindowState(await api.toggle_maximize());
      setTimeout(refreshWindowState, 160);
    } catch (e) { /*window may already be closing*/ }
  };

  $('window-minimize').onclick = () => api.minimize();
  maxButton.onclick = toggleMaximize;
  $('window-close').onclick = () => api.close();

  const isInteractive = target => Boolean(target.closest('button, input, select, textarea, a, .app-nav, .header-actions, .window-controls, [role="button"]'));
  header.addEventListener('pointerdown', event => {
    if (event.button !== 0 || isInteractive(event.target)) return;
    event.preventDefault();
    api.begin_move();
  });
  header.addEventListener('dblclick', event => {
    if (isInteractive(event.target)) return;
    event.preventDefault();
    toggleMaximize();
  });
  header.addEventListener('contextmenu', event => {
    if (isInteractive(event.target)) return;
    event.preventDefault();
    api.show_system_menu(Math.round(event.screenX), Math.round(event.screenY));
  });
  document.querySelectorAll('.window-resize-handle').forEach(handle => {
    handle.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      event.preventDefault();
      api.begin_resize(handle.dataset.edge);
    });
  });
  let sizingTimer;
  let sizingBusy = false;
  let sizingPending = false;
  const fitWorkspace = async () => {
    if (typeof api.fit_workspace !== 'function') return;
    if (sizingBusy) { sizingPending = true; return; }
    sizingBusy = true;
    try {
      //Measure unscaled controls so font changes and longer labels raise the floor.
      const fit = Number(document.body.style.getPropertyValue('--desktop-fit')) || 1;
      const rowWidth = row => row && !row.hidden && row.getBoundingClientRect().width
        ? [...row.children].filter(el => getComputedStyle(el).display !== 'none').reduce((sum, el) => {
            return sum + el.getBoundingClientRect().width / fit;
          }, 0) + Math.max(0, row.children.length - 1) * (parseFloat(getComputedStyle(row).gap) || 0) + 24 : 0;
      const width = Math.ceil(Math.max(1160, rowWidth(header), rowWidth(document.querySelector('.cfg-header'))));
      const limits = await api.fit_workspace(width, 740);
      const next = Math.min(1, Number(limits.fit) || 1);
      document.body.style.setProperty('--desktop-fit', next);
      document.body.style.zoom = String(next);
    } catch (error) { /*Keep native startup limits if the bridge is unavailable.*/ }
    finally {
      sizingBusy = false;
      if (sizingPending) { sizingPending = false; scheduleSizing(); }
    }
  };
  const scheduleSizing = () => { clearTimeout(sizingTimer); sizingTimer = setTimeout(fitWorkspace, 100); };
  window.addEventListener('resize', scheduleSizing);
  window.addEventListener('focus', scheduleSizing);
  window.addEventListener('workshop-page', scheduleSizing);
  new MutationObserver(scheduleSizing).observe(document.body, {attributes:true, attributeFilter:['class']});
  document.fonts.ready.then(scheduleSizing);
  scheduleSizing();
  window.addEventListener('resize', () => setTimeout(refreshWindowState, 80));
  window.addEventListener('focus', refreshWindowState);
  window.addEventListener('keydown', event => {
    if (event.key === 'F11') {
      event.preventDefault();
      if (event.ctrlKey) {
        api.toggle_fullscreen();
      } else {
        toggleMaximize();
      }
    }
  });
  refreshWindowState();
}
window.addEventListener('pywebviewready', setupDesktopChrome);
if (window.pywebview && window.pywebview.api) setupDesktopChrome();

//冰翼取用精灵一键打开
(function bindPickerLauncher() {
  const buttons = Array.from(document.querySelectorAll('#open-picker, [data-open-picker]'));
  if (!buttons.length) return;
  buttons.forEach(btn => {
    btn.onclick = async () => {
      const status = document.getElementById(btn.dataset.status || 'picker-status');
      if (status) status.textContent = '正在召唤冰翼取用精灵…';
      try {
        const resp = await fetch('/api/picker/open', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
        });
        const data = await resp.json();
        if (status) {
          status.textContent = data.ok
            ? (data.mode === 'fallback'
              ? '已打开兼容取用窗；本机缺少冰翼取用精灵组件，安装完整版后即可使用新界面'
              : '冰翼取用精灵已打开：点「立绘总览」可查看全部立绘')
            : `打开失败：${data.error || '未知错误'}`;
        }
      } catch (error) {
        if (status) status.textContent = '打开失败：本地服务未响应';
      }
    };
  });
})();

//立绘库：手动导入本地图片
const MISSING_BOTH_TEXT =
  '作品名和角色名都是空的，你这是在玩我，还是在玩 Galgame？' +
  '你自己说说，你推的是哪部作品里的谁，一个都答不上来。' +
  '这工具不是给你囤图的。填了再回来。';
const MISSING_CHARACTER_TEXT =
  '作品名填了，角色名空着。' +
  '一个连角色名都懒得打的人，是「不认识」还是「无所谓」？' +
  '玩过 Galgame 的人，会记不住自己推的是谁吗？' +
  '这工具不是给你囤图的。填了再回来。';
const MISSING_GAME_TEXT =
  '角色名填了，作品名空着。' +
  '同一个角色在不同作品里的立绘会混成一锅，以后你搜出来自己都分不清哪个是哪个。' +
  '作品名填了再回来。';

(function bindLibraryImport() {
  const openBtn = $('library-import');
  if (!openBtn) return;
  const dialog = $('import-dialog');
  const results = $('import-results');
  const status = $('import-status');
  const forceRow = $('import-force-row');
  const forceBtn = $('import-force');
  let lastWarningPaths = [];

  const STATUS_TEXT = {
    imported: '已导入',
    duplicate: '库里已有',
    warning: '需要确认',
    rejected: '已拒绝',
  };
  const STATUS_ICON = { imported: '✅', duplicate: '🔁', warning: '⚠️', rejected: '⛔' };

  function renderResults(summary, force) {    const rows = summary.results || [];
    results.innerHTML = rows.map(r => {
      const icon = STATUS_ICON[r.status] || '•';
      const size = r.width ? ` （${r.width}×${r.height}）` : '';
      const label = STATUS_TEXT[r.status] || r.status;
      return `<p class="import-row import-${r.status}">${icon} <strong>${escapeHtml(r.name)}</strong>` +
        `<span class="import-kind">${label}</span>${escapeHtml(size)}<br><span class="import-reason">${escapeHtml(r.reason || '')}</span></p>`;
    }).join('');
    results.hidden = false;
    status.textContent = `成功 ${summary.imported || 0}，重复 ${summary.duplicate || 0}，` +
      `需确认 ${summary.warning || 0}，拒绝 ${summary.rejected || 0}`;

    //只有「可争议」的（警告，或已解码但透明特征不达标）才给强制入口；
    //音频/损坏/超限没有 metrics，force 也救不了，所以按钮不出现。
    lastWarningPaths = rows.filter(r =>
      r.status === 'warning' || (r.status === 'rejected' && r.metrics && Object.keys(r.metrics).length)
    ).map(r => r.path).filter(Boolean);
    //commit 的结果里不一定带 path，用名字兜底匹配不上时就不显示强制按钮
    forceRow.hidden = force || lastWarningPaths.length === 0;

    try { resetLibraryView(); loadLibrary(true); } catch (e) { /*图库刷新失败不影响导入结果展示*/ }
  }

  async function commit(paths, force) {
    const gameInput = $('import-game');
    const characterInput = $('import-character');
    const gameValue = (gameInput?.value || '').trim();
    const characterValue = (characterInput?.value || '').trim();
    if (!gameValue || !characterValue) {
      status.textContent = !gameValue && !characterValue
        ? MISSING_BOTH_TEXT
        : (!characterValue ? MISSING_CHARACTER_TEXT : MISSING_GAME_TEXT);
      status.classList.add('import-refusal');
      (!gameValue ? gameInput : characterInput)?.focus();
      return;
    }
    status.classList.remove('import-refusal');
    status.textContent = force ? '正在强制导入…' : '正在校验并导入…';
    try {
      const resp = await fetch('/api/library/import-commit', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          paths,
          game: gameValue,
          character: characterValue,
          //将标签字符串规整为列表后提交。
          tags: $('import-tags').value.split(/[,，]/).map(value => value.trim()).filter(Boolean),
          force: !!force,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) { status.textContent = `导入失败：${data.error || resp.status}`; return; }
      renderResults(data, !!force);
      //导入成功后重置筛选，使新增作品与角色立即可见。
      if (data.imported > 0) {
        clearLibraryFilters();
        status.textContent += ' ｜ 已切到「全部作品 / 全部角色」，方便你确认新导入的图。';
      }
      resetLibraryView();
    } catch (e) {
      status.textContent = '导入失败：本地服务未响应';
    }
  }

  //补齐必填项后清除对应的错误提示。
  function syncImportGate() {
    const ready = Boolean(($('import-game')?.value || '').trim())
      && Boolean(($('import-character')?.value || '').trim());
    if (ready && status.classList.contains('import-refusal')) {
      status.classList.remove('import-refusal');
      status.textContent = '';
    }
  }
  for (const id of ['import-game', 'import-character']) {
    const input = $(id);
    if (input) input.addEventListener('input', syncImportGate);
  }

  openBtn.onclick = () => {
    results.hidden = true;
    results.innerHTML = '';
    forceRow.hidden = true;
    status.textContent = '';
    status.classList.remove('import-refusal');
    dialog.showModal();
  };
  $('close-import').onclick = () => dialog.close();
  $('import-pick').onclick = async () => {
    status.textContent = '正在打开文件选择框…';
    try {
      const resp = await fetch('/api/library/import-pick', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      });
      const data = await resp.json();
      const paths = data.paths || [];
      if (!paths.length) { status.textContent = '没有选择文件'; return; }
      commit(paths, false);
    } catch (e) {
      status.textContent = '打开文件选择框失败';
    }
  };
  forceBtn.onclick = () => {
    if (!lastWarningPaths.length) return;
    commit(lastWarningPaths, true);
  };
})();

//窗口先出现，扫描在后台跑，进度来自 /api/boot 的真实计数。
const BOOT_LINES = [
  '让我先醒一醒……',
  '正在把立绘一张张理出来',
  '本地服务开好了',
  '好啦，进来吧～',
];
const BOOT_PORTRAITS = [
  'boot-01-default.png',
  'boot-02-searching.png',
  'boot-03-ready.png',
  'boot-04-done.png',
];
//加载页最短展示时长（避免一闪而过）。
const BOOT_MIN_VISIBLE_MS = 1200;

let appBooted = false;
let bootStartedAt = 0;
let bootPollTimer = null;

function bootElapsed() { return performance.now() - bootStartedAt; }

function paintBoot(state, responseMs) {
  const overlay = $('boot-overlay');
  const phase = Math.max(0, Math.min(3, Number(state.phase) || 0));
  $('boot-line').textContent = BOOT_LINES[phase];
  const image = $('boot-portrait-image');
  const wanted = `/ui/loading/${BOOT_PORTRAITS[phase]}`;
  if (!image.src.includes(BOOT_PORTRAITS[phase])) image.src = wanted;
  const total = Number(state.total) || 0;
  const done = Number(state.done) || 0;
  const ratio = total > 0 ? Math.min(1, done / total) : (state.ready ? 1 : 0.08);
  $('boot-bar-fill').style.width = `${Math.round(ratio * 100)}%`;
  $('boot-detail').textContent = state.error
    ? state.error
    : (total > 0 ? `已理出 ${done} / ${total}` : '正在发现素材目录…');
  if (overlay.hidden) overlay.hidden = false;
}

function finishBoot() {
  const overlay = $('boot-overlay');
  if (overlay.hidden) return;
  overlay.classList.add('boot-leaving');
  setTimeout(() => { overlay.hidden = true; overlay.classList.remove('boot-leaving'); }, 300);
}

async function pollBoot() {
  const started = performance.now();
  let state = {};
  try {
    const response = await fetch('/api/boot', { cache: 'no-store' });
    state = await response.json();
  } catch (error) {
    //服务还没起来：保持加载页，继续轮询
    state = { ready: false, phase: 0 };
  }
  const responseMs = performance.now() - started;

  if (!state.ready) {
    paintBoot(state, responseMs);
    bootPollTimer = setTimeout(pollBoot, 180);
    return;
  }

  //素材就绪后完成初始化并撤下加载页。
  paintBoot({ ...state, phase: 3, ready: true }, responseMs);
  $('boot-bar-fill').style.width = '100%';
  const wait = Math.max(0, BOOT_MIN_VISIBLE_MS - bootElapsed());
  setTimeout(async () => { await bootstrapApp(); finishBoot(); }, wait + 320);
}

//素材就绪后加载目录与设置，避免初始化读取空数据。
async function bootstrapApp() {
  if (appBooted) return;
  appBooted = true;
  try {
    parseCustomQueue();
    await loadCatalog();
    await loadBrand();
    await loadSettings();
  } catch (error) {
    setStatus('初始化失败：' + error.message);
  }
}

function startBootSequence() {
  bootStartedAt = performance.now();
  bootPollTimer = setTimeout(pollBoot, 0);
}

//重新扫描素材
(function bindRescan() {
  const button = $('rescan-assets');
  if (!button) return;
  const status = $('rescan-status');
  button.onclick = async () => {
    if (!confirm('重新扫描素材需要重启程序。\n\n现在重启吗？')) return;
    button.disabled = true;
    status.textContent = '正在清除扫描缓存…';
    try {
      const resp = await fetch('/api/rescan', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      });
      //不假设响应一定是 JSON：文本/HTML 错误页也要能读出状态码（这个教训吃过一次）。
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        status.textContent = `清除失败：${data.error || resp.status}`;
        button.disabled = false;
        return;
      }
      status.textContent = data.cleared
        ? '已清除扫描缓存，正在重启程序…'
        : '缓存本来就不存在，正在重启程序…';
    } catch (e) {
      status.textContent = '清除失败：本地服务未响应';
      button.disabled = false;
    }
  };
})();

//把 startup.log（含请求级日志）、扫描摘要、设置、环境与统计打成一个 zip。
(function bindDiagnosticsExport() {
  const button = $('export-diagnostics');
  if (!button) return;
  const status = $('diagnostics-status');
  button.onclick = async () => {
    button.disabled = true;
    status.textContent = '正在打包…';
    try {
      const response = await fetch('/api/diagnostics/export', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `导出失败（${response.status}）`);
      const kb = Math.max(1, Math.round((data.size || 0) / 1024));
      status.textContent = `已导出：${data.path}（${kb} KB）`;
    } catch (error) {
      status.textContent = '导出失败：' + error.message;
    } finally {
      button.disabled = false;
    }
  };
})();
//运行体检
(function bindDiagnostics() {
  const button = $('run-diagnostics');
  if (!button) return;
  const list = $('diagnostics-list');
  const summary = $('diagnostics-summary');

  button.onclick = async () => {
    button.disabled = true;
    summary.textContent = '正在检查…';
    try {
      const resp = await fetch('/api/diagnostics');
      const data = await resp.json();
      if (!resp.ok) { summary.textContent = `体检失败：${data.error || resp.status}`; return; }
      const rows = (data.checks || []).map(item =>
        `<p class="diagnostics-row ${item.ok ? 'is-ok' : 'is-bad'}">` +
        `<span class="diagnostics-mark">${item.ok ? '✅' : '⚠️'}</span>` +
        `<strong>${escapeHtml(item.label)}</strong>` +
        `<span class="diagnostics-detail">${escapeHtml(item.detail)}</span>` +
        (item.hint ? `<span class="diagnostics-hint">建议：${escapeHtml(item.hint)}</span>` : '') +
        '</p>').join('');
      list.innerHTML = rows;
      list.hidden = false;
      summary.textContent = data.hardProblems
        ? `发现 ${data.hardProblems} 项需要处理（版本：${data.version}）`
        : `一切正常（版本：${data.version}）`;
      diagnosticsSummary = summary.textContent;
      if (data.logPath) {
        logPath = data.logPath;
        if ($('log-path')) $('log-path').value = data.logPath;
      }
      refreshSettingsRowValues();
    } catch (e) {
      summary.textContent = '体检失败：本地服务未响应';
    } finally {
      button.disabled = false;
    }
  };
})();

bindSettingsExtensions();
initIceSelects();
//开始轮询启动状态，数据就绪后初始化界面。
startBootSequence();

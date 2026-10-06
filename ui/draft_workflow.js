/*Ordinary draft entry; legacy script data and listeners remain intact.*/
(() => {
  const $ = id => document.getElementById(id), root = $('roughcut-page');
  const editor = window.cutEditor;
  const tools = $('tools-page');
  tools.querySelector('.tools-heading p').textContent = '取用素材，或把图片、视频、音频和文字安排成剪映草稿。';
  const voiceEntry = $('open-localtts');
  voiceEntry.className = 'settings-row';
  voiceEntry.innerHTML = '<span class="settings-row-icon" aria-hidden="true">♫</span><span class="settings-row-copy"><strong>配音组件与声音</strong></span><span class="settings-row-arrow" aria-hidden="true">›</span>';
  const voiceGroup = document.createElement('section');
  voiceGroup.className = 'settings-group';
  voiceGroup.innerHTML = '<h3 class="settings-group-title">配音</h3><div class="settings-rows"></div>';
  voiceGroup.querySelector('div').append(voiceEntry);
  $('settings-list').append(voiceGroup);
  let page = 'workbench', backDestination = 'settings';
  window.addEventListener('workshop-page', event => {
    if (event.detail === 'localtts') {
      backDestination = page === 'roughcut' ? 'roughcut' : 'settings';
      $('tts-back').textContent = backDestination === 'roughcut' ? '返回草稿' : '返回设置';
    }
    page = event.detail;
  });
  $('tts-back').onclick = () => window.switchPage(backDestination);
  $('open-roughcut').querySelector('strong').textContent = '剪映草稿自动生成';
  $('open-roughcut').querySelector('small').textContent = '安排图片、视频、音频和文字，人物与配音按需添加';
  root.querySelector('.production-heading h2').textContent = '剪映草稿自动生成';
  root.querySelector('.production-heading h2').title = 'Galgame 视频草稿工作区';
  root.querySelector('.production-heading p').textContent = '图片 · 视频 · 音频 · 文字';
  $('cut-bg-tab').textContent = '图片 / 视频';
  $('cut-sprite-tab').textContent = '人物';
  $('cut-asset-search').placeholder = '搜索图片、视频或人物';
  const previewNote = $('cut-preview-note');
  if (previewNote) previewNote.textContent = '素材分轨可编辑，人物、文字和配音都可选。';
  $('editor-dialogue-tab').textContent = '音频';
  const textPanel = $('text-properties');
  textPanel.querySelector('p').textContent = '标题、说明和字幕可直接添加；选中文字后可切换到配音。';
  //Existing bulk/script workflows are retained only behind the legacy entry.
  $('text-bulk').hidden = true;
  const quickText = [...$('editor-timeline-actions').children].find(n => n.textContent === '批量文字');
  quickText.id = 'editor-add-text';
  quickText.textContent = '添加文字';
  quickText.onclick = () => { $('editor-text-tab').click(); $('text-single').click(); $('text-content')?.focus(); };
  $('studio-text').textContent = '文字';
  $('studio-text').onclick = () => { $('editor-text-tab').click(); };
  const originalNew = $('cut-new').onclick;
  $('cut-new').onclick = event => {
    originalNew(event);
    if (!editor.snapshot().scenes.length && !editor.snapshot().textClips.length) $('cut-name').value = '新草稿项目';
  };
  if ($('cut-name').value === '新粗剪项目') $('cut-name').value = '新草稿项目';

  const compat = document.createElement('details');
  compat.id = 'draft-legacy-tools';
  compat.className = 'production-panel';
  compat.hidden = true;
  compat.innerHTML = '<summary>旧项目兼容工具</summary><p>保留旧项目的台词表、计时和配音关联。需要重新铺轨时先查看影响，可另存副本并撤销。</p><div class="production-actions"></div>';
  $('studio-project-fields').append(compat);
  const legacyButton = $('studio-script');
  legacyButton.textContent = '旧项目台词与计时';
  compat.querySelector('.production-actions').append(legacyButton);
  compat.querySelector('.production-actions').append($('dialogue-arrange'), $('dialogue-scenes'));
  $('dialogue-fit').textContent = '延长画面至内容结束';
  const notice = document.createElement('div');
  notice.id = 'draft-legacy-notice';
  notice.className = 'action-note';
  notice.hidden = true;
  notice.innerHTML = '<span>此项目保留了旧台词与计时数据。</span> <button id="draft-open-legacy" type="button">打开兼容工具</button>';
  root.querySelector('.production-heading').after(notice);
  $('draft-open-legacy').onclick = () => window.cutScript.open();
  //Do not advertise new script imports in either ordinary or legacy editing.
  for (const id of ['script-import-file', 'script-import-paste', 'script-save-standalone']) $(id).hidden = true;
  const sync = () => {
    const p = editor.snapshot();
    const legacy = Boolean(p.scriptTiming || p.scriptBase || p.scriptBaseline || p.scriptPlan?.rows?.length);
    compat.hidden = notice.hidden = !legacy;
    if (!legacy) compat.open = false;
  };
  window.addEventListener('cut-rendered', sync);
  window.addEventListener('cut-project-loaded', sync);
  window.addEventListener('script-plan-rendered', sync);
  new MutationObserver(sync).observe($('script-rows'), {childList: true});
  sync();
})();

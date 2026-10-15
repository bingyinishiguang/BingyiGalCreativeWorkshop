/*Ordinary draft entry; legacy script data and listeners remain intact.*/
(() => {
  const $ = id => document.getElementById(id), root = $('roughcut-page');
  const editor = window.cutEditor;
  const tools = $('tools-page');
  tools.querySelector('.tools-heading p').textContent = '先选你要做的事，再按步骤准备素材。配音与模型可在需要时配置。';
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
  $('cut-bg-tab').textContent = '素材';
  $('cut-sprite-tab').textContent = '人物';
  $('cut-asset-search').placeholder = '搜索图片、视频或人物';
  const previewNote = $('cut-preview-note');
  if (previewNote) previewNote.textContent = '素材分轨可编辑，人物、文字和配音都可选。';
  $('editor-dialogue-tab').textContent = '音频';
  const textPanel = $('text-properties');
  textPanel.querySelector('p').textContent = '选中时间轴上的文字，在这里修改内容、时间和位置。';
  //Existing bulk/script workflows are retained only behind the legacy entry.
  $('text-bulk').hidden = true;
  const quickText = [...$('editor-timeline-actions').children].find(n => n.textContent === '批量文字');
  quickText.id = 'editor-add-text';
  quickText.textContent = '添加文字';
  quickText.onclick = () => { $('editor-text-tab').click(); $('text-single').click(); $('text-content')?.focus(); };
  $('studio-text').textContent = '文字';
  const textAssets = document.createElement('div');
  textAssets.id = 'studio-text-assets';
  textAssets.hidden = true;
  textAssets.innerHTML = '<article class="production-tile studio-text-card"><div class="studio-text-card-surface"><span class="studio-text-sample" aria-hidden="true">Aa<br><small>请输入文字</small></span><button id="studio-add-default-text" type="button" title="添加一条默认文字" aria-label="添加一条默认文字">＋</button></div><strong>默认文字</strong><small>从播放头开始 · 默认 3 秒</small></article>';
  const textImports = document.createElement('div');
  textImports.className = 'production-actions';
  $('text-single').hidden = true;
  textImports.append($('text-single'), $('text-bulk'), $('text-srt'));
  textPanel.querySelector('.production-actions').remove();
  textAssets.prepend(textImports);
  root.querySelector('.studio-material-scroll').append(textAssets);
  let textAssetsVisible = false;
  const showTextAssets = () => {
    editor.cancelAssetLoad?.();
    textAssetsVisible = true;
    for (const id of ['cut-bg-tab', 'cut-sprite-tab', 'cut-audio-tab', 'cut-preset-tab']) $(id).classList.remove('active');
    $('studio-text').classList.add('active');
    $('studio-local').classList.add('active');
    for (const id of ['cut-assets', 'cut-assets-more', 'editor-audio-assets', 'cut-presets', 'cut-asset-search', 'studio-import', 'cut-create-group', 'cut-asset-target-label']) $(id).hidden = true;
    $('cut-asset-hint').hidden = false;
    $('cut-asset-hint').textContent = '点默认文字右下角 ＋ 添加，再到右侧修改内容和时间。';
    textAssets.hidden = false;
    $('editor-text-tab').click();
  };
  $('studio-text').onclick = showTextAssets;
  $('studio-add-default-text').onclick = () => { $('editor-text-tab').click(); $('text-single').click(); $('text-content')?.focus(); };
  const originalLocal = $('studio-local').onclick;
  $('studio-local').onclick = event => { if (textAssetsVisible) showTextAssets(); else originalLocal(event); };
  for (const id of ['cut-bg-tab', 'cut-sprite-tab', 'cut-audio-tab', 'cut-preset-tab']) $(id).addEventListener('click', () => {
    textAssetsVisible = false;
    textAssets.hidden = true;
    $('studio-text').classList.remove('active');
  });
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
  $('draft-open-legacy').onclick = () => legacyButton.click();
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

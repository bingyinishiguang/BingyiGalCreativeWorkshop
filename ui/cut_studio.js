/*Workshop editing layout; existing project editors remain the source of truth.*/
(()=>{
  const $=id=>document.getElementById(id),root=$('roughcut-page'),editor=window.cutEditor;
  root.classList.add('cut-studio');
  const assets=root.querySelector('.editor-assets'),bar=assets.querySelector('.production-actions');
  const header=root.querySelector('.production-heading');
  header.classList.add('studio-header');header.querySelector('h2').textContent='Galgame 剧情草稿生成器';
  const title=header.querySelector('h2');title.title='Galgame 视频制作工作区';
  const settings=document.createElement('dialog');settings.id='studio-project-dialog';settings.className='studio-dialog';
  settings.innerHTML='<h3>项目设置</h3><div id="studio-project-fields"></div><button id="studio-project-close">完成</button>';
  settings.querySelector('div').append(root.querySelector(':scope > .production-filters'));
  settings.append(root.querySelector('.editor-directory-bar'));document.body.append(settings);
  $('studio-project-close').onclick=()=>settings.close();
  const projectButton=document.createElement('button');projectButton.id='studio-project-settings';projectButton.textContent='项目设置';projectButton.onclick=()=>settings.showModal();
  header.append(projectButton,$('cut-save'),$('cut-export'));
  $('cut-save').textContent='保存项目';$('cut-export').textContent='生成剪映草稿';
  header.querySelector('button[title="收起工坊顶栏，给剪辑区更多空间"]').hidden=true;
  const content=document.createElement('div');content.className='studio-material-content';
  const rail=document.createElement('nav');rail.className='studio-local-rail';rail.setAttribute('aria-label','素材来源');
  const local=document.createElement('button');local.id='studio-local';local.textContent='本地';local.className='active';
  const preset=$('cut-preset-tab');rail.append(local,preset);
  const tabs=document.createElement('div');tabs.className='studio-material-tabs';tabs.setAttribute('aria-label','素材分类');
  tabs.append($('cut-bg-tab'),$('cut-sprite-tab'),$('cut-audio-tab'));
  const text=document.createElement('button');text.id='studio-text';text.textContent='文本';text.onclick=()=>{$('editor-text-tab').click();$('text-bulk').click();};tabs.append(text);
  const toolrow=document.createElement('div');toolrow.className='studio-import-row';
  const importButton=document.createElement('button');importButton.id='studio-import';importButton.textContent='＋ 导入';
  const group=$('cut-create-group');toolrow.append(importButton,group);
  const scroller=document.createElement('div');scroller.className='studio-material-scroll';
  //Keep IDs and listeners intact when relocating controls.
  scroller.append($('cut-asset-hint'),$('cut-asset-target-label'),$('cut-assets'),$('cut-assets-more'),$('editor-audio-assets'),$('cut-presets'));
  content.append(toolrow,$('cut-asset-search'),scroller);
  const body=document.createElement('div');body.className='studio-material-body';body.append(rail,content);
  const extras=document.createElement('details');extras.className='studio-scene-tools';extras.innerHTML='<summary>镜头与节奏</summary>';
  extras.append(assets.querySelector('.editor-scene-list'),$('dialogue-gap').parentElement);
  assets.replaceChildren(tabs,body);$('editor-scene-properties').append(extras);
  bar.remove();
  let kind='background';
  const activateLocal=()=>{local.classList.add('active');preset.classList.remove('active');importButton.hidden=false;$('cut-asset-hint').hidden=false;$('cut-asset-target-label').hidden=kind!=='sprite';};
  local.onclick=()=>{$(kind==='sprite'?'cut-sprite-tab':kind==='audio'?'cut-audio-tab':'cut-bg-tab').click();};
  for(const [id,value] of [['cut-bg-tab','background'],['cut-sprite-tab','sprite'],['cut-audio-tab','audio']]){
    $(id).addEventListener('click',()=>{kind=value;activateLocal();});
  }
  preset.addEventListener('click',()=>{local.classList.remove('active');importButton.hidden=true;$('cut-asset-hint').hidden=true;$('cut-asset-target-label').hidden=true;});
  importButton.onclick=async()=>{
    importButton.disabled=true;
    try{
      if(kind==='sprite'){$('library-import').click();return;}
      if(kind==='audio'){
        const picked=await editor.api('/api/audio/pick',{});if(!picked.paths?.length)return;
        const result=await editor.api('/api/audio/import',{paths:picked.paths});
        await window.cutV2.loadAudio();$('cut-audio-tab').click();
        const failures=result.results.filter(r=>r.error);
        $('cut-status').textContent=failures.length?failures.map(r=>r.source+'：'+r.error).join('；'):'音频导入完成';return;
      }
      const picked=await editor.api('/api/backgrounds/pick',{});if(!picked.paths?.length)return;
      const result=await editor.api('/api/backgrounds/import',{paths:picked.paths});
      await editor.refreshAssets();
      const failures=result.results.filter(r=>r.error);
      $('cut-status').textContent=`已处理 ${result.results.length} 个背景素材`+(failures.length?'；'+failures.map(r=>r.source+'：'+r.error).join('；'):'');
    }catch(error){$('cut-status').textContent=error.message;}finally{importButton.disabled=false;}
  };
  $('import-dialog').addEventListener('close',()=>{if(!root.hidden&&kind==='sprite')editor.refreshAssets().catch(error=>$('cut-status').textContent=error.message);});
  $('editor-scene-tab').textContent='画面';$('editor-dialogue-tab').textContent='音频 / 对白';$('editor-subtitle-tab').textContent='字幕';
  const panelTitle=root.querySelector('.editor-panel-title');panelTitle.firstChild.textContent='播放器';
  const clock=document.createElement('output');clock.id='studio-clock';clock.textContent='00:00:00:00';clock.setAttribute('aria-label','播放时间');
  $('editor-preview-controls').prepend(clock);
  const updateClock=()=>{const fps=Number($('cut-fps').value),t=Number($('dialogue-preview-time').value)||0;const frames=Math.floor(t*fps+1e-5);const seconds=Math.floor(frames/fps);clock.textContent=[Math.floor(seconds/3600),Math.floor(seconds/60)%60,seconds%60,frames%fps].map(n=>String(n).padStart(2,'0')).join(':');};
  window.addEventListener('cut-rendered',updateClock);
  const fit=document.createElement('button');fit.id='studio-fit-timeline';fit.textContent='适应全片';fit.onclick=()=>{const s=editor.snapshot(),end=Math.max(1,s.scenes.reduce((t,c)=>t+c.duration,0),...(s.audioClips||[]).map(c=>c.start+c.duration),...(s.textClips||[]).map(c=>c.start+c.duration));const zoom=$('editor-zoom');zoom.value=Math.max(5,Math.min(120,($('editor-timeline-scroll').clientWidth-260)/end));zoom.dispatchEvent(new Event('input'));};$('editor-timeline-actions').append(fit);
  const activate=()=>{document.body.classList.toggle('studio-active',!root.hidden);requestAnimationFrame(()=>window.dispatchEvent(new Event('resize')));};
  window.addEventListener('workshop-page',activate);activate();
})();

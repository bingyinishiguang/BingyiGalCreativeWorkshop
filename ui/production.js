/*Background library and local rough-cut editor. No remote assets or services.*/
(() => {
  const el = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function api(path, body) {
    const response = await fetch(path, body === undefined ? {cache:'no-store'} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '操作失败');
    return data;
  }
  async function run(statusId, button, action) {
    if (button) button.disabled = true;
    try { await action(); } catch (error) { el(statusId).textContent = error.message; }
    finally { if (button) button.disabled = false; }
  }
  let backgrounds = [], bgSelection = new Set(), bgSelected = null, bgSerial = 0;
  let bgDetailRevision=0;const bgPendingSaves=new Set();
  window.workshopActivity ||= {};
  window.workshopActivity.backgroundLibrary=()=>bgPendingSaves.size>0;
  let allBackgrounds = [], sprites = [], spriteOffset = 0, spriteTotal = 0;
  let assetKind = 'background', assetSerial = 0, activeScene = -1, scenes = [], projectId = '', output = '';
  let cutInitialized = false, dirty = false, cutBusy = false, roleTarget = 0, visualTarget = 'background';
  let projectLoadSerial=0,projectRevision=0;
  let transformEdit = null;
  let cleanProjectName='新草稿项目';
  const hasUnsavedChanges=()=>dirty||Boolean(transformEdit)||el('cut-name').value!==cleanProjectName;
  const spriteSizes = new Map(), geometry = window.cutGeometry;
  const canvasSize = () => el('cut-canvas').value.split('x').map(Number);
  function transformFor(scene, actor=null) {
    const [w,h]=canvasSize(), info=actor?(actor.alignment||spriteSizes.get(spriteKey(actor))):background(scene.background);
    if(!info)return null;
    const key=actor?'transform':'backgroundTransform', target=actor||scene;
    return target[key] ||= geometry.defaults(w,h,info.width,info.height,actor);
  }
  const bgUrl = (id, thumb=false, trash=false) => `/api/backgrounds/${thumb?'thumb':'media'}?id=${encodeURIComponent(id)}${trash?'&trash=1':''}`;
  const spriteKey = actor => actor.id+JSON.stringify(actor.alignment||null);
  const spriteUrl = actor => '/api/roughcut/sprite?id=' + encodeURIComponent(actor.id)+(actor.alignment?'&alignment='+encodeURIComponent(JSON.stringify(actor.alignment)):'');
  const background = id => allBackgrounds.find(i => i.id === id) || backgrounds.find(i => i.id === id);
  const spriteName = id => { const s = sprites.find(i => i.id === id); return s?.displayName || s?.character || '已选立绘'; };
  const markDirty = () => { dirty = true; projectRevision++; el('cut-status').textContent = '项目有未保存的修改'; window.dispatchEvent(new Event('cut-changed')); };
  let assetViewing=false;
  function clearAssetView(){
    assetViewing=false;el('cut-preview').classList.remove('asset-previewing');
    el('cut-preview').querySelectorAll('video,audio').forEach(v=>v.pause());
    el('cut-assets').querySelectorAll('.asset-viewed').forEach(card=>{card.classList.remove('asset-viewed');card.querySelector('.asset-open')?.setAttribute('aria-pressed','false');});
  }
  function returnToTimeline(){if(!assetViewing)return;clearAssetView();renderPreview();window.cutText?.renderPreview();}
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&assetViewing)returnToTimeline();});
  document.addEventListener('pointerdown',event=>{if(event.target.closest('#editor-timeline-scroll'))returnToTimeline();},true);
  document.addEventListener('click',event=>{
    if(assetViewing&&event.target.closest('#dialogue-play,#dialogue-stop')){
      event.preventDefault();event.stopImmediatePropagation();const video=el('cut-preview').querySelector('video,audio');
      if(video){if(event.target.closest('#dialogue-stop'))video.pause();else if(video.paused)playAsset(video);else video.pause();}return;
    }
    if(event.target.closest('#editor-timeline-scroll'))returnToTimeline();
  },true);
  const assetTarget=document.createElement('label');assetTarget.id='cut-asset-target-label';assetTarget.hidden=true;
  assetTarget.innerHTML='立绘目标 <select id="cut-asset-target" aria-label="立绘添加或替换目标"><option value="0">角色 1</option><option value="1">角色 2</option></select>';
  el('cut-assets').before(assetTarget);
  el('cut-asset-target').onchange=event=>chooseRole(Number(event.target.value));
  function playAsset(media){media.play().catch(error=>{if(!media.isConnected||error.name==='AbortError')return;el('cut-status').textContent=error.name==='NotAllowedError'?'未能自动播放，请点击预览区的播放按钮。':'素材播放失败，请检查音频或视频文件。';});}
  function showAsset(item,kind){
    window.cutV2?.stopPlayback?.();clearAssetView();assetViewing=true;
    el('cut-assets').querySelectorAll('.production-tile').forEach(card=>{const selected=card.dataset.assetId===item.id;card.classList.toggle('asset-viewed',selected);card.querySelector('.asset-open')?.setAttribute('aria-pressed',String(selected));});
    const name=kind==='sprite'?(item.displayName||item.character||'立绘'):item.name;
    const media=document.createElement(kind==='audio'?'audio':kind==='background'&&item.kind==='video'?'video':'img');
    media.src=kind==='audio'?'/api/audio/media?id='+encodeURIComponent(item.id):kind==='sprite'?'/api/library/image?id='+encodeURIComponent(item.id):bgUrl(item.id);
    media.alt=name;media.className='asset-preview-media';if(['VIDEO','AUDIO'].includes(media.tagName)){media.controls=true;media.preload='metadata';}
    media.addEventListener('error',()=>{if(media.isConnected&&assetViewing)el('cut-status').textContent='素材「'+name+'」无法预览，请检查文件或重新导入。';});
    const bar=document.createElement('div');bar.className='asset-preview-bar';
    const title=document.createElement('span');title.textContent='素材预览 · '+name;
    bar.append(title);const preview=el('cut-preview');preview.classList.add('asset-previewing');preview.replaceChildren(media,bar);
    if(['VIDEO','AUDIO'].includes(media.tagName)){media.autoplay=true;playAsset(media);}
  }
  function updateAssetActions(){
    const scene=scenes[activeScene];el('cut-asset-target').value=String(roleTarget);
    const hint=el('cut-asset-hint'),scroller=hint.closest('.studio-material-scroll');
    if(scroller)scroller.before(hint,assetTarget);
    const spriteTab=el('cut-sprite-tab').classList.contains('active');assetTarget.hidden=!spriteTab;
    const occupied=scene?.actors.some(a=>(a.slot||0)===roleTarget),otherSlot=roleTarget===0?1:0;
    if(spriteTab){
      el('cut-asset-hint').textContent=!scene?'加号暂不可用：先到「素材」添加图片或视频镜头，再添加人物。':scene.blank?'加号暂不可用：当前是背景空隙，请先添加背景或选择有背景的镜头。':occupied?`加号暂不可用：角色 ${roleTarget+1} 已有立绘，请用下方「替换角色 ${roleTarget+1}」更换。${scene.actors.some(a=>(a.slot||0)===otherSlot)?'两个角色位置都已占用。':`添加另一人物时，将立绘目标改为角色 ${otherSlot+1}。`}`:`右下角 ＋ 添加到角色 ${roleTarget+1}；点击图片只预览，不修改当前镜头。`;
    }else if(el('cut-bg-tab').classList.contains('active'))el('cut-asset-hint').textContent='点击图片 / 视频只预览；点右下角 ＋ 添加一个背景镜头。';
    el('cut-assets').querySelectorAll('[data-add-asset],[data-replace-asset]').forEach(button=>{
      const card=button.closest('.production-tile'),sprite=card.dataset.assetKind==='sprite',occupied=scene?.actors.some(a=>(a.slot||0)===roleTarget),replace=button.hasAttribute('data-replace-asset');
      const actionLabel=sprite?`${replace?'替换':'添加'}角色 ${roleTarget+1}`:'添加到轨道';
      button.textContent=replace?actionLabel:'＋';
      button.disabled=card.dataset.missing==='true'||(sprite&&scene?.blank)||(replace?(!scene||(sprite&&!occupied)):(sprite&&(!scene||occupied)));
      button.title=card.dataset.missing==='true'?'素材文件丢失，请先重新导入或恢复文件':!sprite?'添加到轨道':!scene?'请先添加背景镜头':scene.blank?'当前是背景空隙，请选择有背景的镜头':occupied&&!replace?`角色 ${roleTarget+1} 已有立绘，请使用下方替换按钮`:replace&&!occupied?`角色 ${roleTarget+1} 还没有立绘，请点右下角 ＋ 添加`:actionLabel;
      button.setAttribute('aria-label',actionLabel);
      if(sprite&&!replace){
        const reason=card.querySelector('.asset-add-reason');
        reason.hidden=!button.disabled;
        reason.textContent=card.dataset.missing==='true'?'素材文件丢失，请重新导入':!scene?'先添加背景镜头':scene.blank?'先添加背景或选择有背景的镜头':occupied?`角色 ${roleTarget+1} 已有立绘，请用替换`:'';
        if(button.disabled)button.setAttribute('aria-describedby',reason.id);else button.removeAttribute('aria-describedby');
      }
    });
  }
  function applyAsset(item,kind,replace){
    if(cutBusy||item.missing)return;finishTransformEdit();
    if(kind==='background'){
      const gap=scenes[activeScene];
      if(gap?.blank){
        const added=newScene(item.id),fps=Number(el('cut-fps').value)||30;
        added.duration=Math.min(added.duration,gap.duration,item.kind==='video'?item.duration:Infinity);
        const remaining=Math.round((gap.duration-added.duration)*fps)/fps;
        scenes.splice(activeScene,1,added,...(remaining>0?[{...gap,duration:remaining}]:[]));
      }else{const next=activeScene+1;scenes.splice(next,0,newScene(item.id));activeScene=next;}
      visualTarget='background';
    }else{
      const scene=scenes[activeScene];if(!scene){el('cut-status').textContent='请先添加背景镜头';return;}
      if(scene.blank){el('cut-status').textContent='当前是背景空隙；请选择有背景的镜头再添加角色。';return;}
      const ix=scene.actors.findIndex(a=>(a.slot||0)===roleTarget);
      if((replace&&ix<0)||(!replace&&ix>=0))return;
      const actor=geometry.replaceActor(scene.actors[ix],item.id,roleTarget,scene.actors.some(a=>(a.slot||0)!==roleTarget));
      window.cutComposition?.replaceAlignment(actor,item.id);if(ix>=0)scene.actors[ix]=actor;else scene.actors.push(actor);
      scene.actors.sort((a,b)=>(a.slot||0)-(b.slot||0));visualTarget=String(roleTarget);
    }
    markDirty();renderCut();notifyVisualSelection();
  }
  function notifyVisualSelection(){window.dispatchEvent(new CustomEvent('cut-visual-selected',{detail:{index:activeScene,kind:visualTarget==='background'?'background':'actor',slot:visualTarget==='background'?null:Number(visualTarget)}}));}
  function selectVisual(target){returnToTimeline();finishTransformEdit();visualTarget=String(target);if(target!=='background')roleTarget=Number(target);renderEditor();refreshVisualStyles();updateAssetActions();notifyVisualSelection();}
  function chooseRole(slot){finishTransformEdit();roleTarget=slot;if(scenes[activeScene]?.actors.some(a=>(a.slot||0)===slot))selectVisual(slot);else{if(el('cut-role-target'))el('cut-role-target').value=String(slot);updateAssetActions();}}
  function finishTransformEdit(commit=true){
    if(!transformEdit)return;const edit=transformEdit;transformEdit=null;
    if(!commit||!edit.input.value.trim()||!edit.input.checkValidity())Object.assign(edit.transform,edit.before);
    const changed=JSON.stringify(edit.before)!==JSON.stringify(edit.transform);
    if(changed)markDirty();
    refreshVisualStyles();
    if(!commit||!changed)edit.input.value=edit.display;
  }
  function refreshVisualStyles(){
    const scene=scenes[activeScene];if(!scene)return;const [w,h]=canvasSize();
    el('cut-preview').querySelectorAll('[data-visual-target]').forEach(media=>{
      const actor=media.dataset.visualTarget==='background'?null:scene.actors.find(a=>String(a.slot||0)===media.dataset.visualTarget);
      const size=actor?(actor.alignment||spriteSizes.get(spriteKey(actor))):background(scene.background),t=transformFor(scene,actor);
      if(size&&t)Object.assign(media.style,geometry.style(w,h,size.width,size.height,t));
      media.classList.toggle('visual-selected',media.dataset.visualTarget===visualTarget);
    });
  }

  function tile(item, isSprite=false, selectable=false) {
    const card = document.createElement('div');
    card.className = 'production-tile';
    if (bgSelection.has(item.id)) card.classList.add('is-selected');
    const url = isSprite ? `/api/library/image?id=${encodeURIComponent(item.id)}&thumb=1` : bgUrl(item.id,true,el('bg-trash-view').checked);
    card.innerHTML = `<button class="asset-open" type="button"${item.missing?' disabled':''}>${!isSprite && !item.thumbnail ? '<span class="tile-placeholder">▷</span>' : `<img src="${url}" loading="lazy" alt="">`}<strong>${escape(isSprite ? item.displayName || item.character : item.name)}</strong><small>${item.missing?'文件丢失':isSprite ? escape(item.game || '立绘') : `${item.kind==='video'?'视频 '+item.duration.toFixed(1)+' 秒':'图片'} · ${item.width} × ${item.height}`}</small></button>`;
    if (selectable && !item.missing) {
      const check = document.createElement('input'); check.type='checkbox'; check.checked=bgSelection.has(item.id);
      check.setAttribute('aria-label','选择 '+item.name);
      check.onchange = () => { if (check.checked) bgSelection.add(item.id); else bgSelection.delete(item.id); card.classList.toggle('is-selected',check.checked); };
      card.append(check);
    }
    if(isSprite) {
      const rename=document.createElement('button');rename.type='button';rename.textContent='改名';
      rename.onclick=()=>run('cut-status',rename,async()=>{
        const name=window.prompt('立绘显示名称',item.displayName||[item.character,item.body,item.face].filter(Boolean).join('_'));
        if(name===null||!name.trim())return;
        await api('/api/roughcut/rename-sprite',{id:item.id,name});await loadAssets();renderCut();
      });card.append(rename);
    }
    return card;
  }

  async function loadBackgrounds() {
    const serial = ++bgSerial;
    const params = new URLSearchParams({search:el('bg-search').value, kind:el('bg-kind').value, favorite:el('bg-favorite').checked?'1':'0', trash:el('bg-trash-view').checked?'1':'0'});
    const data = await api('/api/backgrounds?' + params);
    if (serial !== bgSerial) return;
    backgrounds = data.items;
    const grid = el('bg-grid'); grid.replaceChildren();
    el('bg-count').textContent = `${data.total} 个素材`;
    el('bg-to-cut').disabled = el('bg-trash-view').checked;
    if (!backgrounds.length) grid.textContent = el('bg-trash-view').checked ? '回收站是空的。' : '导入场景图片或视频，开始建立背景库。';
    for (const item of backgrounds) {
      const card = tile(item,false,!el('bg-trash-view').checked);
      card.querySelector('button').onclick = () => showBackground(item);
      grid.append(card);
    }
  }
  function showBackground(item) {
    clearBgDetail();
    bgSelected = item;
    const trash = el('bg-trash-view').checked;
    el('bg-detail').innerHTML = `<h3>${escape(item.name)}</h3>${item.kind==='video' ? `<video src="${bgUrl(item.id,false,trash)}" controls preload="metadata"></video>` : `<img src="${bgUrl(item.id,false,trash)}" alt="${escape(item.name)}">`}<p>${item.width} × ${item.height}${item.kind==='video'?' · '+item.duration.toFixed(2)+' 秒':''}</p>${trash ? '<button id="bg-restore" type="button">恢复背景</button>' : `<label>名称<input id="bg-edit-name" value="${escape(item.name)}" maxlength="200"></label><label>标签（逗号分隔）<input id="bg-edit-tags" value="${escape(item.tags.join(', '))}"></label><label><input id="bg-edit-favorite" type="checkbox" ${item.favorite?'checked':''}>收藏</label><div class="production-actions"><button id="bg-edit-save" type="button">保存资料</button><button id="bg-use" type="button">加入粗剪</button><button id="bg-trash" type="button">移入回收站</button></div>`}`;
    if (trash) el('bg-restore').onclick = () => run('bg-status',el('bg-restore'),async () => {
      await api('/api/backgrounds/restore',{id:item.id}); el('bg-status').textContent='已恢复背景'; if(bgSelected?.id===item.id)clearBgDetail(); await loadBackgrounds();
    });
    else {
      el('bg-detail').querySelectorAll('input').forEach(input=>input.addEventListener('input',()=>bgDetailRevision++));
      el('bg-edit-save').disabled=bgPendingSaves.has(item.id);
      el('bg-edit-save').onclick = () => run('bg-status',el('bg-edit-save'),async () => {
        if(bgPendingSaves.has(item.id))return;
        const revision=bgDetailRevision,values={id:item.id,name:el('bg-edit-name').value,tags:el('bg-edit-tags').value,favorite:el('bg-edit-favorite').checked};
        bgPendingSaves.add(item.id);el('bg-status').textContent='正在保存背景资料…';
        try{
          const updated=await api('/api/backgrounds/update',values);let warning='';try{await loadBackgrounds();}catch(error){warning=' 列表暂未刷新：'+error.message;}
          const unchanged=bgSelected?.id===item.id&&bgDetailRevision===revision;
          if(unchanged)showBackground(updated);
          el('bg-status').textContent=(bgSelected?.id===item.id&&!unchanged?'背景资料已保存；之后的修改仍待保存。':'背景「'+updated.name+'」的名称、标签与收藏已保存')+warning;
        }finally{bgPendingSaves.delete(item.id);if(el('bg-edit-save'))el('bg-edit-save').disabled=bgPendingSaves.has(bgSelected?.id);}
      });
      el('bg-trash').onclick = () => run('bg-status',el('bg-trash'),async () => {
        await api('/api/backgrounds/trash',{id:item.id}); bgSelection.delete(item.id); if(bgSelected?.id===item.id)clearBgDetail(); await loadBackgrounds(); el('bg-status').textContent='已移入回收站，之后可恢复';
      });
      el('bg-use').onclick = () => enterWithBackgrounds([item.id]);
    }
  }
  function clearBgDetail() { el('bg-detail').querySelectorAll('video,audio').forEach(media=>media.pause());bgDetailRevision++;bgSelected=null; el('bg-detail').innerHTML='<p>选择背景查看预览、名称与标签。</p>'; }
  async function importBackgrounds(folder=false) {
    const button=el(folder?'bg-import-folder':'bg-import');
    await run('bg-status',button,async () => {
      let payload;
      if (folder) {
        const picked = await api('/api/settings/choose-folder',{});
        if (!picked.path) return;
        payload={folder:picked.path};
      } else {
        const picked=await api('/api/backgrounds/pick',{});
        if (!picked.paths.length) return;
        payload={paths:picked.paths};
      }
      el('bg-status').textContent='正在复制素材并制作预览…';
      const data=await api('/api/backgrounds/import',payload);
      const failed=data.results.filter(i=>i.error), duplicates=data.results.filter(i=>i.duplicate);
      el('bg-status').textContent=`已导入 ${data.results.length-failed.length-duplicates.length} 个，已有 ${duplicates.length} 个，失败 ${failed.length} 个。` + failed.map(i=>`${i.source}：${i.error}`).join('；');
      el('bg-trash-view').checked=false; await loadBackgrounds();
    });
  }
  async function enterWithBackgrounds(ids) {
    if (cutBusy) { el('bg-status').textContent='粗剪项目正在保存或生成，请完成后再加入素材'; return; }
    await run('bg-status',null,async () => {
      await initializeCut();
      const data=await api('/api/backgrounds'); allBackgrounds=data.items;
      for (const id of ids) {
        const item=background(id); if (item && !item.missing) scenes.push(newScene(id));
      }
      activeScene=scenes.length-1; markDirty(); renderCut(); switchPage('roughcut');
    });
  }
  function newScene(id) { return {background:id,duration:Number(el('cut-batch-duration').value)||4,videoStart:0,restart:false,loop:false,actors:activeScene>=0?structuredClone(scenes[activeScene].actors):[]}; }
  function ensureCoverage(end){
    const fps=Number(el('cut-fps').value)||30;
    if(!Number.isFinite(end)||end<=0||end>10800)return;
    let remaining=Math.ceil(end*fps-1e-7)-scenes.reduce((sum,s)=>sum+Math.round(s.duration*fps),0);
    if(remaining<=0)return;
    const last=scenes.at(-1),info=last?background(last.background):null;
    const canExtend=last&&(last.blank||info?.kind==='image'||(info?.kind==='video'&&last.loop));
    const available=canExtend?Math.max(0,3600*fps-Math.round(last.duration*fps)):0;
    if(scenes.length+Math.ceil(Math.max(0,remaining-available)/(3600*fps))>500)return;
    if(canExtend){const amount=Math.min(remaining,available);last.duration=(Math.round(last.duration*fps)+amount)/fps;remaining-=amount;}
    while(remaining>0){const frames=Math.min(remaining,3600*fps);scenes.push({blank:true,background:'',duration:frames/fps,videoStart:0,restart:true,loop:false,actors:[]});remaining-=frames;}
    if(activeScene<0)activeScene=0;
  }
  async function initializeCut() {
    if (!cutInitialized) {
      const options=await api('/api/roughcut/options'); el('cut-directory').value=options.draftDirectory;el('cut-material-directory').value=options.materialDirectory||'';
      cutInitialized=true;
    }
    await refreshProjects(); await loadAssets();
  }
  async function refreshProjects() {
    const data=await api('/api/roughcut/projects');
    el('cut-projects').innerHTML='<option value="">打开已保存项目…</option>' + data.items.map(i=>`<option value="${i.id}">${escape(i.name)} · ${escape(i.updated)}</option>`).join('');
    el('cut-projects').value=data.items.some(i=>i.id===projectId)?projectId:'';
  }
  async function loadAssets(more=false) {
    const serial=++assetSerial;
    const loadedKind=assetKind;
    const search=el('cut-asset-search').value;
    if (!more) spriteOffset=0;
    const data=await api(loadedKind==='background'?'/api/backgrounds?'+new URLSearchParams({search}):'/api/roughcut/sprites?'+new URLSearchParams({search,offset:String(spriteOffset)}));
    if (serial!==assetSerial) return;
    el('cut-bg-tab').classList.toggle('active',assetKind==='background'); el('cut-sprite-tab').classList.toggle('active',assetKind==='sprite');
    if (assetKind==='background') {
      //Preserve full metadata for already selected scenes while filtering the visible asset list.
      for (const item of data.items) { const ix=allBackgrounds.findIndex(i=>i.id===item.id); if (ix>=0) allBackgrounds[ix]=item; else allBackgrounds.push(item); }
    } else { sprites=more ? [...sprites,...data.items] : data.items; spriteTotal=data.total; }
    const grid=el('cut-assets'); if (!more) grid.replaceChildren();
    if (!data.items.length && !more) grid.textContent=assetKind==='background'?'背景库还没有匹配素材，请先导入。':'没有匹配的普通立绘，请先保存到立绘库。';
    for (const item of data.items) {
      const card=tile(item,loadedKind==='sprite');
      card.dataset.assetId=item.id;card.dataset.assetKind=loadedKind;card.dataset.missing=String(Boolean(item.missing));
      card.querySelector('.asset-open').onclick=()=>showAsset(item,loadedKind);
      const actions=document.createElement('div');actions.className='asset-edit-actions';
      for(const replace of (loadedKind==='background'?[false]:[false,true])){const button=document.createElement('button');button.type='button';button.setAttribute(replace?'data-replace-asset':'data-add-asset',item.id);button.onclick=()=>applyAsset(item,loadedKind,replace);actions.append(button);}
      const surface=document.createElement('div');surface.className='asset-preview-surface';surface.append(card.querySelector('.asset-open'),actions.firstChild);card.prepend(surface);
      if(loadedKind==='sprite'){
        card.append(actions);
        const reason=document.createElement('small');reason.className='asset-add-reason';reason.id='sprite-add-reason-'+item.id;reason.hidden=true;card.append(reason);
      }
      grid.append(card);
    }
    el('cut-assets-more').hidden=assetKind!=='sprite'||sprites.length>=spriteTotal;
    spriteOffset=sprites.length;window.cutComposition?.decorateAssets(grid,sprites);updateAssetActions();
  }
  function renderCut() {
    finishTransformEdit();
    const list=el('cut-scenes'); list.replaceChildren(); let time=0;
    scenes.forEach((scene,index)=> {
      const bg=background(scene.background), button=document.createElement('button');
      button.className='cut-scene'+(index===activeScene?' active':''); button.type='button';
      button.innerHTML=`${bg?.thumbnail?`<img src="${bgUrl(bg.id,true)}" alt="">`:''}<span class="scene-copy"><strong>${index+1}. ${escape(scene.blank?'空隙（背景空白）':bg?.name||'背景已失效')}</strong><small>${time.toFixed(2)} 秒起 · ${Number(scene.duration).toFixed(2)} 秒 · ${scene.actors.length} 位人物</small></span>`;
      button.onclick=()=>{finishTransformEdit();activeScene=index;renderCut();notifyVisualSelection();}; list.append(button);
      time+=Math.round(Number(scene.duration)*Number(el('cut-fps').value))/Number(el('cut-fps').value);
    });
    if (!scenes.length) list.textContent='点击背景缩略图右下角的“＋”添加到轨道，再添加人物。';
    el('cut-total').textContent=`${scenes.length} 个镜头 · ${time.toFixed(2)} 秒`;
    renderEditor(); renderPreview();updateAssetActions();
    window.dispatchEvent(new Event('cut-rendered'));
  }
  function renderEditor() {
    finishTransformEdit();
    const scene=scenes[activeScene], editor=el('cut-editor');
    if (!scene) { editor.replaceChildren(); return; }
    const bg=background(scene.background);
    editor.innerHTML=`<label>画面素材<select id="cut-visual-target"><option value="background">背景</option>${scene.actors.map(a=>`<option value="${a.slot||0}">角色 ${(a.slot||0)+1} · ${escape(spriteName(a.id))}</option>`).join('')}</select></label><div id="cut-transform-panel"></div><details class="cut-scene-settings"><summary>镜头与角色</summary><label>镜头时长（秒）<input id="cut-scene-duration" type="number" min="0.1" max="3600" step="0.1" value="${scene.duration}"></label><label>放入角色<select id="cut-role-target"><option value="0">角色 1</option><option value="1">角色 2</option></select></label><div class="production-actions"><button id="cut-layout-single" type="button">单人居中</button><button id="cut-layout-double" type="button">双人左右</button></div>${scene.actors.map(a=>`<button type="button" data-remove-actor="${a.slot||0}">角色 ${(a.slot||0)+1} 移除 / 退场</button>`).join('')}${bg?.kind==='video'?`<label><input id="cut-video-loop" type="checkbox" ${scene.loop?'checked':''}>长度不足时循环播放</label><label><input id="cut-video-restart" type="checkbox" ${scene.restart?'checked':''}>本镜头重新开始背景视频</label><label>视频起点（秒）<input id="cut-video-start" type="number" min="0" step="0.1" value="${scene.videoStart||0}"></label>`:''}<div class="production-actions"><button id="cut-move-up" type="button">上移</button><button id="cut-move-down" type="button">下移</button><button id="cut-remove-scene" type="button">删除镜头</button></div></details>`;
    if(visualTarget!=='background'&&!scene.actors.some(a=>String(a.slot||0)===visualTarget))visualTarget='background';
    el('cut-visual-target').value=visualTarget;
    el('cut-visual-target').onchange=e=>selectVisual(e.target.value);
    const actor=scene.actors.find(a=>String(a.slot||0)===visualTarget),target=actor||scene,t=transformFor(scene,actor);
    const panel=el('cut-transform-panel'),[w,h]=canvasSize();
    if(t){
      const value=key=>['x','y','rotation'].includes(key)?Math.round(t[key]):Number(t[key].toFixed(1));
      panel.innerHTML=`<div class="transform-heading"><strong>位置大小</strong><button id="cut-transform-reset" type="button" title="恢复默认构图">重置</button></div><div class="transform-scale"><label for="cut-scale">缩放</label><input id="cut-scale-slider" aria-label="缩放滑块" type="range" min="1" max="2000" step="1" value="${t.scaleX}"><input id="cut-scale" aria-label="缩放百分比" type="number" min="1" max="2000" step="0.1" value="${value('scaleX')}"><span>%</span></div><label class="transform-lock">等比缩放<input id="cut-uniform" type="checkbox" ${t.uniform?'checked':''}></label>${!t.uniform?`<label>垂直缩放 %<input id="cut-scale-y" type="number" min="1" max="2000" step="0.1" value="${value('scaleY')}"></label>`:''}<div class="transform-position"><label>位置 X<input id="cut-position-x" type="number" min="${-w*10}" max="${w*10}" step="1" value="${value('x')}"></label><label>位置 Y<input id="cut-position-y" type="number" min="${-h*10}" max="${h*10}" step="1" value="${value('y')}"></label></div><label>旋转 °<input id="cut-rotation" type="number" min="-360" max="360" step="1" value="${value('rotation')}"></label><div class="production-actions"><button id="cut-center-x" type="button">水平居中</button><button id="cut-center-y" type="button">垂直居中</button></div><small class="transform-note">位置单位：画布像素；中心为 0，X 向右、Y 向上。100% 为素材等比适应画布。换图保留构图。</small>`;
      const bind=(input,key)=>{
        input.oninput=()=>{
          if(transformEdit?.input!==input){finishTransformEdit();transformEdit={input,transform:t,before:structuredClone(t),display:String(value(key))};}
          if(!input.value.trim()||!input.checkValidity())return;
          t[key]=Number(input.value);if(t.uniform&&key.startsWith('scale'))t.scaleX=t.scaleY=t[key];
          if(key.startsWith('scale')){if(input.id==='cut-scale-slider')el('cut-scale').value=value('scaleX');else el('cut-scale-slider').value=t.scaleX;if(el('cut-scale-y')&&input.id!=='cut-scale-y')el('cut-scale-y').value=value('scaleY');}
          refreshVisualStyles();
        };
        input.onchange=()=>finishTransformEdit();input.onblur=()=>finishTransformEdit();
        input.onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();finishTransformEdit(false);el('cut-scale-slider').value=t.scaleX;el('cut-scale').value=value('scaleX');}else if(event.key==='Enter'){event.preventDefault();finishTransformEdit();}};
        input.onpointercancel=()=>{finishTransformEdit(false);el('cut-scale-slider').value=t.scaleX;el('cut-scale').value=value('scaleX');};
      };
      for(const [id,key] of [['cut-scale','scaleX'],['cut-scale-y','scaleY'],['cut-position-x','x'],['cut-position-y','y'],['cut-rotation','rotation'],['cut-scale-slider','scaleX']])if(el(id))bind(el(id),key);
      el('cut-uniform').onchange=e=>{t.uniform=e.target.checked;if(t.uniform)t.scaleY=t.scaleX;markDirty();renderPreview();renderEditor();};
      el('cut-transform-reset').onclick=()=>{delete target[actor?'transform':'backgroundTransform'];transformFor(scene,actor);markDirty();renderCut();};
      for(const [id,key] of [['cut-center-x','x'],['cut-center-y','y']])el(id).onclick=()=>{t[key]=0;markDirty();renderPreview();renderEditor();};
    }else panel.textContent='正在读取立绘尺寸…';
    if(actor)window.cutComposition?.renderActor(panel,actor);
    el('cut-scene-duration').onchange=e=>{if(!e.target.checkValidity()||!e.target.value.trim()){renderEditor();return;}scene.duration=Number(e.target.value);markDirty();renderCut();};
    el('cut-role-target').value=String(roleTarget);
    el('cut-role-target').onchange=e=>chooseRole(Number(e.target.value));
    el('cut-layout-single').onclick=()=>{if(scene.actors.length){const a=scene.actors[0];scene.actors=[{...a,x:0,slot:0}];if(a.transform)a.transform.x=0;}markDirty();renderCut();};
    el('cut-layout-double').onclick=()=>{scene.actors.forEach(a=>{a.x=(a.slot||0)===0?-.45:.45;if(a.transform)a.transform.x=a.x*w/2;});markDirty();renderCut();};
    editor.querySelectorAll('[data-remove-actor]').forEach(b=>b.onclick=()=>{scene.actors=scene.actors.filter(a=>(a.slot||0)!==Number(b.dataset.removeActor));markDirty();renderCut();});
    if(bg?.kind==='video') {
      el('cut-video-loop').onchange=e=>{scene.loop=e.target.checked;markDirty();renderPreview();};
      el('cut-video-restart').onchange=e=>{scene.restart=e.target.checked;markDirty();renderPreview();};
      el('cut-video-start').onchange=e=>{scene.videoStart=Number(e.target.value);scene.restart=true;markDirty();renderEditor();renderPreview();};
    }
    el('cut-move-up').disabled=activeScene===0; el('cut-move-down').disabled=activeScene===scenes.length-1;
    const move=delta=> {const next=activeScene+delta;[scenes[activeScene],scenes[next]]=[scenes[next],scenes[activeScene]];activeScene=next;markDirty();renderCut();};
    el('cut-move-up').onclick=()=>move(-1); el('cut-move-down').onclick=()=>move(1);
    el('cut-remove-scene').onclick=()=>{scenes.splice(activeScene,1);activeScene=Math.min(activeScene,scenes.length-1);markDirty();renderCut();};
  }
  function renderPreview() {
    clearAssetView();
    const scene=scenes[activeScene], preview=el('cut-preview'); preview.replaceChildren();
    preview.style.background=scene?.blank?'#000':'';
    const [w,h]=el('cut-canvas').value.split('x').map(Number); preview.style.aspectRatio=`${w}/${h}`;
    if (!scene) {preview.textContent='添加背景镜头开始制作';return;}
    const bg=background(scene.background);
    if (bg) {
      const media=document.createElement(bg.kind==='video'?'video':'img');media.className='preview-bg';media.dataset.visualTarget='background';media.src=bgUrl(bg.id);media.setAttribute('aria-label',bg.name);
      if(bg.kind==='video') {
        media.muted=true;media.controls=true;media.preload='metadata';media.loop=scene.loop;
        let cursor=0,last=''; const fps=Number(el('cut-fps').value);
        for(let ix=0;ix<=activeScene;ix++) {const s=scenes[ix];if(s.background!==last||s.restart)cursor=Number(s.videoStart)||0;if(ix<activeScene)cursor+=Math.round(s.duration*fps)/fps;last=s.background;}
        media.onloadedmetadata=()=>{media.currentTime=scene.loop?cursor%media.duration:Math.min(cursor,media.duration);};
      }
      const apply=()=>{const t=transformFor(scene);if(t)Object.assign(media.style,geometry.style(w,h,bg.width,bg.height,t));};
      apply();media.addEventListener('click',()=>selectVisual('background'));preview.append(media);
    }
    const order=window.cutV2?.snapshot().roleOrder||[0,1];
    [...scene.actors].sort((a,b)=>order.indexOf(a.slot||0)-order.indexOf(b.slot||0)).forEach(a=>{
      const image=document.createElement('img');image.alt=spriteName(a.id);image.className='preview-actor';image.dataset.visualTarget=String(a.slot||0);
      const apply=()=>{const size=a.alignment||spriteSizes.get(spriteKey(a)),t=transformFor(scene,a);if(size&&t)Object.assign(image.style,geometry.style(w,h,size.width,size.height,t));};
      const requestedKey=spriteKey(a),initializing=!spriteSizes.has(requestedKey)||!a.transform;
      image.onload=()=>{spriteSizes.set(requestedKey,{width:image.naturalWidth,height:image.naturalHeight});apply();if(initializing&&scene===scenes[activeScene]&&visualTarget===String(a.slot||0))renderEditor();};
      image.onerror=()=>{if(scene===scenes[activeScene])el('cut-status').textContent='立绘读取失败，请检查素材是否丢失';};
      image.onclick=()=>selectVisual(String(a.slot||0));
      image.src=spriteUrl(a);apply();preview.append(image);
    });
    window.cutLayers?.renderPreview(preview);
    window.cutV2?.renderPreview(preview,activeScene);
    refreshVisualStyles();
  }
  function payload() {
    const [width,height]=el('cut-canvas').value.split('x').map(Number);
    return {id:projectId||undefined,name:el('cut-name').value,width,height,fps:Number(el('cut-fps').value),scenes,...(window.cutV2?.snapshot()||{}),...(window.cutText?.snapshot()||{}),...(window.cutScript?.snapshot()||{}),...(window.cutLayers?.snapshot()||{})};
  }
  function adopt(project,{preserveHistory=false}={}) {
    projectLoadSerial++;projectRevision++;
    finishTransformEdit(false);
    const previousTime=Number(el('dialogue-preview-time')?.value)||0;
    projectId=project.id; scenes=project.scenes;el('cut-name').value=project.name;cleanProjectName=el('cut-name').value;
    setCanvas(project.width,project.height);el('cut-fps').value=String(project.fps);
    if(!preserveHistory){visualTarget='background';roleTarget=0;output='';el('cut-open-output').hidden=true;}
    window.cutLayers?.adopt(project);
    activeScene=scenes.length?0:-1;dirty=false;window.cutV2?.adopt(project);window.cutText?.adopt(project);window.cutScript?.adopt(project);renderCut();if(preserveHistory)window.cutV2.locate(previousTime);window.dispatchEvent(new CustomEvent('cut-project-loaded',{detail:{preserveHistory}}));
  }
  async function saveCut(exportDraft=false) {
    if(cutBusy)return;
    finishTransformEdit();
    const snapshot=structuredClone(payload());
    if(!snapshot.scenes.length){el('cut-status').textContent='先添加图片或视频到时间轴，再保存项目或生成剪映草稿。';return;}
    const preflight=window.cutValidation.check(snapshot,window.cutV2.audioItems());
    if(exportDraft?!preflight.canExport:!preflight.canSave){el('cut-status').textContent='请先修正时间轴提示：'+preflight.issues.find(i=>exportDraft?i.blocksExport:i.blocksSave).message;window.dispatchEvent(new Event('cut-preflight-open'));return;}
    if(exportDraft){const overlaps=preflight.issues.filter(i=>i.code==='cue-overlap');if(overlaps.length&&!window.confirm(`有 ${overlaps.length} 处字幕时间重叠，会同时显示并可能叠字。继续保留这些重叠并导出吗？`))return;}
    cutBusy=true;
    el('roughcut-page').inert=true;
    el('cut-save').disabled=true;el('cut-export').disabled=true;
    el('cut-status').textContent=exportDraft?'正在准备剪映草稿…':'正在保存项目…';
    window.dispatchEvent(new Event('cut-save-state'));
    try {
      if(exportDraft) {await api('/api/roughcut/options',{draftDirectory:el('cut-directory').value,materialDirectory:el('cut-material-directory').value});el('cut-status').textContent='正在复制素材并生成分轨草稿…';}
      const data=await api(exportDraft?'/api/roughcut/export':'/api/roughcut/save',snapshot);
      adopt(exportDraft?data.project:data,{preserveHistory:true});
      const success=exportDraft?`已生成 ${data.duration.toFixed(2)} 秒草稿：${data.path}。请在剪映打开检查。`:'项目已保存，可从“项目与导出设置”重新打开。';
      if(exportDraft) {output=data.path;el('cut-open-output').hidden=false;}
      el('cut-status').textContent=success;
      try {await refreshProjects();}
      catch(error) {el('cut-status').textContent=success+' 项目列表暂未刷新：'+error.message+'；稍后重新进入工作区即可重试。';}
    } catch(error) {
      el('cut-status').textContent=error.message;
    } finally {
      cutBusy=false;
      el('roughcut-page').inert=false;
      el('cut-save').disabled=false;el('cut-export').disabled=false;
      window.dispatchEvent(new Event('cut-save-state'));
    }
  }
  el('nav-backgrounds').onclick=()=>switchPage('backgrounds'); el('cut-back').onclick=()=>switchPage('tools');
  el('bg-import').onclick=()=>importBackgrounds();el('bg-import-folder').onclick=()=>importBackgrounds(true);
  el('bg-to-cut').onclick=()=>{if(!bgSelection.size){el('bg-status').textContent='先勾选要排列的背景素材';return;}enterWithBackgrounds([...bgSelection]);};
  let bgTimer,assetTimer;
  el('bg-search').oninput=()=>{clearTimeout(bgTimer);bgTimer=setTimeout(()=>run('bg-status',null,loadBackgrounds),250);};
  for(const id of ['bg-kind','bg-favorite','bg-trash-view']) el(id).onchange=()=>{clearBgDetail();bgSelection.clear();run('bg-status',null,loadBackgrounds);};
  el('cut-bg-tab').onclick=()=>{assetKind='background';run('cut-status',null,loadAssets);};
  el('cut-sprite-tab').onclick=()=>{assetKind='sprite';run('cut-status',null,loadAssets);};
  el('cut-asset-search').oninput=()=>{clearTimeout(assetTimer);assetTimer=setTimeout(()=>run('cut-status',null,loadAssets),250);};
  el('cut-assets-more').onclick=()=>run('cut-status',el('cut-assets-more'),()=>loadAssets(true));
  el('cut-add').onclick=()=>{scenes.push(activeScene>=0?structuredClone(scenes[activeScene]):newScene(allBackgrounds.find(i=>!i.missing)?.id||''));activeScene=scenes.length-1;markDirty();renderCut();};
  el('cut-duplicate').onclick=()=>{if(!scenes.length){el('cut-status').textContent='请先添加一个镜头';return;}const ix=activeScene>=0?activeScene:scenes.length-1;const copy=structuredClone(scenes[ix]);copy.id=crypto.randomUUID().replaceAll('-','');delete copy.sourceRow;scenes.splice(ix+1,0,copy);activeScene=ix+1;markDirty();renderCut();};
  el('cut-apply-duration').onclick=()=>{const value=Number(el('cut-batch-duration').value);if(!Number.isFinite(value)||value<=0||value>3600){el('cut-status').textContent='请输入有效的镜头时长';return;}scenes.forEach(s=>s.duration=value);markDirty();renderCut();};
  el('cut-save').onclick=()=>saveCut();el('cut-export').onclick=()=>saveCut(true);
  el('cut-open-output').onclick=()=>run('cut-status',el('cut-open-output'),()=>api('/api/settings/open-folder',{target:'dir',path:output}));
  el('cut-choose-directory').onclick=()=>run('cut-status',el('cut-choose-directory'),async()=>{
    el('cut-status').textContent='正在选择草稿目录…';
    const data=await api('/api/settings/choose-folder',{target:'draft',initial:el('cut-directory').value});
    if(data.path){el('cut-directory').value=data.path;markDirty();el('cut-status').textContent='草稿目录：'+data.path;}
    else el('cut-status').textContent='已取消选择草稿目录';
  });
  el('cut-directory').addEventListener('input',markDirty);
  el('cut-material-directory').addEventListener('input',markDirty);
  el('cut-choose-material-directory').onclick=()=>run('cut-status',el('cut-choose-material-directory'),async()=>{
    el('cut-status').textContent='正在选择素材目录…';
    const data=await api('/api/settings/choose-folder',{target:'episode',initial:el('cut-material-directory').value});
    if(data.path){el('cut-material-directory').value=data.path;markDirty();el('cut-status').textContent='素材目录：'+data.path;}
    else el('cut-status').textContent='已取消选择素材目录';
  });
  el('cut-projects').onchange=()=>run('cut-status',null,async()=> {
    const id=el('cut-projects').value;if(!id)return;
    if(hasUnsavedChanges()&&!window.confirm('当前修改尚未保存，确定打开其他项目吗？')){el('cut-projects').value=projectId||'';return;}
    const serial=++projectLoadSerial,revision=projectRevision,name=el('cut-name').value;
    try {
      const [assets,project]=await Promise.all([api('/api/backgrounds'),api('/api/roughcut/project?id='+id)]);
      if(serial!==projectLoadSerial)return;
      if(revision!==projectRevision||name!==el('cut-name').value){el('cut-projects').value=projectId||'';el('cut-status').textContent='当前项目已有新修改，已取消打开其他项目。';return;}
      allBackgrounds=assets.items;adopt(project);el('cut-status').textContent='已打开粗剪项目';
    }
    catch(error){if(serial!==projectLoadSerial)return;el('cut-projects').value=projectId||'';throw error;}
  });
  el('cut-new').onclick=()=>{finishTransformEdit();if(hasUnsavedChanges()&&!window.confirm('当前修改尚未保存，确定新建项目吗？'))return;projectLoadSerial++;projectRevision++;projectId='';scenes=[];activeScene=-1;visualTarget='background';roleTarget=0;dirty=false;output='';clearAssetView();el('cut-open-output').hidden=true;el('cut-name').value='新草稿项目';cleanProjectName=el('cut-name').value;el('cut-projects').value='';window.cutLayers?.adopt({});window.cutV2?.adopt({});window.cutText?.adopt({});window.cutScript?.adopt({});renderCut();window.dispatchEvent(new Event('cut-project-loaded'));el('cut-status').textContent='已新建项目';};
  el('cut-name').onchange=()=>{if(el('cut-name').value!==cleanProjectName)markDirty();else window.dispatchEvent(new Event('cut-changed'));renderCut();};
  el('cut-fps').onchange=()=>{markDirty();renderCut();};
  function setCanvas(w,h){const select=el('cut-canvas'),value=`${w}x${h}`;if(![...select.options].some(o=>o.value===value)){const custom=select.querySelector('[data-custom]');custom.value=value;custom.textContent=`自定义 ${w} × ${h}`;}select.value=value;el('cut-width').value=w;el('cut-height').value=h;}
  el('cut-canvas').onchange=()=>{setCanvas(...canvasSize());markDirty();renderCut();};
  for(const id of ['cut-width','cut-height'])el(id).onchange=()=>{const w=Number(el('cut-width').value),h=Number(el('cut-height').value);if(![w,h].every(v=>Number.isInteger(v)&&v>=320&&v<=3840)){el('cut-status').textContent='宽高需为 320–3840 的整数';setCanvas(...canvasSize());return;}setCanvas(w,h);markDirty();renderCut();};
  window.addEventListener('beforeunload',event=>{if(hasUnsavedChanges()){event.preventDefault();event.returnValue='';}});
  window.cutEditor={api,escape,markDirty,render:renderCut,snapshot:payload,restore:adopt,ensureCoverage,refreshAssets:loadAssets,cancelAssetLoad:()=>{assetSerial++;},previewAsset:showAsset,save:()=>saveCut(false),isDirty:hasUnsavedChanges,isBusy:()=>cutBusy,
    applyTimeline(value,{coverContent=false}={}){scenes=value.scenes;activeScene=scenes.length?0:-1;window.cutLayers?.adopt(value);window.cutV2.adopt(value);window.cutText.adopt(value);window.cutScript.adopt(value);if(coverContent)ensureCoverage(Math.max(0,...[...(value.audioClips||[]),...(value.textClips||[])].map(clip=>clip.start+clip.duration)));markDirty();renderCut();},
    async openGeneratedProject(project){allBackgrounds=(await api('/api/backgrounds')).items;await window.cutV2.loadAudio();adopt(project);await refreshProjects();output='';el('cut-open-output').hidden=true;},
    get scenes(){return scenes;},get activeScene(){return activeScene;},
    get visualSelection(){return {index:activeScene,kind:visualTarget==='background'?'background':'actor',slot:visualTarget==='background'?null:Number(visualTarget)};},
    setScenes(value){scenes=value;activeScene=scenes.length?0:-1;markDirty();renderCut();},
    selectScene(index,target){finishTransformEdit();activeScene=index;if(target!==undefined){visualTarget=String(target);if(target!=='background')roleTarget=Number(target);}renderCut();if(target!==undefined)notifyVisualSelection();}};
  window.addEventListener('workshop-page',event=> {
    if(event.detail==='backgrounds')run('bg-status',null,loadBackgrounds);
    if(event.detail==='roughcut')run('cut-status',null,async()=>{await initializeCut();renderCut();});
    if(event.detail!=='roughcut')el('cut-preview').querySelectorAll('video,audio').forEach(v=>v.pause());
    if(event.detail!=='backgrounds')el('bg-detail').querySelectorAll('video').forEach(v=>v.pause());
  });
})();

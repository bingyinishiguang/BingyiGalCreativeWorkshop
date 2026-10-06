/*Column preferences hold reusable assets; full-length images are ordinary layers.*/
(() => {
  const $=id=>document.getElementById(id), editor=window.cutEditor, api=editor.api, e=editor.escape;
  let layers=[],workflow,generation,images=[],audio=[],presets=[],formLayers=[],formSequence=[],selectedRevision,baseline;
  const button=document.createElement('button');button.id='column-open';button.textContent='常用配置 / 自动铺底';
  $('roughcut-page').querySelector('.production-heading').append(button);
  const dialog=document.createElement('dialog');dialog.className='modal';dialog.id='column-dialog';
  dialog.style.cssText='width:min(900px,94vw);max-height:90vh;overflow:auto';
  dialog.innerHTML=`<div class="modal-top"><h2>常用配置与自动铺底</h2><button id="column-close" type="button">关闭</button></div>
    <p>记住常用画面、音乐和全片图片；每期选择配音，生成新的可编辑草稿。</p>
    <div class="production-filters"><label>已有配置<select id="column-preset"><option value="">新配置</option></select></label><label>配置名称<input id="column-name" value="IfGal"></label><button id="column-save" type="button">保存常用配置</button></div>
    <div class="production-filters"><label>起步方案<select id="column-starter"><option value="cover">配音＋单个画面</option><option value="sequence">配音＋顺序画面＋补图</option></select></label><button id="column-new">建立新配置</button><button id="column-copy">将当前设置另存一份</button></div><p id="column-edit-state" role="status"></p>
    <div class="production-filters"><label>常用画面<select id="column-background"></select></label><button data-column-import="background">导入画面</button><label>开场画面（可选）<select id="column-opening-background"></select></label><button data-column-import="opening-background">导入开场画面</button></div>
    <div class="production-filters"><label>主画面时长处理<select id="column-background-mode"><option value="ask">不自动循环或截取</option><option value="trim">允许截取到配音结束</option><option value="loop">允许循环铺底并截取末段</option></select></label><label>开场画面时长处理<select id="column-opening-mode"><option value="ask">不自动循环或截取</option><option value="trim">允许截取到配音结束</option><option value="loop">允许循环铺底并截取末段</option></select></label></div>
    <label>主画面安排<select id="column-visual-mode"><option value="cover">单个画面铺底</option><option value="sequence">多个画面按顺序组合</option></select></label>
    <section id="column-sequence-panel" hidden><p>按列表顺序播放，每项保留独立截取起点。最后可放一张图片填满剩余；新画面添加在补图前。专用开场画面在这组画面之前播放。</p><div class="production-filters"><select id="column-sequence-image" aria-label="选择顺序画面"></select><button id="column-add-sequence">添加画面</button><button data-column-import="sequence-image">导入顺序素材</button></div><div id="column-sequence-list"></div></section>
    <div class="production-filters"><label>BGM（可选）<select id="column-bgm"></select></label><button data-column-import="bgm">导入 BGM</button><label>音量倍率（1 = 0 dB）<input id="column-bgm-volume" type="number" min="0" max="2" step="0.05" value="1"></label><label><input id="column-bgm-loop" type="checkbox">音乐播完后循环</label></div>
    <p>画面按你明确选择的规则铺到配音结束，视频原声关闭。音乐默认播完即止。</p><p id="column-revision"></p>
    <h3>全片叠加图片</h3><p>用于徽章、栏目名图片、边框等；列表靠后的图片在前面，字幕显示在这些图片之上。</p>
    <div class="production-filters"><select id="column-overlay-image" aria-label="选择全片图片"></select><button id="column-add-overlay">添加图片层</button><button data-column-import="overlay-image">导入图片</button></div><div id="column-overlay-list"></div>
    <button id="column-apply-overlays">应用图片层到当前草稿</button>
    <h3>输出位置</h3><div class="production-filters"><label>本期作品目录<input id="column-episode-directory" placeholder="每期单独选择，可暂时留空"></label><button data-column-folder="episode-directory">选择作品目录</button><label>剪映草稿根目录<input id="column-draft-directory"></label><button data-column-folder="draft-directory">选择草稿目录</button></div>
    <p>草稿根目录存入常用配置；作品目录每期单独选择，不沿用上一期。留空时本期不关联作品目录。</p>
    <details><summary>画布与帧率</summary><div class="production-filters"><label>宽<input id="column-width" type="number" value="1920" min="320" max="3840"></label><label>高<input id="column-height" type="number" value="1080" min="320" max="3840"></label><label>帧率<select id="column-fps"><option>30</option><option>24</option><option>25</option><option>60</option></select></label></div></details>
    <h3>本期配音</h3><div class="production-filters"><label>本期名称<input id="column-episode-name" value="IfGal 新一期"></label><label>开场配音（可选）<select id="column-opening-voice"></select></label><button data-column-import="opening-voice">导入开场配音</button><label>正文配音<select id="column-voice"></select></label><button data-column-import="voice">导入正文配音</button></div>
    <button id="column-check">预览安排 / 检查缺口</button><button id="column-build" class="primary-button">按配音生成新草稿</button><div id="column-arrangement"></div><p id="column-status" role="status"></p>`;
  document.body.append(dialog);
  const status=value=>$('column-status').textContent=value;
  function settingsKey(){const value=config();delete value.id;delete value.revision;return JSON.stringify(value);}
  function editState(){
    const changed=baseline!==settingsKey();
    $('column-edit-state').textContent=$('column-preset').value?(changed?'已修改常用设置：生成只用于本期，点击保存才建立新版本。':'正在使用已保存配置；本期名称、配音和作品目录每次单独填写。'):'新配置尚未保存；可以先试生成，满意后再保存常用设置。';
    $('column-save').textContent=$('column-preset').value?'保存为下一版':'保存新配置';
    if($('column-arrangement').childElementCount)status('设置已变化，请重新检查安排。');
    $('column-arrangement').replaceChildren();
  }
  dialog.addEventListener('change',editState);
  dialog.addEventListener('input',editState);
  async function run(action){dialog.querySelectorAll('button').forEach(b=>b.disabled=true);try{await action();}catch(error){status(error.message);}finally{dialog.querySelectorAll('button').forEach(b=>b.disabled=false);}}
  function options(id,items,empty='不使用'){
    const select=$('column-'+id),old=select.value;
    select.innerHTML=`<option value="">${empty}</option>`+items.map(v=>`<option value="${e(v.id)}" ${v.missing?'disabled':''}>${e(v.name)}${v.missing?'（文件丢失）':''}</option>`).join('');select.value=old;
  }
  async function refresh(){
    const [b,a,p]=await Promise.all([api('/api/backgrounds'),api('/api/audio'),api('/api/roughcut/columns')]);
    images=b.items;audio=a.items;presets=p.items;
    options('background',images,'请选择画面');options('opening-background',images);options('overlay-image',images.filter(v=>v.kind==='image'),'请选择图片');
    options('sequence-image',images,'请选择画面');
    for(const id of ['bgm','opening-voice','voice'])options(id,audio,id==='voice'?'请选择配音':'不使用');
    options('preset',presets,'以当前设置新建配置');
  }
  function renderLayers(){
    const imageChoices=(selected)=>`<option value="">请选择图片</option>`+images.filter(v=>v.kind==='image').map(v=>`<option value="${e(v.id)}" ${v.id===selected?'selected':''}>${e(v.name)}</option>`).join('')+(!images.some(v=>v.id===selected)?`<option selected value="${e(selected)}">素材丢失，请替换</option>`:'');
    $('column-overlay-list').innerHTML=formLayers.map((row,index)=>`<div class="production-panel"><strong>${e(row.name)}</strong><div class="production-filters">${[['left','距左边 %'],['top','距上边 %'],['width','宽度占画面 %'],['rotation','旋转角度']].map(([key,label])=>`<label>${label}<input type="number" step="0.1" data-layer-index="${index}" data-layer-key="${key}" value="${row[key]}"></label>`).join('')}<button data-layer-remove="${index}">移除</button>${index?`<button data-layer-up="${index}">向后移一层</button>`:''}</div></div>`).join('');
    dialog.querySelectorAll('[data-layer-key]').forEach(input=>input.onchange=()=>formLayers[Number(input.dataset.layerIndex)][input.dataset.layerKey]=Number(input.value));
    dialog.querySelectorAll('[data-layer-remove]').forEach(b=>b.onclick=()=>{formLayers.splice(Number(b.dataset.layerRemove),1);renderLayers();});
    dialog.querySelectorAll('[data-layer-up]').forEach(b=>b.onclick=()=>{const i=Number(b.dataset.layerUp);[formLayers[i-1],formLayers[i]]=[formLayers[i],formLayers[i-1]];renderLayers();});
    $('column-overlay-list').querySelectorAll('.production-panel').forEach((panel,i)=>{
      const label=document.createElement('label');label.textContent='替换图片（保留位置与大小）';const select=document.createElement('select');select.dataset.layerImage=i;select.innerHTML=imageChoices(formLayers[i].image);select.onchange=()=>{formLayers[i].image=select.value;formLayers[i].name=images.find(v=>v.id===select.value)?.name||'全片图片';renderLayers();};label.append(select);panel.querySelector('strong').after(label);
      const copy=document.createElement('button');copy.textContent='复制图片层';copy.dataset.layerCopy=i;copy.onclick=()=>{if(formLayers.length>=16){status('最多16个图片层');return;}formLayers.splice(i+1,0,{...structuredClone(formLayers[i]),slotId:crypto.randomUUID().replaceAll('-','')});renderLayers();};panel.append(copy);
      if(i<formLayers.length-1){const down=document.createElement('button');down.textContent='向前移一层';down.dataset.layerDown=i;down.onclick=()=>{[formLayers[i],formLayers[i+1]]=[formLayers[i+1],formLayers[i]];renderLayers();};panel.append(down);}
    });
    editState();
  }
  function renderSequence(){
    $('column-sequence-panel').hidden=$('column-visual-mode').value!=='sequence';
    $('column-background').disabled=$('column-visual-mode').value==='sequence';
    $('column-background-mode').disabled=$('column-visual-mode').value==='sequence';
    $('column-sequence-list').innerHTML=formSequence.map((row,i)=>`<div class="production-panel"><strong>画面 ${i+1}</strong><small>${e(images.find(v=>v.id===row.background)?.kind==='video'?'视频总长 '+Number(images.find(v=>v.id===row.background).duration).toFixed(3)+' 秒':'静态图片')}</small><div class="production-filters"><label>素材<select data-seq-index="${i}" data-seq-key="background"><option value="">请选择素材</option>${images.map(v=>`<option value="${e(v.id)}">${e(v.name)}</option>`).join('')}${row.background&&!images.some(v=>v.id===row.background)?`<option value="${e(row.background)}">素材丢失，请替换</option>`:''}</select></label><label>时长方式<select data-seq-index="${i}" data-seq-key="timing"><option value="fixed">使用指定时长</option><option value="remainder">图片填满剩余</option></select></label><label>视频起点（秒）<input type="number" min="0" step="0.01" data-seq-index="${i}" data-seq-key="sourceStart" value="${row.sourceStart}"></label><label>取用 / 停留（秒）<input type="number" min="0.02" step="0.01" data-seq-index="${i}" data-seq-key="duration" value="${row.duration}"></label><label>补图最长（留空不限）<input type="number" min="0.02" step="0.01" data-seq-index="${i}" data-seq-key="maxDuration" value="${row.maxDuration??''}"></label><label><input type="checkbox" data-seq-index="${i}" data-seq-key="acceptFrameAdjustment" ${row.acceptFrameAdjustment?'checked':''}>允许按帧对齐（预览显示实际时长）</label></div><button data-seq-remove="${i}">移除</button>${row.timing==='fixed'?`<button data-seq-copy="${i}">复制画面</button>`:''}${i?`<button data-seq-up="${i}">向前移</button>`:''}${i<formSequence.length-1?`<button data-seq-down="${i}">向后移</button>`:''}</div>`).join('');
    dialog.querySelectorAll('[data-seq-key]').forEach(input=>{
      const row=formSequence[Number(input.dataset.seqIndex)],key=input.dataset.seqKey;
      if(input.tagName==='SELECT')input.value=row[key];
      const isVideo=images.find(v=>v.id===row.background)?.kind==='video';
      if(key==='sourceStart')input.disabled=!isVideo;
      if(key==='duration')input.disabled=row.timing==='remainder';
      if(key==='maxDuration')input.disabled=row.timing!=='remainder';
      if(key==='timing')input.querySelector('option[value="remainder"]').disabled=isVideo;
      input.onchange=()=>{row[key]=input.type==='checkbox'?input.checked:input.tagName==='SELECT'?input.value:input.value===''&&key==='maxDuration'?null:Number(input.value);
        if(key==='background'){row.sourceStart=0;if(images.find(v=>v.id===row.background)?.kind==='video')row.timing='fixed';}
        if(key==='background'||key==='timing')renderSequence();};
    });
    dialog.querySelectorAll('[data-seq-remove]').forEach(b=>b.onclick=()=>{formSequence.splice(Number(b.dataset.seqRemove),1);renderSequence();});
    dialog.querySelectorAll('[data-seq-copy]').forEach(b=>b.onclick=()=>{if(formSequence.length>=500){status('最多500项');return;}const i=Number(b.dataset.seqCopy);formSequence.splice(i+1,0,{...structuredClone(formSequence[i]),itemId:crypto.randomUUID().replaceAll('-','')});renderSequence();});
    for(const [attr,delta] of [['seqUp',-1],['seqDown',1]])dialog.querySelectorAll(`[data-${attr==='seqUp'?'seq-up':'seq-down'}]`).forEach(b=>b.onclick=()=>{const i=Number(b.dataset[attr]);[formSequence[i],formSequence[i+delta]]=[formSequence[i+delta],formSequence[i]];renderSequence();});
    editState();
  }
  $('column-visual-mode').onchange=renderSequence;
  $('column-add-sequence').onclick=()=>{const item=images.find(v=>v.id===$('column-sequence-image').value);if(!item){status('请选择画面');return;}if(formSequence.length>=500){status('最多500项');return;}const index=formSequence.findIndex(r=>r.timing==='remainder');formSequence.splice(index<0?formSequence.length:index,0,{itemId:crypto.randomUUID().replaceAll('-',''),background:item.id,sourceStart:0,duration:Math.min(5,item.duration||5),timing:'fixed',maxDuration:null,acceptFrameAdjustment:false});renderSequence();};
  function config(){return {id:$('column-preset').value||crypto.randomUUID().replaceAll('-',''),name:$('column-name').value,
    ...($('column-preset').value&&selectedRevision!=null?{revision:selectedRevision}:{}),schemaVersion:1,
    background:$('column-background').value,openingBackground:$('column-opening-background').value,bgm:$('column-bgm').value,
    bgmVolume:Number($('column-bgm-volume').value),bgmLoop:$('column-bgm-loop').checked,
    width:Number($('column-width').value),height:Number($('column-height').value),fps:Number($('column-fps').value),
    draftDirectory:$('column-draft-directory').value,overlays:structuredClone(formLayers),visualMode:$('column-visual-mode').value,sequence:structuredClone(formSequence),
    permissions:{background:{asset:$('column-background').value,mode:$('column-background-mode').value},openingBackground:{asset:$('column-opening-background').value,mode:$('column-opening-mode').value}}};}
  function adoptConfig(p){
    for(const [id,key] of Object.entries({'name':'name','background':'background','opening-background':'openingBackground','bgm':'bgm','bgm-volume':'bgmVolume','draft-directory':'draftDirectory','width':'width','height':'height','fps':'fps'})){
      const field=$('column-'+id),value=p[key]??'';
      if(field.tagName==='SELECT'&&value&&!Array.from(field.options).some(o=>o.value===value))field.add(new Option('素材丢失，请替换或选择不使用',value));
      field.value=value;
    }
    selectedRevision=p.revision;
    $('column-visual-mode').value=p.visualMode||'cover';formSequence=structuredClone(p.sequence||[]);renderSequence();
    $('column-revision').textContent=p.revision?`常用配置第 ${p.revision} 版；本期调整不会自动保存。`:'尚未保存；视频时长处理规则需要明确选择。';
    for(const [field,input] of [['background','background'],['openingBackground','opening']])$('column-'+input+'-mode').value=p[field]&&p.permissions?.[field]?.asset===p[field]?p.permissions[field].mode:'ask';
    $('column-bgm-loop').checked=p.bgmLoop===true;formLayers=structuredClone(p.overlays||[]);renderLayers();
    baseline=settingsKey();editState();
  }
  async function open(){await refresh();
    if(presets.length){const preferred=presets.find(p=>p.id===workflow?.presetId)||presets[0];$('column-preset').value=preferred.id;adoptConfig(preferred);}
    else {const project=editor.snapshot();adoptConfig({name:'IfGal',background:project.scenes[0]?.background||'',bgmVolume:1,width:project.width,height:project.height,fps:project.fps,...workflow,overlays:layers,draftDirectory:workflow?.draftDirectory||$('cut-directory').value});}
    $('column-episode-name').value=($('column-name').value||'栏目')+' 新一期';
    $('column-episode-directory').value='';$('column-opening-voice').value='';$('column-voice').value='';
    status('选择本期配音和作品目录，再生成一个新草稿。');dialog.showModal();
  }
  button.textContent='配置工作区';
  button.onclick=()=>window.configurationWorkspace.open().catch(error=>$('cut-status').textContent=error.message);
  $('column-close').onclick=()=>dialog.close();
  $('column-preset').onchange=()=>{const p=presets.find(v=>v.id===$('column-preset').value);if(p)adoptConfig(p);else{selectedRevision=undefined;$('column-revision').textContent='以当前设置建立新配置，原配置保持不变。';editState();}};
  $('column-copy').onclick=()=>{const c=config();$('column-preset').value='';delete c.revision;c.name+=' 副本';adoptConfig(c);status('已复制当前设置；修改名称后保存，新配置与原配置分开。');};
  $('column-new').onclick=()=>{
    const c=config(),mode=$('column-starter').value;
    $('column-preset').value='';
    adoptConfig({name:mode==='sequence'?'顺序画面配置':'单画面配置',width:c.width,height:c.height,fps:c.fps,draftDirectory:c.draftDirectory,bgmVolume:1,visualMode:mode,sequence:mode==='sequence'?[{itemId:crypto.randomUUID().replaceAll('-',''),background:'',sourceStart:0,duration:5,timing:'fixed',maxDuration:null},{itemId:crypto.randomUUID().replaceAll('-',''),background:'',sourceStart:0,duration:5,timing:'remainder',maxDuration:null}]:[]});
    status(mode==='sequence'?'已建立待填配置：选择第一段画面和最后的补图，填好时长后检查安排。':'已建立待填配置：选择主画面，再明确选择时长处理规则。');
  };
  $('column-background').onchange=()=>$('column-background-mode').value='ask';
  $('column-opening-background').onchange=()=>$('column-opening-mode').value='ask';
  $('column-add-overlay').onclick=()=>{const item=images.find(v=>v.id===$('column-overlay-image').value);if(!item){status('请选择一张图片');return;}if(formLayers.length>=16){status('最多 16 个图片层');return;}formLayers.push({image:item.id,name:item.name,left:2,top:2,width:12,rotation:0});renderLayers();};
  dialog.querySelectorAll('[data-column-import]').forEach(b=>b.onclick=()=>run(async()=>{
    const field=b.dataset.columnImport,isAudio=['bgm','voice','opening-voice'].includes(field),kind=isAudio?'audio':'backgrounds';
    const picked=await api('/api/'+kind+'/pick',{});if(!picked.paths?.length)return;
    const imported=await api('/api/'+kind+'/import',{paths:picked.paths});await refresh();
    const errors=imported.results.filter(r=>r.error);const item=imported.results.find(r=>r.item&&(!['overlay-image'].includes(field)||r.item.kind==='image'))?.item;
    if(item){$('column-'+field).value=item.id;if(field==='background')$('column-background-mode').value='ask';if(field==='opening-background')$('column-opening-mode').value='ask';}
    status(errors.length?errors.map(r=>r.source+'：'+r.error).join('；'):item?'已导入，可重复使用。':'没有可用的静态图片');
  }));
  dialog.querySelectorAll('[data-column-folder]').forEach(b=>b.onclick=()=>run(async()=>{const r=await api('/api/settings/choose-folder',{});if(r.path)$('column-'+b.dataset.columnFolder).value=r.path;}));
  $('column-save').onclick=()=>run(async()=>{const saved=await api('/api/roughcut/column-save',config());await refresh();$('column-preset').value=saved.id;adoptConfig(saved);status(`已保存常用配置第 ${saved.revision} 版；本期名称、配音和作品目录不存入配置。`);});
  $('column-apply-overlays').onclick=()=>run(async()=>{
    const project=editor.snapshot();if(!project.scenes.length)throw Error('先添加画面或生成草稿');
    const checked=await api('/api/roughcut/overlays-check',{overlays:formLayers});
    editor.applyTimeline({...project,overlays:checked.overlays});status('已应用图片层，可撤销；点击保存项目后保留。');
  });
  function episodeRequest(){
    if(!$('column-voice').value)throw Error('请选择正文配音');
    const c=config();const voices=[];if($('column-opening-voice').value)voices.push({audio:$('column-opening-voice').value,opening:true});voices.push({audio:$('column-voice').value});
    return {config:c,voices,name:$('column-episode-name').value,episodeDirectory:$('column-episode-directory').value};
  }
  $('column-check').onclick=()=>run(async()=>{
    $('column-arrangement').replaceChildren();
    const checked=await api('/api/roughcut/column-check',episodeRequest());
    if(checked.state!=='ready'){status(checked.issues.map(i=>i.message).join('；'));return;}
    const a=checked.arrangement;
    $('column-arrangement').innerHTML=a.sequence.length?`<table style="width:100%;text-align:left"><thead><tr><th>画面</th><th>出场区间</th><th>实际时长</th><th>源起点</th></tr></thead><tbody>${a.sequence.map((row,i)=>`<tr><td>${i+1}. ${e(images.find(v=>v.id===row.asset)?.name||'待补素材')}</td><td>${(row.startFrame/Number($('column-fps').value)).toFixed(3)}—${(row.endFrame/Number($('column-fps').value)).toFixed(3)} 秒</td><td>${(row.durationUs/1e6).toFixed(3)} 秒</td><td>${images.find(v=>v.id===row.asset)?.kind==='video'?(row.sourceStartUs/1e6).toFixed(3)+' 秒':'图片'}</td></tr>`).join('')}</tbody></table>`:`<p>主画面铺到 ${(a.durationUs/1e6).toFixed(3)} 秒；按已选择的时长规则处理。</p>`;
    status(`安排可生成，总时长 ${(a.durationUs/1000000).toFixed(3)} 秒。`+a.sequence.map((row,i)=>`画面 ${i+1}：${(row.durationUs/1000000).toFixed(3)} 秒（视频起点 ${(row.sourceStartUs/1000000).toFixed(3)} 秒）`).join('；'));
  });
  $('column-build').onclick=()=>run(async()=>{
    const request={...episodeRequest(),requestId:crypto.randomUUID().replaceAll('-','')},c=request.config;
    const checked=await api('/api/roughcut/column-check',request);
    if(checked.state!=='ready'){status(checked.issues.map(i=>i.message).join('；'));return;}
    //Keep the current project available before switching to a newly generated project.
    if(editor.snapshot().scenes.length)await api('/api/roughcut/save',editor.snapshot());
    const project=await api('/api/roughcut/column-build',request);
    await editor.openGeneratedProject(project);$('cut-directory').value=c.draftDirectory||$('cut-directory').value;
    dialog.close();$('cut-status').textContent=`已生成并保存 ${project.durationUs/1000000} 秒项目；检查后点击「生成剪映草稿」。`;
  });
  window.cutLayers={snapshot:()=>({...((layers.length||workflow)?{overlays:structuredClone(layers)}:{}),...(workflow?{workflow:structuredClone(workflow)}:{}),...(generation?{generation:structuredClone(generation)}:{})}),
    adopt(project){layers=structuredClone(project.overlays||[]);workflow=project.workflow?structuredClone(project.workflow):undefined;generation=project.generation?structuredClone(project.generation):undefined;},
    renderPreview(preview){for(const row of layers){const image=document.createElement('img');image.className='preview-full-layer';image.alt=row.name;image.src='/api/backgrounds/media?id='+encodeURIComponent(row.image);image.style.cssText=`position:absolute;left:${row.left}%;top:${row.top}%;width:${row.width}%;height:auto;transform:rotate(${row.rotation}deg);pointer-events:none`;preview.append(image);}},open:()=>window.configurationWorkspace.open()};
  window.addEventListener('column-layer-open',()=>window.configurationWorkspace.open().catch(error=>$('cut-status').textContent=error.message));
})();

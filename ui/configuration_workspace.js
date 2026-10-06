/*Configuration rules are independent of the currently edited project.*/
(()=>{
 const $=id=>document.getElementById(id),editor=window.cutEditor,api=editor.api,e=editor.escape;
 const clone=v=>structuredClone(v),uid=()=>crypto.randomUUID().replaceAll('-','');
 let media=[],audio=[],presets=[],selected={type:'settings'},target='main',filter='visual',checked=null,baseline='',busy=false,undo=[],redo=[],readyRanges=new Set(),roles={};
 try{roles=JSON.parse(localStorage.getItem('bingyi-audio-roles')||'{}');}catch{}
 const blank=()=>({schemaVersion:1,id:uid(),name:'新配置',visualMode:'sequence',durationPolicy:'voice',sequence:[],overlays:[],background:'',openingBackground:'',bgm:'',bgmVolume:1,bgmLoop:false,width:1920,height:1080,fps:30,draftDirectory:'',permissions:{background:{asset:'',mode:'ask'},openingBackground:{asset:'',mode:'ask'}}});
 let config=blank(),episode={name:'',directory:'',voices:[]};
 const page=document.createElement('section');page.id='configuration-page';page.hidden=true;
 page.innerHTML=`<header class="cfg-header"><button id="cfg-back">返回草稿</button><strong>配置工作区</strong><input id="cfg-name" aria-label="配置名称" value="新配置"><button id="cfg-new">新建</button><select id="cfg-open" aria-label="打开配置"><option value="">打开配置…</option></select><details class="cfg-menu"><summary>更多</summary><button id="cfg-copy">复制为新配置</button><button id="cfg-settings">输出与画布</button></details><span id="cfg-dirty"></span><button id="cfg-save">保存配置</button><button id="cfg-build" class="cfg-primary">生成新草稿</button></header>
 <div class="cfg-body"><aside id="cfg-assets-panel" class="cfg-panel"><nav><button id="cfg-visual-tab">画面</button><button id="cfg-audio-tab">音频</button><button id="cfg-import">导入</button></nav><div class="cfg-components" aria-label="组件类型">${[['main','主画面'],['fill','尾部补图'],['overlay','全片图片'],['voice','配音'],['bgm','背景音乐']].map(([id,label])=>`<button data-cfg-purpose="${id}">${label}</button>`).join('')}</div><p id="cfg-purpose"></p><input id="cfg-search" type="search" aria-label="搜索素材" placeholder="搜索素材"><audio id="cfg-audition" controls preload="none" hidden></audio><div id="cfg-asset-list"></div></aside>
 <section class="cfg-panel cfg-player"><header><strong>画面预览</strong><span id="cfg-mode">配置规则 · 时长待计算</span><button id="cfg-show-assets">素材</button><button id="cfg-show-inspector">参数</button></header><div id="cfg-preview"><p>从左侧添加组件，或把素材拖到下方轨道。</p></div><div class="cfg-preview-controls"><button id="cfg-check">检查安排</button><button id="cfg-preview-play">播放本期预览</button><button id="cfg-preview-stop">停止</button><span id="cfg-duration"></span></div><p class="cfg-help">保存配置记住规则；本期配音和作品目录单独填写。生成得到独立新草稿。</p></section>
 <aside id="cfg-inspector-panel" class="cfg-panel"><header><strong id="cfg-inspector-title">选中项参数</strong><button id="cfg-close-inspector">收起</button></header><div id="cfg-inspector"></div></aside></div>
 <section class="cfg-timeline cfg-panel"><header><button id="cfg-undo">撤销</button><button id="cfg-redo">重做</button><button id="cfg-properties">输出设置</button><span id="cfg-time-label">排列顺序 · 卡片宽度不代表时长</span><label>缩放 <input id="cfg-zoom" type="range" min="12" max="80" value="32"></label></header><div id="cfg-lanes"></div></section>
 <footer><p id="cfg-status" role="status">先添加画面或配音，逐步搭建。</p></footer>`;
 document.querySelector('.app-shell').append(page);
 const msg=text=>$('cfg-status').textContent=text;
 const key=()=>JSON.stringify(config);
 const state=()=>({config:clone(config),episode:clone(episode),selected:clone(selected),ready:[...readyRanges]});
 function remember(){undo.push(state());if(undo.length>80)undo.shift();redo=[];}
 function changed(){checked=null;stopPlayback();render();}
 function change(action){remember();action();changed();}
 function restore(s){config=clone(s.config);episode=clone(s.episode);selected=clone(s.selected);readyRanges=new Set(s.ready);changed();}
 function setRole(id,role){roles[id]=role;try{localStorage.setItem('bingyi-audio-roles',JSON.stringify(roles));}catch{}}
 function select(type,id){selected={type,id};renderInspector();renderPreview();renderLanes();page.classList.add('show-inspector');}
 const info=id=>media.find(m=>m.id===id),sound=id=>audio.find(m=>m.id===id);
 const assetURL=(kind,id,thumb=false)=>'/api/'+(kind==='audio'?'audio/media':'backgrounds/'+(thumb?'thumb':'media'))+'?id='+encodeURIComponent(id);
 const title=(kind,id)=>((kind==='audio'?sound(id):info(id))?.name||'素材丢失，请替换');
 const row=id=>config.sequence.find(r=>r.itemId===id),layer=id=>config.overlays.find(r=>r.slotId===id);
 const seconds=value=>Number(value||0).toFixed(3);
 async function refresh(){const [b,a,p]=await Promise.all([api('/api/backgrounds'),api('/api/audio'),api('/api/roughcut/columns')]);media=b.items;audio=a.items;presets=p.items;$('cfg-open').innerHTML='<option value="">打开配置…</option>'+presets.map(p=>`<option value="${e(p.id)}">${e(p.name)}</option>`).join('');}
 function purpose(value){target=value;filter=['voice','bgm'].includes(value)?'audio':'visual';renderAssets();}
 function renderAssets(){
  const names={main:'主画面：按顺序播放',fill:'尾部补图：图片填满剩余',overlay:'全片图片：持续到配音结束',voice:'配音：决定本期总长',bgm:'背景音乐：默认播完即止'};
  $('cfg-purpose').textContent='添加用途 · '+names[target];
  page.querySelectorAll('[data-cfg-purpose]').forEach(b=>b.classList.toggle('active',b.dataset.cfgPurpose===target));
  const query=$('cfg-search').value.toLowerCase();
  const list=(filter==='audio'?audio:media).filter(v=>v.name.toLowerCase().includes(query));
  $('cfg-asset-list').innerHTML=list.length?list.map(v=>`<article class="cfg-asset" draggable="true" data-cfg-asset="${e(v.id)}" data-kind="${filter==='audio'?'audio':v.kind}">${filter==='visual'?`<img src="${assetURL('visual',v.id,true)}" alt="">`:''}<strong title="${e(v.name)}">${e(v.name)}</strong><small>${filter==='audio'?(roles[v.id]==='voice'?'用途：配音':roles[v.id]==='bgm'?'用途：音乐':'用途未指定'):(v.kind==='video'?'视频':'图片')}${v.duration?' · '+seconds(v.duration)+' 秒':''}${v.missing?' · 文件丢失':''}</small><div>${filter==='audio'?'<button data-cfg-listen>试听</button>':''}<button data-cfg-add>添加</button></div></article>`).join(''):'<p>这里还没有素材，可以导入。</p>';
  $('cfg-asset-list').querySelectorAll('.cfg-asset').forEach(card=>{
   const id=card.dataset.cfgAsset,kind=card.dataset.kind;
   card.ondragstart=event=>event.dataTransfer.setData('application/x-bingyi-asset',JSON.stringify({id,kind}));
   card.querySelector('[data-cfg-add]').onclick=()=>add(id,kind,target);
   const listen=card.querySelector('[data-cfg-listen]');if(listen)listen.onclick=()=>{const player=$('cfg-audition');player.hidden=false;player.src=assetURL('audio',id);player.play().catch(error=>msg(error.message));};
  });
 }
 function add(id,kind,destination,index=null){
  if(['voice','bgm'].includes(destination)&&kind!=='audio'){msg('此轨道需要音频，请选择音频素材。');return;}
  if(!['voice','bgm'].includes(destination)&&kind==='audio'){msg('音频请放到配音或背景音乐轨道。');return;}
  if(['fill','overlay'].includes(destination)&&kind!=='image'){msg('这里仅支持静态图片，视频请放到主画面轨道。');return;}
  if(destination==='overlay'&&config.overlays.length>=16){msg('全片图片最多16层。');return;}
  if(destination==='voice'&&episode.voices.length>=100){msg('配音最多100段。');return;}
  if(['main','fill'].includes(destination)&&config.sequence.length>=500){msg('主画面最多500项。');return;}
  change(()=>{
   if(destination==='voice'){const voice={audio:id};episode.voices.push(voice);setRole(id,'voice');selected={type:'voice',id:episode.voices.length-1};}
   else if(destination==='bgm'){config.bgm=id;setRole(id,'bgm');selected={type:'bgm'};}
   else if(destination==='overlay'){const item={slotId:uid(),image:id,name:title('visual',id),left:2,top:2,width:12,rotation:0};config.overlays.push(item);selected={type:'overlay',id:item.slotId};}
   else {
    const existing=config.sequence.find(r=>r.timing==='remainder');
    if(destination==='fill'&&existing){existing.background=id;selected={type:'main',id:existing.itemId};}
    else {const item={itemId:uid(),background:id,gapBefore:0,sourceStart:0,duration:kind==='video'?Math.min(info(id).duration,3600):5,timing:destination==='fill'?'remainder':'fixed',maxDuration:null,acceptFrameAdjustment:false};
     const fillIndex=config.sequence.findIndex(r=>r.timing==='remainder');const at=destination==='fill'?config.sequence.length:Math.min(index??config.sequence.length,fillIndex<0?config.sequence.length:fillIndex);
     config.sequence.splice(at,0,item);if(kind==='image')readyRanges.add(item.itemId);selected={type:'main',id:item.itemId};}
    config.visualMode='sequence';
   }
  });
  page.classList.add('show-inspector');msg(kind==='audio'?'已按投放轨道指定用途，请试听确认。':kind==='video'?'已添加视频，请在参数栏确认源范围或使用整段。':'已添加图片。');
 }
 function adopt(value){config=clone(value);config.sequence??=[];config.overlays??=[];config.permissions??={background:{asset:config.background||'',mode:'ask'},openingBackground:{asset:config.openingBackground||'',mode:'ask'}};readyRanges=new Set(config.sequence.map(r=>r.itemId));episode={name:config.name+' 新一期',directory:'',voices:[]};selected={type:'settings'};undo=[];redo=[];baseline=key();checked=null;render();}
 function render(){
  $('cfg-name').value=config.name;$('cfg-dirty').textContent=config.revision?(key()===baseline?'已保存':'有未保存修改'):'尚未保存';
  $('cfg-undo').disabled=!undo.length;$('cfg-redo').disabled=!redo.length;
  const total=episode.voices.reduce((n,v)=>n+(sound(v.audio)?.duration||0),0);
  $('cfg-mode').textContent=episode.voices.length?'本期预览 · 配音 '+seconds(total)+' 秒':'配置规则 · 未绑定配音';
  $('cfg-time-label').textContent=checked?.state==='ready'?'实际秒数 · '+seconds(checked.arrangement.durationUs/1e6)+' 秒':'排列顺序 · 卡片宽度不代表时长';
  $('cfg-duration').textContent=checked?.state==='ready'?'安排 '+seconds(checked.arrangement.durationUs/1e6)+' 秒':'';
  renderAssets();renderInspector();renderPreview();renderLanes();
 }
 const choices=(items,value)=>items.map(v=>`<option value="${e(v.id)}" ${v.id===value?'selected':''}>${e(v.name)}</option>`).join('');
 const field=(label,id,value,type='text')=>`<label>${label}<input id="${id}" type="${type}" value="${e(String(value??''))}"></label>`;
 function bind(id,action){$(id).onchange=()=>change(()=>action($(id)));}
 function renderInspector(){
  const box=$('cfg-inspector');let r;
  if(selected.type==='main'&&(r=row(selected.id))){
   const m=info(r.background);box.innerHTML=`<h3>${e(title('visual',r.background))}</h3><label>替换素材<select id="cfg-replace">${choices(media,r.background)}</select></label>${m?.kind==='video'?field('源起点（秒）','cfg-start',r.sourceStart,'number'):''}${r.timing==='remainder'?'<p>填满前面画面之后的剩余时长。</p>':field('使用时长（秒）','cfg-length',r.duration,'number')}${m?.kind==='video'?'<button id="cfg-range">确认源范围</button>':''}<label><input id="cfg-align" type="checkbox" '+(r.acceptFrameAdjustment?'checked':'')+'>允许调整到完整视频帧</label><div class="cfg-actions"><button id="cfg-earlier">向前</button><button id="cfg-later">向后</button><button id="cfg-remove">删除</button></div>`;
   bind('cfg-replace',el=>{r.background=el.value;r.timing='fixed';r.sourceStart=0;r.duration=info(el.value)?.duration||5;readyRanges.delete(r.itemId);if(info(el.value)?.kind==='image')readyRanges.add(r.itemId);});
   if($('cfg-start'))bind('cfg-start',el=>{r.sourceStart=Number(el.value);readyRanges.delete(r.itemId);});
   if($('cfg-length'))bind('cfg-length',el=>{r.duration=Number(el.value);readyRanges.delete(r.itemId);if(m?.kind==='image')readyRanges.add(r.itemId);});
   bind('cfg-align',el=>r.acceptFrameAdjustment=el.checked);
   const gap=document.createElement('div');gap.innerHTML=field('此片段前留空（秒）','cfg-gap-before',r.gapBefore||0,'number');box.insertBefore(gap,box.querySelector('.cfg-actions'));bind('cfg-gap-before',el=>r.gapBefore=Number(el.value));
   const position=document.createElement('p');let start=0;for(const item of config.sequence){start+=item.gapBefore||0;if(item.itemId===r.itemId)break;start+=item.duration;}position.textContent='主画面相对起点 '+seconds(start)+' 秒'+(r.timing==='fixed'?' → 终点 '+seconds(start+r.duration)+' 秒':' → 填满至本期结束');gap.append(position);
   if($('cfg-range'))$('cfg-range').onclick=()=>{if(r.sourceStart<0||r.duration<=0||r.sourceStart+r.duration>m.duration+.001){msg('源范围超出视频，请调整起点和时长。');return;}change(()=>readyRanges.add(r.itemId));msg('源范围已确认。');};
   if(m?.kind==='video'){const whole=document.createElement('button');whole.textContent='使用整段并确认';whole.id='cfg-use-whole';whole.onclick=()=>change(()=>{r.sourceStart=0;r.duration=m.duration;r.acceptFrameAdjustment=true;readyRanges.add(r.itemId);});$('cfg-range').after(whole);}
   const duplicate=document.createElement('button');duplicate.id='cfg-duplicate';duplicate.textContent='复制片段';duplicate.onclick=()=>{if(r.timing==='remainder'){msg('尾部补图保持一项，请先添加固定画面。');return;}change(()=>{const item={...clone(r),itemId:uid(),gapBefore:0};config.sequence.splice(config.sequence.indexOf(r)+1,0,item);if(readyRanges.has(r.itemId))readyRanges.add(item.itemId);selected={type:'main',id:item.itemId};});};box.querySelector('.cfg-actions').append(duplicate);
   $('cfg-earlier').onclick=()=>moveMain(r.itemId,-1);$('cfg-later').onclick=()=>moveMain(r.itemId,1);$('cfg-remove').onclick=()=>change(()=>{config.sequence=config.sequence.filter(v=>v.itemId!==r.itemId);selected={type:'settings'};});
  }else if(selected.type==='overlay'&&(r=layer(selected.id))){
   box.innerHTML=`<h3>全片图片</h3><label>图片<select id="cfg-overlay-image">${choices(media.filter(v=>v.kind==='image'),r.image)}</select></label>${field('距左边 %','cfg-left',r.left,'number')}${field('距上边 %','cfg-top',r.top,'number')}${field('宽度占画面 %','cfg-width',r.width,'number')}${field('旋转角度','cfg-rotation',r.rotation,'number')}<button id="cfg-remove">删除图片层</button>`;
   bind('cfg-overlay-image',el=>r.image=el.value);for(const [id,key]of [['left','left'],['top','top'],['width','width'],['rotation','rotation']])bind('cfg-'+id,el=>r[key]=Number(el.value));$('cfg-remove').onclick=()=>change(()=>{config.overlays=config.overlays.filter(v=>v.slotId!==r.slotId);selected={type:'settings'};});
   for(const [label,delta]of [['置前一层',1],['置后一层',-1]]){const b=document.createElement('button');b.textContent=label;b.onclick=()=>{const i=config.overlays.indexOf(r),j=i+delta;if(j<0||j>=config.overlays.length)return;change(()=>{[config.overlays[i],config.overlays[j]]=[config.overlays[j],config.overlays[i]];});};box.append(b);}
  }else if(selected.type==='voice'&&(r=episode.voices[selected.id])){
   box.innerHTML=`<h3>本期配音</h3><p>${e(title('audio',r.audio))} · ${seconds(sound(r.audio)?.duration)} 秒</p><audio controls src="${assetURL('audio',r.audio)}"></audio><label>替换配音<select id="cfg-voice">${choices(audio,r.audio)}</select></label>${selected.id===0?'<label><input id="cfg-opening" type="checkbox" '+(r.opening?'checked':'')+'>此段为开场配音</label>':''}<button id="cfg-remove">删除配音</button>`;
   bind('cfg-voice',el=>{r.audio=el.value;setRole(el.value,'voice');});if($('cfg-opening'))bind('cfg-opening',el=>r.opening=el.checked);$('cfg-remove').onclick=()=>change(()=>{episode.voices.splice(selected.id,1);selected={type:'settings'};});
  }else if(selected.type==='bgm'){
   box.innerHTML=`<h3>背景音乐</h3><label>音乐<select id="cfg-music"><option value="">不使用</option>${choices(audio,config.bgm)}</select></label>${config.bgm?`<audio controls src="${assetURL('audio',config.bgm)}"></audio>`:''}${field('音量倍率（1 = 0 dB）','cfg-volume',config.bgmVolume,'number')}<label><input id="cfg-loop" type="checkbox" ${config.bgmLoop?'checked':''}>播完后循环</label><p>默认播完即止，视频原声关闭。</p>`;bind('cfg-music',el=>config.bgm=el.value);bind('cfg-volume',el=>config.bgmVolume=Number(el.value));bind('cfg-loop',el=>config.bgmLoop=el.checked);
  }else{
   box.innerHTML=`<h3>本期与输出</h3>${field('本期名称','cfg-episode',episode.name)}${field('作品目录（本期）','cfg-directory',episode.directory)}<button id="cfg-pick-episode">选择作品目录</button>${field('剪映草稿目录（配置）','cfg-drafts',config.draftDirectory)}<button id="cfg-pick-drafts">选择草稿目录</button><details><summary>画布与开场</summary>${field('宽','cfg-canvas-w',config.width,'number')}${field('高','cfg-canvas-h',config.height,'number')}${field('帧率','cfg-fps',config.fps,'number')}<label>开场画面<select id="cfg-opening-image"><option value="">不使用</option>${choices(media,config.openingBackground)}</select></label><label>开场时长规则<select id="cfg-opening-policy">${['ask','trim','loop'].map(v=>`<option value="${v}" ${config.permissions.openingBackground?.mode===v?'selected':''}>${({ask:'不自动处理',trim:'允许截取',loop:'允许循环'})[v]}</option>`).join('')}</select></label></details>${config.visualMode!=='sequence'?'<p>此配置使用单画面铺底。</p><button id="cfg-convert">改为顺序画面</button>':''}`;
   bind('cfg-episode',el=>episode.name=el.value);bind('cfg-directory',el=>episode.directory=el.value);bind('cfg-drafts',el=>config.draftDirectory=el.value);for(const [id,key]of [['canvas-w','width'],['canvas-h','height'],['fps','fps']])bind('cfg-'+id,el=>config[key]=Number(el.value));
   const policy=document.createElement('label');policy.innerHTML='本期结束依据<select id="cfg-duration-policy"><option value="voice">以配音结束为准</option><option value="timeline">以配音和主画面最晚结束为准</option></select>';box.prepend(policy);$('cfg-duration-policy').value=config.durationPolicy||'voice';bind('cfg-duration-policy',el=>config.durationPolicy=el.value);
   bind('cfg-opening-image',el=>{config.openingBackground=el.value;config.permissions.openingBackground={asset:el.value,mode:'ask'};});bind('cfg-opening-policy',el=>config.permissions.openingBackground={asset:config.openingBackground,mode:el.value});
   $('cfg-pick-episode').onclick=()=>run(async()=>{const v=await api('/api/settings/choose-folder',{target:'episode'});if(v.path)change(()=>episode.directory=v.path);});$('cfg-pick-drafts').onclick=()=>run(async()=>{const v=await api('/api/settings/choose-folder',{target:'draft'});if(v.path)change(()=>config.draftDirectory=v.path);});
   if($('cfg-convert'))$('cfg-convert').onclick=()=>change(()=>{config.visualMode='sequence';config.sequence=[];});
  }
 }
 function moveMain(id,delta){const i=config.sequence.findIndex(v=>v.itemId===id),j=i+delta;if(j<0||j>=config.sequence.length||config.sequence[i].timing==='remainder'||config.sequence[j].timing==='remainder')return;change(()=>{[config.sequence[i],config.sequence[j]]=[config.sequence[j],config.sequence[i]];});}
 function plannedLayout(){
  if(config.visualMode!=='sequence'||!config.sequence.length)return null;
  const fps=config.fps;if(![24,25,30,60].includes(fps))return null;let cursor=episode.voices[0]?.opening?Math.ceil((sound(episode.voices[0].audio)?.duration||0)*fps):0;const rows=[];
  for(const r of config.sequence){const m=info(r.background);if(!m||m.kind==='video'&&!readyRanges.has(r.itemId))return null;const gap=Number(r.gapBefore||0),length=Number(r.duration);if(!Number.isFinite(gap)||gap<0||!Number.isFinite(length)||length<=0)return null;const gapStartFrame=cursor;cursor+=Math.round(gap*fps);const startFrame=cursor;if(r.timing==='remainder'){rows.push({itemId:r.itemId,asset:r.background,startFrame,endFrame:cursor,durationUs:0,gapStartFrame,gapEndFrame:startFrame,pending:true});break;}let frames=m.kind==='video'?Math.floor(length*fps+1e-8):Math.round(length*fps);if(frames<1)return null;while(m.kind==='video'&&frames&&Math.round((cursor+frames)*1e6/fps)-Math.round(cursor*1e6/fps)>Math.round(length*1e6))frames--;cursor+=frames;rows.push({itemId:r.itemId,asset:r.background,startFrame,endFrame:cursor,durationUs:Math.round(cursor*1e6/fps)-Math.round(startFrame*1e6/fps),gapStartFrame,gapEndFrame:startFrame,sourceStartUs:Math.round((r.sourceStart||0)*1e6)});}
  return {durationUs:Math.round(cursor*1e6/fps),sequence:rows};
 }
 function renderLanes(){
  const voiceEnd=episode.voices.reduce((n,v)=>n+(sound(v.audio)?.duration||0),0),fixed=config.sequence.reduce((n,v)=>n+(v.gapBefore||0)+(v.timing==='fixed'?v.duration:0),0),hasFill=config.sequence.some(v=>v.timing==='remainder');
  const total=config.durationPolicy==='timeline'?Math.max(voiceEnd,fixed):voiceEnd;
  const scale=Number($('cfg-zoom').value),verified=checked?.state==='ready',layout=verified?checked.arrangement:plannedLayout(),resolved=!!layout;
  if(!verified)$('cfg-time-label').textContent=layout?'已排画面秒尺 · '+seconds(layout.durationUs/1e6)+' 秒 · 待本期校验':'排列顺序 · 卡片宽度不代表时长';
  $('cfg-lanes').classList.toggle('cfg-timed',resolved);
  const card=(type,id,label,detail,img)=>{let duration=0;if(resolved){if(type==='main')duration=layout.sequence.find(v=>v.itemId===id)?.durationUs/1e6||0;else if(type==='voice')duration=sound(episode.voices[id]?.audio)?.duration||0;else if(type==='bgm')duration=config.bgmLoop?layout.durationUs/1e6:Math.min(sound(config.bgm)?.duration||0,layout.durationUs/1e6);else if(verified)duration=layout.durationUs/1e6;}
   return `<button draggable="${type==='main'||type==='voice'||type==='overlay'}" class="cfg-clip ${selected.type===type&&String(selected.id)===String(id)?'selected':''}" ${resolved&&duration?`style="width:${duration*scale}px;min-width:${duration*scale}px"`:''} data-type="${type}" data-id="${e(String(id))}">${img?`<img alt="" src="${assetURL('visual',img,true)}">`:''}<strong>${e(label)}</strong><small>${e(detail)}</small></button>`;};
  const openingFrames=resolved&&layout.sequence.length?layout.sequence[0].gapStartFrame||0:0;
  const openingCard=openingFrames?`<button class="cfg-clip" data-type="settings" data-id="" style="width:${openingFrames/config.fps*scale}px;min-width:${openingFrames/config.fps*scale}px">开场画面<br>${seconds(openingFrames/config.fps)} 秒</button>`:'';
  const main=config.visualMode==='sequence'?openingCard+config.sequence.map(r=>{const position=layout?.sequence.find(v=>v.itemId===r.itemId),gap=position?(position.gapEndFrame-position.gapStartFrame)/config.fps:r.gapBefore||0;return (gap?`<div class="cfg-gap" ${resolved?`style="width:${gap*scale}px;min-width:${gap*scale}px"`:''}>空隙 ${seconds(gap)} 秒</div>`:'')+card('main',r.itemId,title('visual',r.background),r.timing==='remainder'?'填满剩余':seconds(r.duration)+' 秒'+(info(r.background)?.kind==='video'&&!readyRanges.has(r.itemId)?' · 待确认源范围':''),r.background);}).join(''):card('settings','',title('visual',config.background),'单画面铺底',config.background);
  const rows=[['overlay','全片图片',config.overlays.map(r=>card('overlay',r.slotId,title('visual',r.image),'全片持续',r.image)).join('')],['main','主画面',main],['voice','配音',episode.voices.map((r,i)=>card('voice',i,title('audio',r.audio),seconds(sound(r.audio)?.duration)+' 秒')).join('')],['bgm','背景音乐',config.bgm?card('bgm','',title('audio',config.bgm),(config.bgmLoop?'允许循环':'播完即止')+' · 倍率 '+config.bgmVolume):'']];
  const extent=layout?Math.max(layout.durationUs/1e6,voiceEnd):0;
  $('cfg-lanes').innerHTML=(resolved?`<div class="cfg-ruler" style="margin-left:105px;display:flex">${Array.from({length:Math.min(10801,Math.ceil(extent)+1)},(_,i)=>`<span style="width:${scale}px;flex:none;font-size:10px">${i}s</span>`).join('')}</div>`:'')+rows.map(([type,label,cards])=>`<div class="cfg-lane" data-lane="${type}"><button class="cfg-lane-label">${label} ＋</button><div class="cfg-lane-cards" ${resolved&&type==='overlay'?'style="display:grid"':''}>${cards||'<span>拖入素材，或点击左侧「添加」</span>'}${type==='main'&&config.visualMode==='sequence'&&total>fixed&&!hasFill?`<button id="cfg-fill-gap" class="cfg-gap">缺少约 ${seconds(total-fixed)} 秒<br>用图片补满</button>`:''}</div></div>`).join('');
  $('cfg-lanes').querySelectorAll('[data-type]').forEach(b=>{b.onclick=()=>select(b.dataset.type,b.dataset.id===''?undefined:b.dataset.type==='voice'?Number(b.dataset.id):b.dataset.id);b.ondragstart=ev=>ev.dataTransfer.setData('application/x-bingyi-component',JSON.stringify({type:b.dataset.type,id:b.dataset.id}));});
  $('cfg-lanes').querySelectorAll('[data-lane]').forEach(l=>{l.querySelector('.cfg-lane-label').onclick=()=>{purpose(l.dataset.lane);page.classList.add('show-assets');};l.ondragover=ev=>{ev.preventDefault();ev.dataTransfer.dropEffect='copy';};l.ondrop=ev=>{ev.preventDefault();try{const component=ev.dataTransfer.getData('application/x-bingyi-component');const hit=ev.target.closest('[data-type]');if(component){const v=JSON.parse(component);if(v.type!==l.dataset.lane){msg('组件只能在同类轨道内重新排列。');return;}reorder(v.type,v.id,hit?.dataset.id);return;}const v=JSON.parse(ev.dataTransfer.getData('application/x-bingyi-asset'));const index=hit?.dataset.type==='main'?config.sequence.findIndex(v=>v.itemId===hit.dataset.id):null;add(v.id,v.kind,l.dataset.lane,index);}catch{msg('请从左侧素材区拖入素材。');}};});
  if($('cfg-fill-gap'))$('cfg-fill-gap').onclick=()=>{purpose('fill');page.classList.add('show-assets');msg('选择一张图片，添加后自动填满尾部缺口。');};
  const ruler=$('cfg-lanes').querySelector('.cfg-ruler');if(ruler){ruler.title='点击秒尺预览对应位置';ruler.style.cursor='crosshair';ruler.onclick=event=>{const time=Math.max(0,Math.min(extent,(event.clientX-ruler.getBoundingClientRect().left)/scale));scrub(time,layout);};}
 }
 function reorder(type,id,before){const list=type==='main'?config.sequence:type==='voice'?episode.voices:config.overlays;const at=type==='voice'?Number(id):list.findIndex(v=>(type==='main'?v.itemId:v.slotId)===id);if(at<0||before===id||type==='main'&&list[at]?.timing==='remainder')return;change(()=>{const item=list.splice(at,1)[0];let index=before===undefined?list.length:type==='voice'?Math.min(Number(before),list.length):list.findIndex(v=>(type==='main'?v.itemId:v.slotId)===before);if(index<0)index=list.length;if(type==='main'){const fill=list.findIndex(v=>v.timing==='remainder');if(fill>=0)index=Math.min(index,fill);}list.splice(index,0,item);if(type==='voice'){list.forEach((v,i)=>{if(i)v.opening=false;});selected={type,id:index};}});}
 function renderPreview(){
  let id=config.visualMode==='sequence'?config.sequence[0]?.background:config.background;if(selected.type==='main')id=row(selected.id)?.background;
  const m=info(id),preview=$('cfg-preview');preview.style.aspectRatio=config.width+'/'+config.height;
  preview.innerHTML=`<div id="cfg-preview-canvas" style="aspect-ratio:${config.width}/${config.height}">${m?m.kind==='video'?`<video muted controls preload="metadata" src="${assetURL('visual',id)}"></video>`:`<img class="cfg-base" alt="画面预览" src="${assetURL('visual',id)}">`:'<p>添加主画面后在这里预览。</p>'}</div>`;
  for(const r of config.overlays){const img=document.createElement('img');img.src=assetURL('visual',r.image);img.alt=r.name||'全片图片';img.className='cfg-overlay';img.style.cssText=`left:${r.left}%;top:${r.top}%;width:${r.width}%;transform:rotate(${r.rotation}deg)`;$('cfg-preview-canvas').append(img);}
  fitCanvas();
  if(selected.type==='main'&&m?.kind==='video'){const v=preview.querySelector('video');v.addEventListener('loadedmetadata',()=>{v.currentTime=row(selected.id)?.sourceStart||0;},{once:true});}
 }
 function fitCanvas(){const holder=$('cfg-preview'),canvas=$('cfg-preview-canvas');if(!canvas||!holder.clientWidth||!holder.clientHeight)return;const ratio=config.width/config.height,w=Math.min(holder.clientWidth,holder.clientHeight*ratio);canvas.style.width=w+'px';canvas.style.height=w/ratio+'px';}
 new ResizeObserver(fitCanvas).observe($('cfg-preview'));
 function scrub(time,layout){stopPlayback();renderPreview();const sequence=layout.sequence;const segment=sequence.find(v=>time>=v.startFrame/config.fps&&time<v.endFrame/config.fps);let id=segment?.asset||config.background;const intro=episode.voices[0]?.opening&&(sound(episode.voices[0].audio)?.duration||0);if(!segment&&intro&&time<intro)id=config.openingBackground;const canvas=$('cfg-preview-canvas');canvas.querySelector('.cfg-base,video')?.remove();if(id){const m=info(id),el=document.createElement(m?.kind==='video'?'video':'img');el.className='cfg-base';el.src=assetURL('visual',id);if(m?.kind==='video'){el.muted=true;el.addEventListener('loadedmetadata',()=>{const offset=segment?segment.sourceStartUs/1e6+time-segment.startFrame/config.fps:time;el.currentTime=Math.min(offset,el.duration);},{once:true});}canvas.prepend(el);}$('cfg-duration').textContent='预览位置 '+seconds(time)+' 秒';}
 let playing=[],playTimer=null;
 function stopPlayback(){if(playTimer)clearInterval(playTimer);playTimer=null;for(const p of playing)p.pause();playing=[];const v=$('cfg-preview').querySelector('video');if(v)v.pause();}
 const request=()=>({config:clone(config),voices:clone(episode.voices),name:episode.name||config.name+' 新一期',episodeDirectory:episode.directory});
 async function check(){if(config.sequence.some(r=>info(r.background)?.kind==='video'&&!readyRanges.has(r.itemId)))throw Error('请先确认每段视频的源起点和使用时长。');if(!episode.voices.length)throw Error('请把音频添加到配音轨道，试听确认用途。');checked=await api('/api/roughcut/column-check',request());render();msg(checked.state==='ready'?'安排可生成，共 '+seconds(checked.arrangement.durationUs/1e6)+' 秒。':checked.issues.map(v=>v.message).join('；'));return checked;}
 async function run(action){if(busy)return;busy=true;page.classList.add('busy');const regions=page.querySelectorAll('.cfg-body,.cfg-header,.cfg-timeline');regions.forEach(v=>v.inert=true);try{await action();}catch(error){msg(error.message);}finally{busy=false;page.classList.remove('busy');regions.forEach(v=>v.inert=false);}}
 $('cfg-check').onclick=()=>run(check);
 $('cfg-save').onclick=()=>run(async()=>{if(config.sequence.some(r=>info(r.background)?.kind==='video'&&!readyRanges.has(r.itemId)))throw Error('保存前请确认视频源范围，避免下一期复用未确认的片段。');const saved=await api('/api/roughcut/column-save',clone(config));config=saved;baseline=key();await refresh();render();msg('配置已保存，本期配音与作品目录仍保留在当前工作区。');});
 $('cfg-build').onclick=()=>run(async()=>{if((await check()).state!=='ready')return;const payload={...request(),requestId:uid()};if(editor.snapshot().scenes.length)await api('/api/roughcut/save',editor.snapshot());const project=await api('/api/roughcut/column-build',payload);const result=await api('/api/roughcut/export',project);await editor.openGeneratedProject(project);close();$('cut-directory').value=config.draftDirectory||$('cut-directory').value;$('cut-status').textContent='已生成独立剪映草稿：'+(result.path||result.directory||JSON.stringify(result));});
 $('cfg-name').onchange=()=>change(()=>config.name=$('cfg-name').value);
 $('cfg-new').onclick=()=>{if(key()!==baseline&&!confirm('当前配置尚未保存，仍要新建吗？'))return;adopt(blank());};
 $('cfg-copy').onclick=()=>{config={...clone(config),id:uid(),name:config.name+' 副本'};delete config.revision;baseline='';render();};
 $('cfg-open').onchange=()=>{const p=presets.find(v=>v.id===$('cfg-open').value);if(p){if(key()!==baseline&&!confirm('当前配置尚未保存，仍要打开其他配置吗？'))return;adopt(p);}};
 $('cfg-settings').onclick=$('cfg-properties').onclick=()=>select('settings');
 $('cfg-undo').onclick=()=>{if(undo.length){redo.push(state());restore(undo.pop());}};$('cfg-redo').onclick=()=>{if(redo.length){undo.push(state());restore(redo.pop());}};
 $('cfg-visual-tab').onclick=()=>{filter='visual';purpose('main');};$('cfg-audio-tab').onclick=()=>purpose('voice');$('cfg-search').oninput=renderAssets;
 page.querySelectorAll('[data-cfg-purpose]').forEach(b=>b.onclick=()=>purpose(b.dataset.cfgPurpose));
 $('cfg-show-assets').onclick=()=>page.classList.toggle('show-assets');$('cfg-show-inspector').onclick=()=>page.classList.toggle('show-inspector');$('cfg-close-inspector').onclick=()=>page.classList.remove('show-inspector');
 $('cfg-import').onclick=()=>run(async()=>{const base=filter==='audio'?'audio':'backgrounds',picked=await api('/api/'+base+'/pick',{});if(picked.paths?.length){await api('/api/'+base+'/import',{paths:picked.paths});await refresh();renderAssets();msg('素材已导入，请选择用途再添加。');}});
 $('cfg-preview-play').onclick=()=>run(async()=>{if((await check()).state!=='ready')return;stopPlayback();const total=checked.arrangement.durationUs/1e6;let time=0,currentVoice=-1,currentAsset='',activeVoice=null,music=null,previous=performance.now();
  const starts=[];let sum=0;for(const r of episode.voices){starts.push(sum);sum+=sound(r.audio)?.duration||0;}
  if(config.bgm){music=new Audio(assetURL('audio',config.bgm));music.volume=Math.min(1,config.bgmVolume);music.loop=config.bgmLoop;playing.push(music);await music.play();if(config.bgmVolume>1)msg('预览音乐最多原始音量；草稿仍保留设置倍率 '+config.bgmVolume+'。');}
  function tick(){const now=performance.now();time+=(now-previous)/1000;previous=now;if(time>=total){stopPlayback();msg('本期预览结束。');return;}let i=starts.findLastIndex(v=>v<=time);if(i!==currentVoice){if(activeVoice)activeVoice.pause();currentVoice=i;activeVoice=new Audio(assetURL('audio',episode.voices[i].audio));activeVoice.currentTime=Math.max(0,time-starts[i]);playing.push(activeVoice);activeVoice.play().catch(error=>{stopPlayback();msg(error.message);});}
   const segment=checked.arrangement.sequence.find(v=>time>=v.startFrame/config.fps&&time<v.endFrame/config.fps);let id=segment?.asset||config.background;if(!segment&&episode.voices[0]?.opening&&time<(sound(episode.voices[0].audio)?.duration||0))id=config.openingBackground;
   if(!id&&currentAsset!=='gap'){currentAsset='gap';$('cfg-preview-canvas').querySelector('.cfg-base,video')?.remove();}
   const visualKey=(segment?.itemId||(!segment&&episode.voices[0]?.opening&&time<(sound(episode.voices[0].audio)?.duration||0)?'opening':'base'))+':'+id;
   if(id&&visualKey!==currentAsset){currentAsset=visualKey;const m=info(id),canvas=$('cfg-preview-canvas');canvas.querySelector('.cfg-base,video')?.remove();const el=document.createElement(m?.kind==='video'?'video':'img');el.className='cfg-base';el.src=assetURL('visual',id);if(m?.kind==='video'){el.muted=true;el.preload='auto';const seek=segment?(segment.sourceStartUs/1e6+time-segment.startFrame/config.fps):time;const policy=id===config.openingBackground?config.permissions.openingBackground:config.permissions.background;el.loop=!segment&&policy?.mode==='loop';el.addEventListener('loadedmetadata',()=>{if(playTimer===null&&playing.length===0)return;el.currentTime=el.loop?seek%el.duration:Math.min(seek,el.duration);el.play().catch(()=>{});},{once:true});}canvas.prepend(el);}
   $('cfg-duration').textContent=seconds(time)+' / '+seconds(total)+' 秒';
  }
  tick();playTimer=setInterval(tick,50);
 });$('cfg-preview-stop').onclick=stopPlayback;
 $('cfg-zoom').oninput=()=>{renderLanes();$('cfg-lanes').style.setProperty('--cfg-card-width',$('cfg-zoom').value*4+'px');};
 function close(){stopPlayback();$('cfg-audition').pause();page.hidden=true;document.body.classList.remove('configuration-active');$('roughcut-page').hidden=false;window.dispatchEvent(new CustomEvent('workshop-page',{detail:'roughcut'}));window.dispatchEvent(new Event('resize'));}
 $('cfg-back').onclick=close;
 window.addEventListener('workshop-page',event=>{if(event.detail!=='roughcut'&&!page.hidden){stopPlayback();$('cfg-audition').pause();page.hidden=true;document.body.classList.remove('configuration-active');}});
 window.configurationWorkspace={async open(){await refresh();switchPage('roughcut');$('roughcut-page').hidden=true;document.body.classList.remove('studio-active');document.body.classList.add('configuration-active');page.hidden=false;render();},snapshot:()=>state()};
 window.addEventListener('beforeunload',event=>{if(!page.hidden&&key()!==baseline){event.preventDefault();event.returnValue='';}});
})();

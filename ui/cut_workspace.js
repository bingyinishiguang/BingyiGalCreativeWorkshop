/*Editing layout and a real, project-backed timeline.*/
//Recovery events can precede the first usable webview measurement. Retry only
//a bounded number of times, and never persist layout from a hidden viewport.
function createCutLayoutRecovery({measure,frame,delay}) {
  let pending=false,revision=0;
  const schedule=()=>{if(pending)return;pending=true;frame(()=>{pending=false;measure();});};
  const recover=()=>{const token=++revision;schedule();for(const ms of [100,300])delay(()=>{if(token===revision)schedule();},ms);};
  return {schedule,recover};
}
function calculateCutTimelineWidth(end,zoom,viewport,labelWidth=180){return Math.max(1,Math.ceil(end*zoom)+80,Math.ceil(viewport-labelWidth));}
// A fixed pixel tolerance feels the same at every zoom level. Snap only to
// legal, frame-aligned values; offsets allow moving either clip edge together.
function resolveCutSnap(value,{fps=30,zoom=35,targets=[],offsets=[0],min=0,max=10800,enabled=true}={}){
  const frame=v=>Math.round(v*fps)/fps,clamp=v=>Math.max(min,Math.min(max,v));
  let time=clamp(frame(value)),guide=null,distance=Infinity;
  if(enabled)for(const target of targets)for(const offset of offsets){
    if(!Number.isFinite(target)||!Number.isFinite(offset))continue;
    const candidate=frame(target-offset),gap=Math.abs(candidate-value)*zoom;
    if(candidate<min-1e-8||candidate>max+1e-8||gap>8||gap>=distance)continue;
    time=candidate;guide=candidate+offset;distance=gap;
  }
  return {time,guide};
}
if(typeof module!=='undefined')module.exports={createCutLayoutRecovery,calculateCutTimelineWidth,resolveCutSnap};
if(typeof document!=='undefined')
(() => {
  const $=id=>document.getElementById(id), editor=window.cutEditor, v2=window.cutV2, e=editor.escape;
  const root=$('roughcut-page');root.classList.add('editor-mode');
  let splitRatio=.5,leftRatio=.30,rightRatio=.29;
  try{const saved=JSON.parse(localStorage.getItem('bingyi-cut-layout-v1')||'null');if(saved){for(const [k,low,high] of [['split',.25,.8],['left',.18,.35],['right',.18,.35]])if(typeof saved[k]!=='number'||!Number.isFinite(saved[k])||saved[k]<low||saved[k]>high)throw Error('Invalid layout');splitRatio=saved.split;leftRatio=saved.left;rightRatio=saved.right;}}catch{}
  const saveLayout=()=>{try{localStorage.setItem('bingyi-cut-layout-v1',JSON.stringify({split:splitRatio,left:leftRatio,right:rightRatio}));}catch{}};
  const measurable=()=>!root.hidden&&!document.hidden&&window.innerWidth>0&&window.innerHeight>0&&root.getClientRects().length>0;
  const fitWorkspace=()=>{if(!measurable())return;const height=window.innerHeight-root.getBoundingClientRect().top;if(!Number.isFinite(height)||height<=0)return;root.style.height=height+'px';requestAnimationFrame(fitPanels);};
  window.addEventListener('resize',fitWorkspace);
  const top=root.querySelector('.cut-workspace'),assets=top.querySelector('.cut-assets');
  const inspector=top.querySelector('.cut-inspector'),scenesPanel=top.querySelector('.cut-scenes');
  const sceneList=$('cut-scenes'),batchControls=scenesPanel.querySelector('.production-filters');
  const addScene=$('cut-add'),duplicateScene=$('cut-duplicate');
  const preview=document.createElement('section');preview.className='production-panel editor-player';
  preview.innerHTML='<div class="editor-panel-title">画面预览 <small>拖动字幕调整位置</small></div><div id="editor-preview-holder"></div><div id="editor-preview-controls" class="production-actions"></div>';
  preview.querySelector('#editor-preview-holder').append($('cut-preview'));
  preview.querySelector('#editor-preview-controls').append($('dialogue-play'),$('dialogue-stop'),$('dialogue-preview-time').parentElement);
  preview.querySelector('#dialogue-play').textContent='播放预览';
  inspector.innerHTML='<div class="editor-property-tabs production-actions"><button id="editor-scene-tab">镜头</button><button id="editor-dialogue-tab">对白</button><button id="editor-subtitle-tab">默认字幕</button></div><div id="editor-scene-properties"></div><div id="editor-dialogue-properties" hidden></div><div id="editor-subtitle-properties" hidden></div>';
  //The scene form was detached by the old inspector replacement, so rebuild a holder.
  const sceneEditor=document.createElement('div');sceneEditor.id='cut-editor';
  $('editor-scene-properties').append(sceneEditor,$('dialogue-role-order').parentElement);
  $('editor-dialogue-properties').append($('dialogue-editor'));
  $('editor-subtitle-properties').append($('subtitle-default-style'),$('subtitle-save-preset'),$('subtitle-load-preset'),$('subtitle-apply-role'));
  const textTab=document.createElement('button');textTab.id='editor-text-tab';textTab.textContent='文字';inspector.querySelector('.editor-property-tabs').append(textTab);
  const textProperties=document.createElement('div');textProperties.id='editor-text-properties';textProperties.hidden=true;textProperties.append($('text-properties'));inspector.append(textProperties);
  const subtitleNote=document.createElement('p');subtitleNote.textContent='默认值只用于新增对白；已有对白组的样式互相独立。';$('editor-subtitle-properties').prepend(subtitleNote);
  assets.classList.add('editor-assets');
  const audioTab=document.createElement('button');audioTab.type='button';audioTab.id='cut-audio-tab';audioTab.textContent='音频';
  assets.querySelector('.production-actions').append(audioTab);
  const audioAssets=document.createElement('div');audioAssets.id='editor-audio-assets';audioAssets.hidden=true;
  const libraryButton=document.createElement('button');libraryButton.textContent='导入 / 管理音频';libraryButton.onclick=()=>switchPage('audio');audioAssets.append(libraryButton);
  const audioList=document.createElement('div');audioList.id='editor-audio-list';audioAssets.append(audioList);assets.append(audioAssets);
  let audioVisible=false;
  audioTab.onclick=()=>{audioVisible=true;assets.querySelector('#cut-assets').hidden=true;$('cut-asset-search').hidden=true;$('cut-assets-more').hidden=true;audioAssets.hidden=false;$('cut-asset-hint').textContent='点击音频试听；点右下角 ＋ 添加到轨道。';audioTab.classList.add('active');$('cut-bg-tab').classList.remove('active');$('cut-sprite-tab').classList.remove('active');editor.api('/api/audio').then(()=>v2.loadAudio()).then(renderAudioAssets).catch(error=>$('cut-status').textContent=error.message);};
  for(const id of ['cut-bg-tab','cut-sprite-tab'])$(id).addEventListener('click',()=>{audioVisible=false;$('cut-assets').hidden=false;$('cut-asset-search').hidden=false;audioAssets.hidden=true;audioTab.classList.remove('active');});
  top.replaceChildren(assets,preview,inspector);
  top.classList.add('editor-top');
  const timeline=document.createElement('section');timeline.className='production-panel editor-timeline-panel';
  timeline.innerHTML='<div class="editor-timeline-toolbar production-actions"><button id="editor-undo" title="撤销 Ctrl+Z">撤销</button><button id="editor-redo" title="重做 Ctrl+Y">重做</button><span id="editor-timeline-actions"></span><label title="拖动时吸附到片段边缘或播放头；按 Alt 临时关闭"><input id="editor-snap" type="checkbox" checked>吸附</label><label>缩放<input id="editor-zoom" type="range" min="5" max="120" value="35"></label><span id="cut-total"></span></div><div id="editor-timeline-scroll"><div id="editor-timeline-content"></div></div>';
  root.insertBefore(timeline,root.querySelector('.cut-export'));
  $('editor-timeline-actions').append(addScene,duplicateScene,$('dialogue-arrange'),$('dialogue-scenes'),$('dialogue-fit'));
  const quickText=document.createElement('button');quickText.textContent='批量文字';quickText.onclick=()=>{$('text-bulk').click();showProperty('text');};$('editor-timeline-actions').append(quickText);
  const helpers=document.createElement('details');helpers.className='editor-scene-list';
  helpers.innerHTML='<summary>镜头列表 / 批量时长</summary>';
  helpers.append(batchControls,sceneList);
  assets.append(helpers,$('dialogue-gap').parentElement);
  //Remove the redundant standalone dialogue panel only after all controls have moved.
  const redundant=$('dialogue-list').closest('.dialogue-panel');
  const hidden=document.createElement('div');hidden.hidden=true;hidden.append($('dialogue-list'),$('dialogue-timeline'),$('dialogue-status'),$('dialogue-audio'),$('dialogue-add'));root.append(hidden);
  redundant.remove();
  const footer=root.querySelector('.cut-export');footer.classList.add('editor-footer');
  const preflight=document.createElement('details');preflight.className='editor-preflight';preflight.id='editor-preflight';preflight.hidden=true;preflight.innerHTML='<summary id="editor-preflight-summary"></summary><div id="editor-preflight-list"></div>';root.insertBefore(preflight,footer);
  window.addEventListener('cut-preflight-open',()=>{preflight.open=true;});
  const dock=document.createElement('div');dock.className='editor-dock';
  root.insertBefore(dock,top);
  const makeDivider=(label,orientation)=>{const node=document.createElement('div');node.className='editor-divider '+orientation;node.role='separator';node.tabIndex=0;node.setAttribute('aria-label',label);node.setAttribute('aria-orientation',orientation==='horizontal'?'horizontal':'vertical');node.title=label+'：拖动调整，双击恢复';return node;};
  const horizontal=makeDivider('预览与时间轴分隔线','horizontal'),left=makeDivider('素材与预览分隔线','vertical'),right=makeDivider('预览与属性分隔线','vertical');
  top.replaceChildren(assets,left,preview,right,inspector);
  dock.append(top,horizontal,timeline);
  function fitPanels(){if(!measurable()||!dock.clientHeight||!top.clientWidth)return;const available=dock.clientHeight-horizontal.offsetHeight;if(available<=0)return;const upper=available>=295?Math.min(Math.max(170,available*splitRatio),available-125):available*splitRatio;top.style.height=upper+'px';timeline.style.height=(available-upper)+'px';const width=Math.max(0,top.clientWidth-20);const minimum=Math.min(220,width*.24);const l=Math.max(minimum,width*leftRatio),r=Math.max(minimum,width*rightRatio);top.style.gridTemplateColumns=`${l}px 10px minmax(0,1fr) 10px ${r}px`;}
  new ResizeObserver(fitPanels).observe(dock);
  function bindDivider(node,axis,apply,reset){node.onpointerdown=event=>{if(event.button!==0)return;event.preventDefault();node.setPointerCapture(event.pointerId);document.body.classList.add('editor-resizing');node.onpointermove=ev=>{apply(ev);fitPanels();};const finish=()=>{node.onpointermove=null;document.body.classList.remove('editor-resizing');saveLayout();};node.onpointerup=finish;node.onpointercancel=finish;};node.ondblclick=()=>{reset();fitPanels();saveLayout();};node.onkeydown=event=>{const delta=['ArrowRight','ArrowDown'].includes(event.key)?.025:['ArrowLeft','ArrowUp'].includes(event.key)?-.025:0;if(!delta)return;event.preventDefault();if(node===horizontal)splitRatio=Math.max(.25,Math.min(.8,splitRatio+delta));else if(node===left)leftRatio=Math.max(.18,Math.min(.35,leftRatio+delta));else rightRatio=Math.max(.18,Math.min(.35,rightRatio-delta));fitPanels();saveLayout();};}
  bindDivider(horizontal,'y',ev=>{splitRatio=Math.max(.25,Math.min(.8,(ev.clientY-dock.getBoundingClientRect().top)/dock.clientHeight));},()=>splitRatio=.5);
  bindDivider(left,'x',ev=>{leftRatio=Math.max(.18,Math.min(.35,(ev.clientX-top.getBoundingClientRect().left)/top.clientWidth));},()=>leftRatio=.30);
  bindDivider(right,'x',ev=>{rightRatio=Math.max(.18,Math.min(.35,(top.getBoundingClientRect().right-ev.clientX)/top.clientWidth));},()=>rightRatio=.29);
  const focusButton=document.createElement('button');focusButton.textContent='专注剪辑';focusButton.title='收起工坊顶栏，给剪辑区更多空间';root.querySelector('.production-heading').append(focusButton);
  focusButton.onclick=()=>{document.body.classList.toggle('editor-focus');focusButton.textContent=document.body.classList.contains('editor-focus')?'退出专注':'专注剪辑';fitWorkspace();};
  window.addEventListener('workshop-page',event=>{if(event.detail!=='roughcut'){document.body.classList.remove('editor-focus');focusButton.textContent='专注剪辑';}});
  const directory=document.createElement('section');directory.className='editor-directory-bar';
  const directoryLabel=footer.querySelector('label'),directoryRow=$('cut-directory').parentElement;
  directory.append(directoryLabel,directoryRow,footer.querySelector('label[for="cut-material-directory"]'),$('cut-material-directory').parentElement,footer.querySelector('small'));
  root.insertBefore(directory,dock);
  const status=$('cut-status');status.classList.add('editor-status');
  root.querySelector('.production-heading p').textContent='背景 · 人物 · 对白 · 字幕';
  let zoom=35,playhead=0,property='scene',history=[],future=[],restoring=false,lastSnapshot='',issueSignature='',selection={kind:'background',index:editor.activeScene};
  const trackViews=new Map(),labelWidth=180;let currentLanes=[];
  const trackKey=lane=>lane.kind+':'+lane.name;
  const trackView=lane=>trackViews.get(trackKey(lane))||{collapsed:false,locked:false};
  function selectionLocked(){return currentLanes.some(lane=>lane.kind===selection.kind&&trackView(lane).locked&&lane.segments.some(segment=>segment.index===selection.index&&(lane.kind!=='actor'||(segment.actor.slot||0)===selection.slot)));}
  function refuseLockedEdit(){if(!selectionLocked())return false;$('cut-status').textContent='该轨道已锁定，请先解锁再修改时间轴。';return true;}
  function showProperty(which){property=which;for(const name of ['scene','dialogue','subtitle','text','voice']){const panel=$('editor-'+name+'-properties'),tab=$('editor-'+name+'-tab');if(panel)panel.hidden=name!==which;if(tab)tab.classList.toggle('active',name===which);}}
  window.addEventListener('cut-property-request',event=>showProperty(event.detail));
  for(const name of ['scene','dialogue','subtitle','text'])$('editor-'+name+'-tab').onclick=()=>showProperty(name);
  window.addEventListener('cut-visual-selected',event=>{selection={...event.detail};showProperty('scene');renderTimeline();});
  window.addEventListener('cut-text-selected',event=>{selection={kind:'text',index:event.detail.index};showProperty('text');renderTimeline();});
  function renderAudioAssets(){
    const list=$('editor-audio-list');list.replaceChildren();
    v2.audioItems().forEach(item=>{
      const card=document.createElement('div');card.className='audio-asset-card';
      const preview=document.createElement('button');preview.className='audio-row';preview.type='button';
      preview.innerHTML=`<strong>${e(item.name)}</strong><small>${item.duration.toFixed(2)} 秒 · ${item.cues.length} 条字幕</small>`;
      preview.disabled=Boolean(item.missing);preview.title='试听 '+item.name;preview.onclick=()=>editor.previewAsset(item,'audio');
      const add=document.createElement('button');add.type='button';add.dataset.addAudio=item.id;add.textContent='＋';
      add.title='添加到轨道';add.setAttribute('aria-label','添加音频 '+item.name+' 到轨道');add.disabled=Boolean(item.missing);
      add.onclick=event=>{event.stopPropagation();v2.addClip(item);showProperty('dialogue');renderTimeline();};
      card.append(preview,add);list.append(card);
    });
    if(!list.children.length)list.textContent='先导入配音、BGM 或音效。';
  }
  function secondsText(time){const minutes=Math.floor(time/60);return `${minutes}:${(time%60).toFixed(2).padStart(5,'0')}`;}
  function sceneRanges(){let cursor=0;const fps=Number($('cut-fps').value);return editor.scenes.map((s,index)=>{const start=cursor;cursor+=Math.round(s.duration*fps)/fps;return {scene:s,index,start,end:cursor};});}
  function snapTargets(kind,index){
    const p=editor.snapshot(),ranges=sceneRanges(),own=kind==='scene'?ranges[index]:p[kind==='audio'?'audioClips':'textClips'][index];
    const ownStart=own.start,ownEnd=own.end??own.start+own.duration;
    const edges=[...ranges.flatMap(r=>[r.start,r.end]),...(p.audioClips||[]).flatMap(c=>[c.start,c.start+c.duration]),...(p.textClips||[]).flatMap(c=>[c.start,c.start+c.duration])];
    // Do not magnetize a clip back to its original position, even where a
    // linked subtitle duplicates that edge. Zero and the playhead remain useful.
    return [...new Set([0,playhead,...edges.filter(t=>Math.abs(t-ownStart)>1e-8&&Math.abs(t-ownEnd)>1e-8)])];
  }
  function snapTime(value,event,targets,limits={}){
    const result=resolveCutSnap(value,{fps:Number($('cut-fps').value),zoom,targets,...limits,enabled:$('editor-snap').checked&&!event.altKey});
    const guide=$('editor-snap-guide');if(guide){guide.hidden=result.guide===null;if(!guide.hidden)guide.style.left=(labelWidth+result.guide*zoom)+'px';}
    return result.time;
  }
  function clearSnap(){const guide=$('editor-snap-guide');if(guide)guide.hidden=true;}
  function appendTextLanes(lanes,name,kind,segments){const groups=[];[...segments].sort((a,b)=>a.start-b.start).forEach(segment=>{let group=groups.find(g=>g.end<=segment.start);if(!group){group={end:0,segments:[]};groups.push(group);}group.end=segment.end;group.segments.push(segment);});groups.forEach((group,index)=>lanes.push({name:name+(groups.length>1?' · '+(index+1):''),kind,segments:group.segments}));}
  function renderTimeline(){
    const ranges=sceneRanges(),clips=v2.snapshot().audioClips,order=v2.snapshot().roleOrder;
    const texts=window.cutText.snapshot().textClips;
    const checked=window.cutValidation.check(editor.snapshot(),v2.audioItems());
    preflight.hidden=!checked.issues.length;
    $('editor-preflight-summary').textContent=`时间轴提示：${checked.errorCount??checked.issues.filter(i=>i.level==='error').length} 项需修正，${checked.warningCount??checked.issues.filter(i=>i.level==='warning').length} 项提醒（点开定位）${checked.totalIssueCount>checked.issues.length?'；显示 '+checked.issues.length+' 项，优先需修正项':''}`;
    const signature=JSON.stringify(checked.issues);
    if(signature!==issueSignature){issueSignature=signature;
    $('editor-preflight-list').replaceChildren();
    checked.issues.forEach(issue=>{const row=document.createElement('div'),locate=document.createElement('button');locate.textContent=issue.message;locate.onclick=()=>{if(issue.kind==='script'){window.cutScript.open();return;}if(issue.kind==='text')window.cutText.select(issue.index);else v2.selectClip(issue.index,{cueIndex:issue.cueIndex??-1});};row.append(locate);
      if(issue.fix){const fix=document.createElement('button');fix.textContent=issue.fix==='extend'?'延长末镜头':'换到空闲音轨';fix.onclick=()=>{if(issue.fix==='extend')$('dialogue-fit').click();else{const original=v2.snapshot().audioClips[issue.index];let track=0;while(track<16&&v2.snapshot().audioClips.some((c,i)=>i!==issue.index&&c.kind===original.kind&&c.track===track&&original.start<c.start+c.duration&&original.start+original.duration>c.start))track++;if(track<16){v2.updateClip(issue.index,{track});v2.selectClip(issue.index);}else $('cut-status').textContent='没有空闲轨道，请调整片段时间。';}};row.append(fix);} $('editor-preflight-list').append(row);});
    }
    const contentEnd=v2.contentEnd();
    const plotWidth=calculateCutTimelineWidth(Math.max(10,contentEnd),zoom,$('editor-timeline-scroll').clientWidth,labelWidth);
    const step=[1,2,5,10,30,60,120,300,600,1800,3600].find(s=>s*zoom>=65)||3600;
    const ticks=[];for(let t=0;t*zoom<=plotWidth-45;t+=step)ticks.push(`<span style="left:${t*zoom}px">${secondsText(t)}</span>`);
    const lanes=[];
    [...new Set(texts.map(c=>c.track+':'+(c.character||'')))].forEach(key=>appendTextLanes(lanes,'文字 '+(Number(key.split(':')[0])+1)+(key.slice(key.indexOf(':')+1)?' · '+key.slice(key.indexOf(':')+1):''),'text',texts.map((c,index)=>({...c,index,end:c.start+c.duration})).filter(c=>c.track+':'+(c.character||'')===key)));
    const captionClips=clips.flatMap((clip,index)=>clip.subtitles?clip.cues.map((c,cueIndex)=>{const left=Math.max(c.start,clip.sourceStart),right=Math.min(c.end,clip.sourceStart+clip.duration);return {start:clip.start+left-clip.sourceStart,end:clip.start+right-clip.sourceStart,text:c.text,index,cueIndex,role:clip.character||`对白组 ${index+1}`};}).filter(c=>c.end>c.start):[]);
    [...new Set(captionClips.map(c=>c.role))].forEach(role=>appendTextLanes(lanes,'字幕 · '+role,'caption',captionClips.filter(c=>c.role===role)));
    [...(editor.snapshot().overlays||[])].map((row,index)=>({...row,index})).reverse().forEach(row=>lanes.push({name:'全片图片 · '+row.name,kind:'overlay',segments:[{...row,start:0,end:checked.visualEnd}]}));
    [...order].filter(slot=>ranges.some(r=>r.scene.actors.some(a=>(a.slot||0)===slot))).reverse().forEach(slot=>lanes.push({name:'角色 '+(slot+1),kind:'actor',segments:ranges.filter(r=>r.scene.actors.some(a=>(a.slot||0)===slot)).map(r=>({...r,actor:r.scene.actors.find(a=>(a.slot||0)===slot)}))}));
    lanes.push({name:'背景',kind:'background',segments:ranges});
    const groups=[...new Set(clips.map(c=>c.kind+':'+c.track))];
    for(const key of groups){const [kind,track]=key.split(':');lanes.push({name:({dialogue:'对白',bgm:'BGM',effect:'音效'}[kind])+' '+(Number(track)+1),kind:'audio',audioKind:kind,track:Number(track),segments:clips.map((c,index)=>({...c,index,end:c.start+c.duration})).filter(c=>c.kind+':'+c.track===key)});}
    currentLanes=lanes;
    const html=lanes.map(lane=>`<div class="editor-lane ${trackView(lane).collapsed?'track-collapsed':''} ${trackView(lane).locked?'track-locked':''}" data-track-key="${e(trackKey(lane))}" data-lane="${lane.kind}" ${lane.kind==='audio'?`data-kind="${lane.audioKind}" data-track="${lane.track}"`:''}><strong><span title="${e(lane.name)}">${e(lane.name)}</span><span class="editor-track-controls"><button type="button" data-track-collapse aria-pressed="${trackView(lane).collapsed}" title="${trackView(lane).collapsed?'显示':'收起'}时间轴片段，不影响预览与导出">${trackView(lane).collapsed?'显示':'收起'}</button><button type="button" data-track-lock aria-pressed="${trackView(lane).locked}" title="${trackView(lane).locked?'解锁':'锁定'}时间轴拖动、裁切和删除">${trackView(lane).locked?'解锁':'锁定'}</button></span></strong><div class="editor-lane-plot" style="width:${plotWidth}px">${lane.segments.map(s=>{
      const left=s.start*zoom,width=Math.max(3,(s.end-s.start)*zoom);
      let label=s.text||'',thumb='',data='';
      if(lane.kind==='audio'){label=v2.audioItems().find(i=>i.id===s.audio)?.name||s.character||'音频';data=`data-audio-index="${s.index}"`;}
      if(lane.kind==='caption')data=`data-caption-index="${s.index}" data-cue-index="${s.cueIndex}"`;
      if(lane.kind==='text')data=`data-text-index="${s.index}"`;
      if(lane.kind==='overlay'){label=s.name;thumb='/api/backgrounds/thumb?id='+encodeURIComponent(s.image);data=`data-overlay-index="${s.index}"`;}
      if(lane.kind==='background'){const sceneButton=$('cut-scenes').children[s.index];label=sceneButton?.querySelector('strong')?.textContent||'背景';thumb=sceneButton?.querySelector('img')?.src||'';data=`data-scene-index="${s.index}"`;}
      if(lane.kind==='actor'){label='角色 '+(s.actor.slot+1);thumb='/api/library/image?id='+encodeURIComponent(s.actor.id)+'&thumb=1';data=`data-scene-index="${s.index}" data-actor-slot="${s.actor.slot||0}"`;}
      const selected=selection.kind===lane.kind&&selection.index===s.index&&(lane.kind!=='actor'||selection.slot===(s.actor.slot||0))&&(lane.kind!=='caption'||selection.cueIndex===s.cueIndex);
      const issues=checked.issues.filter(i=>i.kind===lane.kind&&i.index===s.index&&(lane.kind!=='caption'||i.cueIndex===s.cueIndex));
      return `<button type="button" ${trackView(lane).locked?'disabled':''} class="editor-segment ${lane.kind}${selected?' selected':''}${issues.length?' has-issue':''}" aria-pressed="${selected}" style="left:${left}px;width:${width}px" ${data} title="${e(label)} · ${secondsText(s.start)}—${secondsText(s.end)}${issues.length?' · '+e(issues.map(i=>i.message).join('；')):''}">${thumb?`<img src="${e(thumb)}" alt="">`:''}<span>${e(label)}</span>${lane.kind==='audio'?'<i class="trim-handle trim-left" data-trim="left"></i><i class="trim-handle trim-right" data-trim="right"></i>':['background','text'].includes(lane.kind)?'<i class="trim-handle trim-right" data-trim="scene"></i>':''}</button>`;
    }).join('')}</div></div>`).join('');
    $('editor-timeline-content').style.width=(plotWidth+labelWidth)+'px';
    $('editor-timeline-content').innerHTML=`<div class="editor-ruler"><strong>时间轴</strong><div style="width:${plotWidth}px">${ticks.join('')}</div></div>${html}<div id="editor-playhead" style="left:${labelWidth+playhead*zoom}px"><b></b></div><div id="editor-snap-guide" hidden aria-hidden="true"></div>`;
    fitTracks();
    $('editor-timeline-content').querySelectorAll('[data-track-collapse],[data-track-lock]').forEach(button=>button.onclick=()=>{const row=button.closest('[data-track-key]'),key=row.dataset.trackKey,view={collapsed:false,locked:false,...trackViews.get(key)};const property=button.hasAttribute('data-track-lock')?'locked':'collapsed';view[property]=!view[property];trackViews.set(key,view);renderTimeline();});
    $('editor-timeline-content').querySelectorAll('[data-overlay-index]').forEach(b=>b.onclick=()=>window.dispatchEvent(new Event('column-layer-open')));
    $('editor-timeline-content').querySelectorAll('[data-scene-index]').forEach(b=>{
      b.onclick=()=>{const index=Number(b.dataset.sceneIndex);if(!v2.isPlaying())v2.locate(ranges[index].start);editor.selectScene(index,b.dataset.actorSlot??'background');};
      b.onpointerdown=event=>{if(event.target.dataset.trim==='scene')beginSceneTrim(event,b,Number(b.dataset.sceneIndex));};
    });
    $('editor-timeline-content').querySelectorAll('[data-caption-index]').forEach(b=>b.onclick=()=>{v2.selectClip(Number(b.dataset.captionIndex),{cueIndex:Number(b.dataset.cueIndex)});showProperty('dialogue');});
    $('editor-timeline-content').querySelectorAll('[data-text-index]').forEach(b=>{const index=Number(b.dataset.textIndex);b.onclick=()=>window.cutText.select(index);b.onpointerdown=event=>{if(event.button!==0||b.disabled)return;event.preventDefault();const clip=structuredClone(texts[index]),x=event.clientX,trim=event.target.dataset.trim,targets=snapTargets('text',index);let values={};b.setPointerCapture(event.pointerId);b.onpointermove=ev=>{const delta=(ev.clientX-x)/zoom,fps=Number($('cut-fps').value);values=trim?{duration:snapTime(clip.start+clip.duration+delta,ev,targets,{min:clip.start+1/fps,max:Math.min(10800,clip.start+3600)})-clip.start}:{start:snapTime(clip.start+delta,ev,targets,{max:10800-clip.duration,offsets:[0,clip.duration]})};if(trim)b.style.width=values.duration*zoom+'px';else b.style.left=values.start*zoom+'px';};b.onpointerup=()=>{b.onpointermove=null;clearSnap();if(Object.keys(values).length)window.cutText.update(index,values);else window.cutText.select(index);};b.onpointercancel=()=>{b.onpointermove=null;clearSnap();renderTimeline();};};});
    $('editor-timeline-content').querySelectorAll('[data-audio-index]').forEach(b=>{b.onclick=()=>{v2.selectClip(Number(b.dataset.audioIndex));showProperty('dialogue');};b.onpointerdown=event=>beginAudioDrag(event,b,Number(b.dataset.audioIndex));});
    $('editor-timeline-content').querySelector('.editor-ruler>div').onpointerdown=event=>{
      const plot=event.currentTarget,rect=plot.getBoundingClientRect();
      const seek=ev=>{playhead=Math.max(0,Math.min(contentEnd,(ev.clientX-rect.left)/zoom));v2.previewAt(playhead);};
      const scroll=$('editor-timeline-scroll');scroll.setPointerCapture(event.pointerId);seek(event);
      scroll.onpointermove=seek;scroll.onpointerup=()=>{scroll.onpointermove=null;};
    };
  }
  function beginAudioDrag(event,node,index){
    if(event.button!==0||node.disabled)return;event.preventDefault();
    const original=structuredClone(v2.snapshot().audioClips[index]),startX=event.clientX,trim=event.target.dataset.trim;
    const source=v2.audioItems().find(i=>i.id===original.audio),sourceDuration=source?.duration||original.sourceStart+original.duration;
    const targets=snapTargets('audio',index);let values={};node.setPointerCapture(event.pointerId);
    node.onpointermove=ev=>{
      const delta=(ev.clientX-startX)/zoom;
      if(trim==='left'){
        const d=snapTime(original.start+delta,ev,targets,{min:Math.max(0,original.start-original.sourceStart),max:original.start+original.duration-.05})-original.start;
        values={start:original.start+d,sourceStart:original.sourceStart+d,duration:original.duration-d};
      }else if(trim==='right')values={duration:snapTime(original.start+original.duration+delta,ev,targets,{min:original.start+.05,max:Math.min(10800,original.start+sourceDuration-original.sourceStart)})-original.start};
      else values={start:snapTime(original.start+delta,ev,targets,{max:10800-original.duration,offsets:[0,original.duration]})};
      node.style.left=(values.start??original.start)*zoom+'px';node.style.width=(values.duration??original.duration)*zoom+'px';
      const lane=[...$('editor-timeline-content').querySelectorAll('[data-lane="audio"]')].find(row=>{const rect=row.getBoundingClientRect();return ev.clientY>=rect.top&&ev.clientY<=rect.bottom;});
      if(!trim&&lane?.dataset.kind===original.kind&&!lane.classList.contains('track-locked'))values.track=Number(lane.dataset.track);
    };
    node.onpointerup=()=>{node.onpointermove=null;clearSnap();if(Object.keys(values).length){v2.updateClip(index,values);}else v2.selectClip(index);showProperty('dialogue');renderTimeline();};
    node.onpointercancel=()=>{node.onpointermove=null;clearSnap();renderTimeline();};
  }
  function beginSceneTrim(event,node,index){
    if(event.button!==0||node.disabled)return;event.preventDefault();const original=editor.scenes[index].duration,startX=event.clientX,range=sceneRanges()[index],targets=snapTargets('scene',index);let duration=original;
    node.setPointerCapture(event.pointerId);
    node.onpointermove=ev=>{const fps=Number($('cut-fps').value);duration=snapTime(range.start+original+(ev.clientX-startX)/zoom,ev,targets,{min:range.start+1/fps,max:Math.min(10800,range.start+3600)})-range.start;node.style.width=duration*zoom+'px';};
    node.onpointerup=()=>{node.onpointermove=null;clearSnap();if(duration!==original){const copy=structuredClone(editor.scenes);copy[index].duration=duration;editor.setScenes(copy);}editor.selectScene(index);showProperty('scene');};
    node.onpointercancel=()=>{node.onpointermove=null;clearSnap();renderTimeline();};
  }
  function capture(){if(restoring)return;const snapshot=JSON.stringify(editor.snapshot());if(snapshot===lastSnapshot)return;if(lastSnapshot)history.push(lastSnapshot);if(history.length>50)history.shift();lastSnapshot=snapshot;future=[];updateHistoryButtons();}
  function updateHistoryButtons(){$('editor-undo').disabled=!history.length;$('editor-redo').disabled=!future.length;}
  function restore(snapshot){const previous={...selection},time=Number($('dialogue-preview-time').value)||0;restoring=true;editor.restore(JSON.parse(snapshot));editor.markDirty();v2.locate(time);if(['audio','caption'].includes(previous.kind)&&v2.snapshot().audioClips.length){const index=Math.min(previous.index,v2.snapshot().audioClips.length-1);v2.selectClip(index,{cueIndex:previous.kind==='caption'?previous.cueIndex:-1,seek:false});}else if(previous.kind==='text'&&window.cutText.snapshot().textClips.length){window.cutText.select(Math.min(previous.index,window.cutText.snapshot().textClips.length-1),{seek:false});}else{const index=editor.activeScene,target=previous.kind==='actor'&&editor.scenes[index]?.actors.some(a=>(a.slot||0)===previous.slot)?previous.slot:'background';editor.selectScene(index,target);}lastSnapshot=snapshot;restoring=false;updateHistoryButtons();}
  $('editor-undo').onclick=()=>{if(history.length){future.push(lastSnapshot);restore(history.pop());}};
  $('editor-redo').onclick=()=>{if(future.length){history.push(lastSnapshot);restore(future.pop());}};
  $('editor-zoom').oninput=()=>{zoom=Number($('editor-zoom').value);renderTimeline();};
  window.addEventListener('cut-changed',()=>{capture();renderTimeline();});
  window.addEventListener('cut-rendered',()=>{playhead=Number($('dialogue-preview-time').value)||0;if(['actor','background'].includes(selection.kind))selection={...editor.visualSelection};renderTimeline();if(audioVisible)renderAudioAssets();});
  window.addEventListener('cut-clip-selected',event=>{selection={kind:event.detail.cueIndex>=0?'caption':'audio',index:event.detail.index,cueIndex:event.detail.cueIndex};showProperty('dialogue');renderTimeline();});
  window.addEventListener('cut-project-loaded',event=>{if(!restoring){if(event.detail?.preserveHistory){const id=editor.snapshot().id;const identify=s=>JSON.stringify({...JSON.parse(s),id});history=history.map(identify);future=future.map(identify);if(['audio','caption'].includes(selection.kind)&&v2.snapshot().audioClips[selection.index])v2.selectClip(selection.index,{cueIndex:selection.kind==='caption'?selection.cueIndex:-1,seek:false});else if(selection.kind==='text'&&window.cutText.snapshot().textClips[selection.index])window.cutText.select(selection.index,{seek:false});}else{trackViews.clear();history=[];future=[];selection={kind:'background',index:editor.activeScene};}lastSnapshot=JSON.stringify(editor.snapshot());updateHistoryButtons();renderTimeline();}});
  window.addEventListener('workshop-page',event=>{if(event.detail==='roughcut'){fitWorkspace();renderTimeline();renderAudioAssets();if(!lastSnapshot)lastSnapshot=JSON.stringify(editor.snapshot());}});
  window.addEventListener('keydown',event=>{if(root.hidden||root.inert||document.querySelector('dialog[open]')||['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName)||event.target.isContentEditable)return;if((event.ctrlKey||event.metaKey)&&(event.key.toLowerCase()==='z'||event.key.toLowerCase()==='y')){event.preventDefault();if(event.key.toLowerCase()==='y'||event.shiftKey)$('editor-redo').click();else $('editor-undo').click();}});
  let clipboard=null;
  function keyboardSelection(next){if(next.kind==='text')window.cutText.select(next.index);else if(['audio','caption'].includes(next.kind))v2.selectClip(next.index,{cueIndex:next.cueIndex??-1});else editor.selectScene(next.index,next.kind==='actor'?next.slot:'background');}
  window.addEventListener('keydown',event=>{
    if(root.hidden||root.inert||document.querySelector('dialog[open]')||['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName)||event.target.isContentEditable||event.target.closest('[role=separator]'))return;
    const key=event.key.toLowerCase(),modifier=event.ctrlKey||event.metaKey;
    if(event.code==='Space'&&!modifier){if(event.target.closest('button,a,summary,[role="button"]')&&!event.target.closest('#editor-timeline-content'))return;event.preventDefault();if(v2.isPlaying())v2.stopPlayback();else $('dialogue-play').click();return;}
    if(modifier&&key==='s'){event.preventDefault();$('cut-save').click();return;}
    if(['arrowleft','arrowright'].includes(key)&&!modifier){event.preventDefault();v2.locate(Math.max(0,(Number($('dialogue-preview-time').value)||0)+(key==='arrowright'?1:-1)/Number($('cut-fps').value)));return;}
    if(['arrowup','arrowdown'].includes(key)&&!modifier){event.preventDefault();const size=selection.kind==='text'?window.cutText.snapshot().textClips.length:['audio','caption'].includes(selection.kind)?v2.snapshot().audioClips.length:editor.scenes.length;keyboardSelection({...selection,index:Math.max(0,Math.min(size-1,selection.index+(key==='arrowdown'?1:-1)))});return;}
    if(modifier&&key==='c'){const p=structuredClone(editor.snapshot()),clip=selection.kind==='text'?p.textClips[selection.index]:selection.kind==='audio'?p.audioClips[selection.index]:null;if(clip){event.preventDefault();clipboard={kind:selection.kind,clip};}return;}
    if(modifier&&key==='v'&&clipboard){event.preventDefault();if(refuseLockedEdit())return;const p=structuredClone(editor.snapshot()),c=structuredClone(clipboard.clip);c.id=crypto.randomUUID().replaceAll('-','');delete c.sourceRow;delete c.linkedText;delete c.voice;c.start=Number($('dialogue-preview-time').value)||0;const list=clipboard.kind==='text'?p.textClips:p.audioClips;
      if(clipboard.kind==='audio'){let track=0;while(track<16&&list.some(a=>a.kind===c.kind&&a.track===track&&c.start<a.start+a.duration&&c.start+c.duration>a.start))track++;if(track===16){$('cut-status').textContent='没有空闲音轨';return;}c.track=track;}
      if(c.start+c.duration>10800){$('cut-status').textContent='粘贴位置超出三小时时间轴，片段未添加。';return;}
      list.push(c);editor.applyTimeline(p,{coverContent:true});keyboardSelection({kind:clipboard.kind,index:list.length-1});return;}
    if(['delete','backspace'].includes(key)&&!modifier){event.preventDefault();if(refuseLockedEdit())return;const p=structuredClone(editor.snapshot()),previous={...selection};
      if(selection.kind==='text')p.textClips.splice(selection.index,1);
      else if(selection.kind==='audio')p.audioClips.splice(selection.index,1);
      else if(selection.kind==='caption')p.audioClips[selection.index]?.cues.splice(selection.cueIndex,1);
      else if(selection.kind==='actor')p.scenes[selection.index].actors=p.scenes[selection.index].actors.filter(a=>a.slot!==selection.slot);
      else if(selection.kind==='background')p.scenes.splice(selection.index,1);
      editor.applyTimeline(p);const size=previous.kind==='text'?p.textClips.length:['audio','caption'].includes(previous.kind)?p.audioClips.length:p.scenes.length;if(size)keyboardSelection({...previous,index:Math.min(previous.index,size-1)});return;}
  });
  function fitTracks(){if(!measurable())return;const scroll=$('editor-timeline-scroll'),count=scroll.querySelectorAll('.editor-lane').length;if(count&&scroll.clientHeight>0)scroll.style.setProperty('--lane-height',Math.max(44,Math.min(64,Math.floor((scroll.clientHeight-28)/count)))+'px');}
  new ResizeObserver(fitTracks).observe($('editor-timeline-scroll'));
  const fitPreview=()=>{if(!measurable())return;const holder=$('editor-preview-holder'),preview=$('cut-preview');const [w,h]=$('cut-canvas').value.split('x').map(Number);if(!holder.clientWidth||!holder.clientHeight||!Number.isFinite(w/h)||w<=0||h<=0)return;const width=Math.min(holder.clientWidth,holder.clientHeight*w/h),height=width*h/w;if(preview.style.width===width+'px'&&preview.style.height===height+'px')return;preview.style.width=width+'px';preview.style.height=height+'px';if(preview.classList.contains('asset-previewing'))return;v2.renderPreview(preview,editor.activeScene);window.cutText.renderPreview();};
  new ResizeObserver(fitPreview).observe($('editor-preview-holder'));
  window.addEventListener('cut-rendered',fitPreview);
  const recovery=createCutLayoutRecovery({frame:callback=>requestAnimationFrame(callback),delay:(callback,ms)=>setTimeout(callback,ms),measure:()=>{if(!measurable())return;fitWorkspace();fitPanels();renderTimeline();fitTracks();fitPreview();}});
  window.addEventListener('resize',recovery.schedule);
  window.addEventListener('focus',recovery.recover);
  window.addEventListener('pageshow',recovery.recover);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)recovery.recover();});
  window.addEventListener('workshop-page',recovery.recover);
  //Covers title-bar/header changes without a window resize event.
  const containerObserver=new ResizeObserver(recovery.schedule);
  for(const node of [root.parentElement,document.querySelector('.app-header'),root.querySelector('.production-heading')])if(node)containerObserver.observe(node);
  recovery.recover();
  showProperty('scene');editor.render();updateHistoryButtons();
})();

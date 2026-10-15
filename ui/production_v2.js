/*Local audio/dialogue workbench. Provider calls are optional and explicit.*/
(() => {
  const $=id=>document.getElementById(id), editor=window.cutEditor;
  window.cutWrapLegacy=text=>String(text).split('\n').map(line=>{const chars=Array.from(line),parts=[];for(let i=0;i<chars.length;i+=22)parts.push(chars.slice(i,i+22).join(''));return parts.join('\n');}).join('\n');
  const {api,escape:e}=editor;
  const defaults={x:0,y:-.8,size:8,color:'#ffffff',borderColor:'#000000',borderWidth:40,showCharacter:false};
  const kinds={dialogue:'对白',bgm:'BGM',effect:'音效'};
  let audioDetailRevision=0;const audioPendingSaves=new Set();
  window.workshopActivity ||= {};
  window.workshopActivity.audioLibrary=()=>audioPendingSaves.size>0;
  let items=[],selectedAudio='',clips=[],selectedClip=-1,selectedCue=-1,style={...defaults},roleOrder=[0,1],gap=.3;
  let preset={...defaults},previewTime=0,players=[],playTimers=[],playing=false,loadSerial=0,audioContext=null,gainNodes=[],playSerial=0;
  const audioURL=id=>'/api/audio/media?id='+encodeURIComponent(id);
  async function work(status,action) {
    try {return await action();} catch(error){$(status).textContent=error.message;return null;}
  }
  const changed=()=>{editor.markDirty();};
  const input=(label,id,value,type='text',extra='')=>`<label>${label}<input id="${id}" type="${type}" value="${e(value)}" ${extra}></label>`;
  const selectKind=(id,value)=>`<label>类型<select id="${id}">${Object.entries(kinds).map(([key,name])=>`<option value="${key}" ${key===value?'selected':''}>${name}</option>`).join('')}</select></label>`;
  $('audio-library-root').innerHTML=`<div class="production-heading"><div><span class="eyebrow">AUDIO LIBRARY</span><h2>音频库</h2><p>导入配音、BGM 与音效，同名 SRT 会自动尝试匹配。原文件保留。</p></div><button id="audio-import">导入音频</button></div><div class="production-filters"><input id="audio-search" type="search" placeholder="搜索名称、作品、标签、角色或台词"><select id="audio-kind"><option value="">全部音频</option>${Object.entries(kinds).map(([key,name])=>`<option value="${key}">${name}</option>`).join('')}</select><label><input id="audio-trash-view" type="checkbox">回收站</label><span id="audio-count"></span></div><div class="audio-workspace"><section id="audio-list" class="production-panel"></section><aside id="audio-detail" class="production-panel"><p>选择音频试听、编辑素材信息。</p></aside></div><p id="audio-status" class="action-note" role="status"></p>`;
  const panel=document.createElement('section');panel.className='production-panel dialogue-panel';
  panel.innerHTML=`<div class="production-heading"><div><h3>对白与音频时间轴</h3><p>音频可独立分轨。背景和人物沿用所选镜头，也可按对白生成镜头。</p></div><button id="dialogue-library">打开音频库</button></div><div class="production-filters"><label>选择音频<select id="dialogue-audio"><option value="">请选择音频…</option></select></label><button id="dialogue-add">添加片段</button>${input('顺排间隔（秒）','dialogue-gap',gap,'number','min="0" max="10" step="0.1"')}<button id="dialogue-arrange">对白顺排</button><button id="dialogue-scenes">按对白生成镜头</button><button id="dialogue-fit">延长末镜至内容结束</button></div><div id="dialogue-timeline"></div><div class="dialogue-columns"><div id="dialogue-list"></div><div id="dialogue-editor"></div></div><div class="production-filters"><button id="dialogue-play">试听时间轴</button><button id="dialogue-stop">停止</button><label>预览时间（秒）<input id="dialogue-preview-time" type="number" min="0" step="0.1" value="0"></label><label>人物前后层级<select id="dialogue-role-order"><option value="01">角色 2 在前</option><option value="10">角色 1 在前</option></select></label></div><h3>字幕默认样式</h3><p>新对白使用默认样式；每个对白组可单独设置。修改默认值不会联动已有组。</p><div id="subtitle-default-style"></div><div class="production-actions"><button id="subtitle-save-preset">保存为默认预设</button><button id="subtitle-load-preset">载入默认预设</button><button id="subtitle-apply-role">应用当前组样式到同角色</button></div><p id="dialogue-status" class="action-note" role="status"></p>`;
  $('roughcut-page').insertBefore(panel,$('roughcut-page').querySelector('.cut-export'));
  const note=$('roughcut-page').querySelector('.cut-export small');
  note.textContent='每次生成独立草稿，不覆盖已有工程。请直接选择剪映草稿目录；手动搬动文件夹会导致绝对素材路径失效。';

  async function loadAudio() {
    const serial=++loadSerial;
    const result=await api('/api/audio?'+new URLSearchParams({search:$('audio-search').value,kind:$('audio-kind').value,trash:$('audio-trash-view').checked?'1':'0'}));
    if(serial!==loadSerial)return;
    const shown=result.items;
    const all=(await api('/api/audio')).items;
    if(serial!==loadSerial)return;
    items=all;
    $('audio-count').textContent=result.total+' 个音频'+(result.warnings?.length?' · '+result.warnings.length+' 条音频资料暂不可用，原文件已保留':'');
    const list=$('audio-list');list.replaceChildren();
    if(!shown.length)list.textContent='暂无音频，可多选导入。';
    shown.forEach(item=>{
      const row=document.createElement('button');row.type='button';row.className='audio-row';
      row.innerHTML=`<strong>${e(item.name)}</strong><small>${kinds[item.kind]} · ${item.duration.toFixed(3)} 秒 · ${item.kind==='dialogue'?item.cues.length+' 条字幕':e(item.work||'未指定作品')}${item.missing?' · 文件丢失':''}</small>`;
      row.onclick=()=>showAudio(item);list.append(row);
    });
    $('dialogue-audio').innerHTML='<option value="">请选择音频…</option>'+items.filter(i=>!i.missing).map(i=>`<option value="${i.id}">${e(i.name)} · ${i.duration.toFixed(2)} 秒</option>`).join('');
    renderClips();
  }
  function clearAudioDetail(){ audioDetailRevision++;selectedAudio='';$('audio-detail').querySelectorAll('audio').forEach(a=>a.pause());$('audio-detail').replaceChildren(); }
  function showAudio(item) {
    clearAudioDetail();
    selectedAudio=item.id;
    const trash=$('audio-trash-view').checked;
    $('audio-detail').innerHTML=`<h3>${e(item.name)}</h3>${!item.missing&&!trash?`<audio controls preload="metadata" src="${audioURL(item.id)}"></audio>`:''}${input('名称','audio-name',item.name)}${selectKind('audio-edit-kind',item.kind)}${input('作品','audio-work',item.work||'')}${input('标签（用逗号分隔）','audio-tags',(item.tags||[]).join('，'))}<div id="audio-dialogue-fields">${input('角色','audio-character',item.character)}<label>台词原文<textarea id="audio-text" rows="5">${e(item.text)}</textarea></label><p>${item.cues.length} 条字幕</p></div><p>${item.duration.toFixed(3)} 秒</p><div class="production-actions">${trash?'<button id="audio-restore">恢复音频</button>':'<button id="audio-save">保存资料</button><button id="audio-attach-srt">导入 SRT</button><button id="audio-use">加入粗剪</button><button id="audio-trash">移入回收站</button>'}</div>`;
    const syncKind=()=>{const dialogue=$('audio-edit-kind').value==='dialogue';$('audio-dialogue-fields').hidden=!dialogue;if($('audio-attach-srt'))$('audio-attach-srt').hidden=!dialogue;};
    $('audio-detail').querySelectorAll('input,select,textarea').forEach(node=>node.addEventListener('input',()=>audioDetailRevision++));
    $('audio-edit-kind').onchange=syncKind;syncKind();
    if(trash){$('audio-restore').onclick=()=>work('audio-status',async()=>{await api('/api/audio/update',{id:item.id,restore:true,deleted:false});if(selectedAudio===item.id)clearAudioDetail();await loadAudio();$('audio-status').textContent='音频已恢复。';});return;}
    $('audio-save').disabled=audioPendingSaves.has(item.id);
    $('audio-save').onclick=()=>work('audio-status',async()=>{
      if(audioPendingSaves.has(item.id))return;
      const revision=audioDetailRevision,button=$('audio-save');
      const values={id:item.id,name:$('audio-name').value,kind:$('audio-edit-kind').value,character:$('audio-character').value,text:$('audio-text').value,work:$('audio-work').value,tags:$('audio-tags').value.split(/[,，\n]/).map(tag=>tag.trim()).filter(Boolean)};
      audioPendingSaves.add(item.id);button.disabled=true;$('audio-status').textContent='正在保存音频资料…';
      try {
        const saved=await api('/api/audio/update',values);
        let warning='';try{await loadAudio();}catch(error){warning=' 列表刷新失败：'+error.message;}
        const unchanged=selectedAudio===item.id&&audioDetailRevision===revision;
        if(unchanged)showAudio(saved);
        $('audio-status').textContent=(selectedAudio===item.id&&!unchanged?'音频资料已保存；之后的修改仍待保存。':'音频「'+saved.name+'」资料已保存。已加入项目的对白保留独立台词和字幕。')+warning;
      } finally {
        audioPendingSaves.delete(item.id);button.disabled=false;
        if(selectedAudio===item.id){if($('audio-save'))$('audio-save').disabled=false;if($('audio-attach-srt'))$('audio-attach-srt').disabled=false;}
      }
    });
    $('audio-attach-srt').disabled=audioPendingSaves.has(item.id);
    $('audio-attach-srt').onclick=()=>work('audio-status',async()=>{
      if(audioPendingSaves.has(item.id))return;
      const revision=audioDetailRevision,button=$('audio-attach-srt');
      audioPendingSaves.add(item.id);button.disabled=true;$('audio-save').disabled=true;
      try{
        const picked=await api('/api/audio/srt',{});if(picked.cues===null)return;
        const saved=await api('/api/audio/update',{id:item.id,cues:picked.cues});
        let warning='';try{await loadAudio();}catch(error){warning=' 列表刷新失败：'+error.message;}
        const unchanged=selectedAudio===item.id&&audioDetailRevision===revision;
        if(unchanged)showAudio(saved);
        $('audio-status').textContent='音频「'+saved.name+'」字幕已保存。'+(selectedAudio===item.id&&!unchanged?'当前资料修改仍待保存。':'')+warning;
      }finally{
        audioPendingSaves.delete(item.id);button.disabled=false;
        if(selectedAudio===item.id){if($('audio-save'))$('audio-save').disabled=false;if($('audio-attach-srt'))$('audio-attach-srt').disabled=false;}
      }
    });
    $('audio-trash').onclick=()=>work('audio-status',async()=>{await api('/api/audio/update',{id:item.id,deleted:true});if(selectedAudio===item.id)clearAudioDetail();await loadAudio();$('audio-status').textContent='音频已移入回收站。';});
    $('audio-use').onclick=()=>{addClip(item);switchPage('roughcut');};
  }
  function addClip(item) {
    stopPlayback();
    const same=clips.filter(c=>c.kind===item.kind&&c.track===0);
    const start=Math.max(0,...same.map(c=>c.start+c.duration))+(same.length?gap:0);
    clips.push({audio:item.id,start,sourceStart:0,duration:item.duration,track:0,kind:item.kind,volume:1,
      character:item.character,text:item.text,cues:structuredClone(item.cues),subtitles:item.kind==='dialogue',subtitleStyle:structuredClone(style)});
    selectedClip=clips.length-1;editor.ensureCoverage(start+item.duration);changed();window.cutV2.selectClip(selectedClip);
  }
  function renderClips() {
    const list=$('dialogue-list');list.replaceChildren();
    if(!clips.length)list.textContent='从音频库选择素材添加片段。';
    clips.forEach((clip,index)=>{
      const item=items.find(i=>i.id===clip.audio),button=document.createElement('button');
      button.type='button';button.className='audio-row'+(index===selectedClip?' active':'');
      button.innerHTML=`<strong>${index+1}. ${e(item?.name||'音频失效')} ${e(clip.character)}</strong><small>${kinds[clip.kind]} ${clip.track+1} · ${clip.start.toFixed(3)}—${(clip.start+clip.duration).toFixed(3)} 秒 · ${clip.cues.length} 条字幕</small>`;
      button.onclick=()=>{selectedClip=index;previewTime=clip.start;renderClips();renderClipEditor();editor.render();};list.append(button);
    });
    const end=Math.max(1,...clips.map(c=>c.start+c.duration));
    const groups=[...new Set(clips.map(c=>c.kind+':'+c.track))];
    $('dialogue-timeline').innerHTML=groups.map(key=>{const [kind,track]=key.split(':');return `<div class="audio-lane"><strong>${kinds[kind]} ${Number(track)+1}</strong><div>${clips.map((c,i)=>c.kind+':'+c.track===key?`<button type="button" data-clip="${i}" style="left:${c.start/end*100}%;width:${c.duration/end*100}%" title="${e(items.find(a=>a.id===c.audio)?.name||'音频')}">${e(c.character||kinds[kind])}</button>`:'').join('')}</div></div>`;}).join('');
    $('dialogue-timeline').querySelectorAll('[data-clip]').forEach(b=>b.onclick=()=>{selectedClip=Number(b.dataset.clip);renderClips();renderClipEditor();});
  }
  function styleForm(target,current,onChange,prefix) {
    $(target).innerHTML=`<div class="production-filters">${input('X（-1～1）',prefix+'-x',current.x,'number','min="-1" max="1" step="0.01"')}${input('Y（向上为正）',prefix+'-y',current.y,'number','min="-1" max="1" step="0.01"')}${input('字号（剪映单位）',prefix+'-size',current.size,'number','min="2" max="50" step="0.5"')}${input('文字颜色',prefix+'-color',current.color,'color')}${input('描边颜色',prefix+'-borderColor',current.borderColor,'color')}${input('描边宽度',prefix+'-borderWidth',current.borderWidth,'number','min="0" max="100"')}<label><input id="${prefix}-showCharacter" type="checkbox" ${current.showCharacter?'checked':''}>显示角色名</label></div>`;
    Object.keys(defaults).forEach(key=>$(prefix+'-'+key).onchange=event=>{
      current[key]=key==='showCharacter'?event.target.checked:['color','borderColor'].includes(key)?event.target.value:Number(event.target.value);
      onChange();editor.render();
    });
  }
  function renderClipEditor() {
    const clip=clips[selectedClip],target=$('dialogue-editor');
    if(!clip){target.replaceChildren();return;}
    clip.subtitleStyle??=structuredClone(style);
    target.innerHTML=`<h4>对白组 ${selectedClip+1}（独立字幕样式）</h4><div class="production-filters">${selectKind('clip-kind',clip.kind)}${input('角色','clip-character',clip.character)}${input('轨道编号','clip-track',clip.track+1,'number','min="1" max="16"')}${input('开始时间（秒）','clip-start',clip.start,'number','min="0" step="0.01"')}${input('原音频起点','clip-source',clip.sourceStart,'number','min="0" step="0.01"')}${input('播放时长','clip-duration',clip.duration,'number','min="0.001" step="0.01"')}${input('音量倍率','clip-volume',clip.volume,'number','min="0" max="2" step="0.1"')}</div><label>台词原文<textarea id="clip-text" rows="3">${e(clip.text)}</textarea></label><label><input id="clip-subtitles" type="checkbox" ${clip.subtitles?'checked':''}>导出本组字幕</label><div class="production-actions"><button id="clip-import-srt">导入本组 SRT</button><button id="clip-add-cue">添加字幕</button><button id="clip-whole-cue">原文作为整段字幕</button><button id="clip-duplicate">复制到其他轨道</button><button id="clip-remove">删除片段</button></div><p>字幕时间相对于原音频；音频移动时字幕跟随，裁切时仅保留有效部分。长段原文需手动划分时间，未自动对齐。</p><div id="clip-cues" class="cue-scroll"></div><div id="clip-style"></div>`;
    const fields={kind:'kind',character:'character',track:'track',start:'start',source:'sourceStart',duration:'duration',volume:'volume',text:'text'};
    Object.entries(fields).forEach(([key,field])=>$('clip-'+key).onchange=event=>{stopPlayback();clip[field]=['kind','character','text'].includes(key)?event.target.value:Number(event.target.value)-(key==='track'?1:0);changed();renderClips();editor.render();});
    $('clip-subtitles').onchange=event=>{clip.subtitles=event.target.checked;changed();};
    $('clip-import-srt').onclick=()=>work('dialogue-status',async()=>{const result=await api('/api/audio/srt',{});if(result.cues===null)return;clip.cues=result.cues;changed();renderClipEditor();renderClips();editor.render();});
    $('clip-add-cue').onclick=()=>{clip.cues.push({start:clip.sourceStart,end:clip.sourceStart+clip.duration,text:''});changed();renderClipEditor();};
    $('clip-whole-cue').onclick=()=>{if(!clip.text.trim()){$('dialogue-status').textContent='先粘贴台词原文';return;}if(!window.confirm('整段文字将作为一条字幕显示，不会自动对齐句子。长稿建议导入 SRT 或手动分段。'))return;clip.cues=[{start:clip.sourceStart,end:clip.sourceStart+clip.duration,text:clip.text}];changed();renderClipEditor();renderClips();editor.render();};
    $('clip-duplicate').onclick=()=>{const copy=structuredClone(clip);copy.id=crypto.randomUUID().replaceAll('-','');delete copy.linkedText;delete copy.sourceRow;let track=0;while(clips.some(c=>c.kind===copy.kind&&c.track===track&&copy.start<c.start+c.duration&&copy.start+copy.duration>c.start))track++;if(track>15){$('dialogue-status').textContent='没有空闲音频轨道';return;}copy.track=track;clips.push(copy);selectedClip=clips.length-1;changed();renderClips();renderClipEditor();};
    $('clip-remove').onclick=()=>{stopPlayback();clips.splice(selectedClip,1);selectedClip=Math.min(selectedClip,clips.length-1);changed();renderClips();renderClipEditor();editor.render();};
    renderCues();styleForm('clip-style',clip.subtitleStyle,changed,'clip-subtitle');
  }
  function renderCues() {
    const clip=clips[selectedClip];
    $('clip-cues').innerHTML=clip.cues.length?`<table class="cue-table"><thead><tr><th>开始（秒）</th><th>结束（秒）</th><th>字幕文字</th><th></th></tr></thead><tbody>${clip.cues.map((c,i)=>`<tr><td><input type="number" min="0" step="0.01" data-cue="${i}" data-field="start" value="${c.start}"></td><td><input type="number" min="0" step="0.01" data-cue="${i}" data-field="end" value="${c.end}"></td><td><textarea rows="2" data-cue="${i}" data-field="text">${e(c.text)}</textarea></td><td><button data-delete-cue="${i}" type="button">删除</button></td></tr>`).join('')}</tbody></table>`:'<p>暂无字幕。可导入 SRT，或手动添加文字与时间。</p>';
    $('clip-cues').querySelectorAll('[data-cue]').forEach(node=>node.onchange=()=>{clip.cues[Number(node.dataset.cue)][node.dataset.field]=node.dataset.field==='text'?node.value:Number(node.value);changed();renderClips();editor.render();});
    $('clip-cues').querySelectorAll('[data-delete-cue]').forEach(node=>node.onclick=()=>{clip.cues.splice(Number(node.dataset.deleteCue),1);changed();renderCues();renderClips();editor.render();});
    $('clip-cues').querySelectorAll('tbody tr').forEach((row,index)=>row.classList.toggle('selected-cue',index===selectedCue));
  }
  function renderDefaultStyle(){styleForm('subtitle-default-style',style,changed,'subtitle-default');}
  function renderPreview(preview,sceneIndex) {
    previewTime=clampPreviewTime(previewTime);
    $('dialogue-preview-time').max=String(contentEnd());
    preview.querySelectorAll('.dialogue-subtitle').forEach(node=>node.remove());
    $('dialogue-preview-time').value=previewTime.toFixed(3);
    const active=clips.filter(c=>c.subtitles&&previewTime>=c.start&&previewTime<c.start+c.duration);
    active.forEach(clip=>{
      const cues=clip.cues.filter(c=>previewTime-clip.start+clip.sourceStart>=c.start&&previewTime-clip.start+clip.sourceStart<c.end);
      cues.forEach(cue=>{
      const cs=clip.subtitleStyle||style,node=document.createElement('div');node.className='preview-subtitle dialogue-subtitle';
      node.textContent=window.cutWrapLegacy((cs.showCharacter&&clip.character?clip.character+'：':'')+cue.text);node.style.maxWidth='none';node.style.whiteSpace='pre';
      node.style.left=(1+cs.x)*50+'%';node.style.top=(1-cs.y)*50+'%';node.style.color=cs.color;
      node.style.fontSize=`${Math.max(8,preview.clientHeight*cs.size/108)}px`;
      node.style.webkitTextStroke=`${cs.borderWidth/40}px ${cs.borderColor}`;
      node.onpointerdown=event=>{
        if(event.button!==0)return;event.preventDefault();node.setPointerCapture(event.pointerId);
        selectedClip=clips.indexOf(clip);
        const before={x:cs.x,y:cs.y},originalStyle=clip.subtitleStyle;let pending={...before};
        const draw=position=>{node.style.left=(1+position.x)*50+'%';node.style.top=(1-position.y)*50+'%';};
        const finish=commit=>{
          node.onpointermove=node.onpointerup=node.onpointercancel=node.onlostpointercapture=null;
          if(!commit||!node.isConnected||!clips.includes(clip)||clip.subtitleStyle!==originalStyle){draw(before);return;}
          if(pending.x===before.x&&pending.y===before.y)return;
          // Clips without an explicit style get their own copy; moving this
          // caption must not change the default or another dialogue group.
          clip.subtitleStyle??=structuredClone(cs);Object.assign(clip.subtitleStyle,pending);
          changed();renderClips();renderClipEditor();
        };
        const move=ev=>{const rect=preview.getBoundingClientRect();if(!rect.width||!rect.height)return;pending={x:Math.max(-1,Math.min(1,(ev.clientX-rect.left)/rect.width*2-1)),y:Math.max(-1,Math.min(1,1-(ev.clientY-rect.top)/rect.height*2))};draw(pending);};
        node.onpointermove=move;
        node.onpointerup=()=>finish(true);
        node.onpointercancel=node.onlostpointercapture=()=>finish(false);
      };preview.append(node);
      });
    });
  }
  function stopPlayback(){playSerial++;gainNodes.forEach(n=>n.disconnect());gainNodes=[];players.forEach(a=>a.pause());players=[];playTimers.forEach(clearTimeout);playTimers=[];playing=false;}
  function contentEnd(){
    const fps=Number($('cut-fps').value)||30;
    const visualEnd=editor.scenes.reduce((sum,c)=>sum+(Number.isFinite(Number(c.duration))?Math.round(Number(c.duration)*fps)/fps:0),0);
    const ends=[visualEnd,...clips.map(c=>Number(c.start)+Number(c.duration)),...(window.cutText?.snapshot().textClips||[]).map(c=>Number(c.start)+Number(c.duration))];
    return Math.max(0,...ends.filter(Number.isFinite));
  }
  function clampPreviewTime(time){return Math.max(0,Math.min(contentEnd(),Number(time)||0));}
  function previewAt(time) {
    previewTime=clampPreviewTime(time);let cursor=0;const fps=Number($('cut-fps').value);
    let ix=editor.scenes.findIndex(s=>{const start=cursor;cursor+=Math.round(s.duration*fps)/fps;return previewTime>=start&&previewTime<cursor;});
    if(ix<0)ix=editor.scenes.length-1;editor.selectScene(ix);
  }
  $('dialogue-play').onclick=()=>work('dialogue-status',async()=>{
    stopPlayback();const origin=clampPreviewTime($('dialogue-preview-time').value),end=contentEnd();if(origin>=end){previewAt(end);return;}
    const serial=playSerial,Context=window.AudioContext||window.webkitAudioContext;if(Context){audioContext??=new Context();await audioContext.resume();}else if(clips.some(c=>c.volume>1))throw Error('当前浏览器不支持放大音量的预览，请使用 Chrome 或 Edge');if(serial!==playSerial)return;playing=true;
    clips.forEach(clip=>{if(clip.start+clip.duration<=origin)return;
      const player=new Audio(audioURL(clip.audio));if(audioContext){const source=audioContext.createMediaElementSource(player),gain=audioContext.createGain();gain.gain.value=Math.min(2,Math.max(0,clip.volume));source.connect(gain);gain.connect(audioContext.destination);gainNodes.push(source,gain);player.volume=1;}else player.volume=Math.min(1,Math.max(0,clip.volume));players.push(player);
      const offset=Math.max(origin,clip.start)-clip.start;
      playTimers.push(setTimeout(()=>{player.currentTime=clip.sourceStart+offset;player.play().catch(()=>{$('dialogue-status').textContent='部分音频无法播放，请在音频库检查';});},Math.max(0,clip.start-origin)*1000));
      playTimers.push(setTimeout(()=>player.pause(),(clip.start+clip.duration-origin)*1000));
    });
    const started=performance.now();
    const tick=()=>{if(!playing)return;const now=origin+(performance.now()-started)/1000;previewAt(Math.min(now,end));if(now<end)playTimers.push(setTimeout(tick,150));else stopPlayback();};tick();
  });
  $('dialogue-stop').onclick=stopPlayback;
  $('dialogue-preview-time').onchange=()=>{stopPlayback();previewAt(Math.max(0,Number($('dialogue-preview-time').value)||0));};
  $('dialogue-gap').onchange=()=>{gap=Number($('dialogue-gap').value);changed();};
  $('dialogue-role-order').onchange=()=>{roleOrder=$('dialogue-role-order').value==='01'?[0,1]:[1,0];changed();editor.render();};
  $('dialogue-library').onclick=()=>switchPage('audio');
  $('nav-audio').onclick=()=>switchPage('audio');
  $('dialogue-add').onclick=()=>{const item=items.find(i=>i.id===$('dialogue-audio').value);if(item)addClip(item);else $('dialogue-status').textContent='先选择一个音频';};
  $('dialogue-arrange').onclick=()=>{stopPlayback();let cursor=0;clips.filter(c=>c.kind==='dialogue').forEach(c=>{c.start=cursor;c.track=0;cursor+=c.duration+gap;});changed();renderClips();renderClipEditor();editor.render();};
  $('dialogue-scenes').onclick=()=>{
    const base=editor.scenes[editor.activeScene]||editor.scenes[0],dialogue=clips.filter(c=>c.kind==='dialogue');
    if(!base||!dialogue.length){$('dialogue-status').textContent='先选背景、设置人物，再加入对白';return;}
    if(!window.confirm('将替换当前镜头列表，按对白顺序生成镜头，并沿用所选镜头的背景和人物。'))return;
    stopPlayback();let cursor=0;const fps=Number($('cut-fps').value);
    const generated=dialogue.map((c,i)=>{c.start=cursor;c.track=0;const duration=Math.ceil((c.duration+(i<dialogue.length-1?gap:0))*fps)/fps;cursor+=duration;return {...structuredClone(base),duration,restart:false,videoStart:0};});
    changed();editor.setScenes(generated);renderClips();renderClipEditor();
  };
  $('dialogue-fit').onclick=()=>{const scenes=structuredClone(editor.scenes);if(!scenes.length){$('dialogue-status').textContent='先添加背景镜头';return;}const end=Math.max(0,...clips.map(c=>c.start+c.duration),...(window.cutText?.snapshot().textClips||[]).map(c=>c.start+c.duration)),total=scenes.reduce((s,c)=>s+c.duration,0);if(end>total){const fps=Number($('cut-fps').value);scenes.at(-1).duration+=Math.ceil((end-total)*fps)/fps;editor.setScenes(scenes);}else $('dialogue-status').textContent='现有镜头已经覆盖音频';};
  $('subtitle-save-preset').onclick=()=>work('dialogue-status',async()=>{preset=await api('/api/roughcut/subtitle-preset',style);$('dialogue-status').textContent='已保存默认预设，不联动修改已有对白组';});
  $('subtitle-load-preset').onclick=()=>work('dialogue-status',async()=>{preset=await api('/api/roughcut/subtitle-preset');style=structuredClone(preset);changed();renderDefaultStyle();});
  $('subtitle-apply-role').onclick=()=>{const clip=clips[selectedClip];if(!clip?.character){$('dialogue-status').textContent='先给当前对白填写角色名';return;}if(!window.confirm(`将当前样式应用到角色「${clip.character}」的所有对白组？其他角色保持独立。`))return;clips.filter(c=>c.character===clip.character).forEach(c=>c.subtitleStyle=structuredClone(clip.subtitleStyle));changed();renderClipEditor();editor.render();};
  $('audio-import').onclick=()=>work('audio-status',async()=>{const button=$('audio-import');button.disabled=true;try{const picked=await api('/api/audio/pick',{});if(!picked.paths.length)return;const result=await api('/api/audio/import',{paths:picked.paths});$('audio-status').textContent=result.results.map(r=>r.error?`${r.source}：${r.error}`:r.warning||`${r.source}：${r.duplicate?'已存在':'已导入'}`).join('；');await loadAudio();}finally{button.disabled=false;}});
  let audioSearchTimer;
  $('audio-search').oninput=()=>{clearTimeout(audioSearchTimer);audioSearchTimer=setTimeout(()=>work('audio-status',loadAudio),200);};
  for(const id of ['audio-search','audio-kind','audio-trash-view'])$(id).onchange=()=>{clearTimeout(audioSearchTimer);work('audio-status',loadAudio);};
  window.cutV2={snapshot:()=>({audioClips:clips.map(c=>{c.id??=crypto.randomUUID().replaceAll('-','');return c;}),subtitleStyle:style,roleOrder,gap}),
    audioItems:()=>items,loadAudio,addClip,previewAt,stopPlayback,contentEnd,
    isPlaying:()=>playing,
    locate(time){stopPlayback();previewAt(Math.max(0,time));},
    selectClip(index,{cueIndex=-1,seek=true}={}){const clip=clips[index];if(!clip)return;selectedClip=index;selectedCue=cueIndex;renderClips();renderClipEditor();window.dispatchEvent(new CustomEvent('cut-clip-selected',{detail:{index,cueIndex}}));if(seek&&!playing){const cue=clip.cues[cueIndex];previewAt(clip.start+(cue?Math.max(0,cue.start-clip.sourceStart):0));}else editor.render();if(cueIndex>=0)$('clip-cues').querySelector(`tbody tr:nth-child(${cueIndex+1})`)?.scrollIntoView({block:'nearest'});},
    updateClip(index,values){stopPlayback();Object.assign(clips[index],values);selectedClip=index;changed();renderClips();renderClipEditor();editor.render();},
    adopt(project){stopPlayback();clips=structuredClone(project.audioClips||[]);style={...preset,...project.subtitleStyle};roleOrder=project.roleOrder||[0,1];gap=project.gap??.3;selectedClip=clips.length?0:-1;selectedCue=-1;previewTime=0;$('dialogue-gap').value=gap;$('dialogue-role-order').value=roleOrder.join('');renderClips();renderClipEditor();renderDefaultStyle();},renderPreview};
  window.addEventListener('workshop-page',event=>{if(event.detail==='audio'||event.detail==='roughcut')work(event.detail==='audio'?'audio-status':'dialogue-status',loadAudio);if(event.detail!=='roughcut')stopPlayback();if(event.detail!=='audio')$('audio-detail').querySelectorAll('audio').forEach(a=>a.pause());});
  window.addEventListener('beforeunload',stopPlayback);
  // Empty projects skip the visual renderer, but their playhead and input
  // still need to reset after adoption, undo, deletion or a new project.
  window.addEventListener('cut-rendered',()=>{previewTime=clampPreviewTime(previewTime);$('dialogue-preview-time').value=previewTime.toFixed(3);$('dialogue-preview-time').max=String(contentEnd());});
  renderDefaultStyle();work('dialogue-status',async()=>{preset=await api('/api/roughcut/subtitle-preset');if(!clips.length){style=structuredClone(preset);renderDefaultStyle();}});
})();

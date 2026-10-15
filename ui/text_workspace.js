/*Independent text and bulk script entry, without requiring voice audio.*/
(() => {
  const $=id=>document.getElementById(id),editor=window.cutEditor,e=editor.escape;
  let clips=[],selected=-1,moreSettingsOpen=false;
  let importingSrt=false,projectEpoch=0;
  window.workshopActivity ||= {};
  window.workshopActivity.subtitleImport=()=>importingSrt;
  window.addEventListener('cut-project-loaded',event=>{if(!event.detail?.preserveHistory)projectEpoch++;});
  const style=()=>structuredClone(window.cutV2.snapshot().subtitleStyle);
  const commit=()=>{editor.markDirty();editor.render();};
  const panel=document.createElement('div');panel.id='text-properties';
  panel.innerHTML='<div class="production-actions"><button id="text-single">添加一条文字</button><button id="text-bulk">批量粘贴台词</button><button id="text-srt">导入独立 SRT</button></div><p>无配音的旁白、心理活动、台词独立排入文字轨。有配音的文字在「对白」中随音频编辑。</p><div id="text-edit"></div><p id="text-status" role="status"></p>';
  $('roughcut-page').append(panel);
  const dialog=document.createElement('dialog');dialog.className='text-bulk-dialog production-panel';
  dialog.innerHTML='<h3>批量添加文字</h3><p>每行一条；可写「角色名：台词」，未写角色时使用下面的默认角色。字数时长是阅读估算，可在时间轴继续调整。</p><textarea id="text-bulk-input" rows="10" placeholder="旁白：放学后的教室，只剩下我们两个人。\n主角：你还没有回家吗？\n少女：我在等你。"></textarea><div class="production-filters"><label>默认角色<input id="text-bulk-role" value="旁白"></label><label>开始时间<input id="text-bulk-start" type="number" min="0" step="0.1" value="0"></label><label>安排方式<select id="text-bulk-mode"><option value="reading">按字数估算</option><option value="fixed">统一时长</option></select></label><label>每条秒数<input id="text-bulk-duration" type="number" min="0.1" max="3600" step="0.1" value="3"></label><label>间隔秒数<input id="text-bulk-gap" type="number" min="0" max="10" step="0.1" value="0.3"></label><label>文字轨道<input id="text-bulk-track" type="number" min="1" max="16" value="1"></label></div><p id="text-bulk-error" role="status"></p><div class="production-actions"><button id="text-bulk-confirm">添加并延长末镜头</button><button id="text-bulk-cancel">取消</button></div>';
  document.body.append(dialog);
  function extend(){editor.ensureCoverage(Math.max(0,...clips.map(c=>c.start+c.duration)));}
  function select(index,{seek=true}={}){const clip=clips[index];if(!clip)return;selected=index;renderEditor();window.dispatchEvent(new CustomEvent('cut-text-selected',{detail:{index}}));if(seek&&!window.cutV2.isPlaying())window.cutV2.locate(clip.start);else if(seek)editor.render();}
  function renderEditor(){const clip=clips[selected],target=$('text-edit');if(!clip){target.innerHTML='<p>点击时间轴的文字片段进行修改。</p>';return;}
    if(clip.layout){renderStoryEditor(clip,target);return;}
    const limits={start:[0,10800],duration:[.001,3600],track:[1,16],x:[-100,100],y:[-100,100],size:[2,50]};
    const fields=entries=>entries.map(([name,key,type])=>{const value=['x','y'].includes(key)?Math.round(clip.subtitleStyle[key]*100):key==='size'?Math.round(clip.subtitleStyle.size):key==='track'?clip.track+1:clip[key];return `<label>${name}<input id="text-edit-${key}" type="${type}"${type==='number'?` step="1" min="${limits[key][0]}" max="${limits[key][1]}"`:''} data-rendered-value="${e(value)}" value="${e(value)}"></label>`;}).join('');
    target.innerHTML=`<label>文字内容<textarea id="text-content" rows="4">${e(clip.text)}</textarea></label><div class="production-filters">${fields([['开始秒数','start','number'],['持续秒数','duration','number']])}</div><details id="text-more-settings"${moreSettingsOpen?' open':''}><summary>更多设置</summary><p>角色、轨道和基本位置按需调整；字体与精细样式可在剪映中继续编辑。</p><div class="production-filters">${fields([['人物名（可选）','character','text'],['轨道编号','track','number'],['水平位置（%）','x','number'],['垂直位置（%，向上为正）','y','number'],['字号','size','number']])}<label>文字颜色<input id="text-color" type="color" value="${clip.subtitleStyle.color}"></label></div></details><div class="production-actions"><button id="text-copy">复制到下一条</button><button id="text-delete">删除文字</button></div>`;
    $('text-more-settings').ontoggle=event=>{moreSettingsOpen=event.currentTarget.open;};
    $('text-content').onchange=()=>{if(!$('text-content').value.trim()){$('text-content').value=clip.text;$('text-status').textContent='文字不能为空；删除这条文字请使用「删除文字」。';return;}$('text-status').textContent='';if(clip.text===$('text-content').value)return;clip.text=$('text-content').value;commit();};
    for(const key of ['character','start','duration','track','x','y','size'])$('text-edit-'+key).onchange=event=>{const input=event.target;let value=key==='character'?input.value:Number(input.value);if(limits[key]&&(!input.value.trim()||!Number.isFinite(value)||value<limits[key][0]||value>limits[key][1]||(['track','x','y','size'].includes(key)&&!Number.isInteger(value)))){renderEditor();return;}const initial=key==='character'?input.dataset.renderedValue:Number(input.dataset.renderedValue);if(value===initial)return;input.dataset.renderedValue=String(value);if(['x','y'].includes(key))clip.subtitleStyle[key]=value/100;else if(key==='size')clip.subtitleStyle.size=value;else clip[key]=key==='track'?value-1:value;commit();};
    $('text-color').onchange=event=>{clip.subtitleStyle.color=event.target.value;commit();};
    $('text-copy').onclick=()=>{const copy={...structuredClone(clip),id:crypto.randomUUID().replaceAll('-',''),start:clip.start+clip.duration};delete copy.sourceRow;delete copy.voice;clips.push(copy);selected=clips.length-1;extend();commit();select(selected);$('text-content')?.focus();};
    $('text-delete').onclick=()=>{clips.splice(selected,1);selected=Math.min(selected,clips.length-1);commit();renderEditor();};
  }
  $('text-single').onclick=()=>{clips.push({text:'请输入文字',character:'',start:Number($('dialogue-preview-time').value)||0,duration:3,track:0,subtitleStyle:style()});selected=clips.length-1;extend();commit();select(selected);};
  $('text-bulk').onclick=()=>{$('text-bulk-start').value=Math.max(Number($('dialogue-preview-time').value)||0,...clips.map(c=>c.start+c.duration));$('text-bulk-error').textContent='';dialog.showModal();};
  $('text-bulk-cancel').onclick=()=>dialog.close();
  $('text-bulk-confirm').onclick=()=>{const lines=$('text-bulk-input').value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);let cursor=Number($('text-bulk-start').value);const fixed=Number($('text-bulk-duration').value),gap=Number($('text-bulk-gap').value),track=Number($('text-bulk-track').value)-1;
    if(!lines.length||lines.length+clips.length>2000||!Number.isFinite(cursor)||cursor<0||!Number.isFinite(fixed)||fixed<=0||fixed>3600||!Number.isFinite(gap)||gap<0||gap>10||!Number.isInteger(track)||track<0||track>15){$('text-bulk-error').textContent='请检查文字数量、时间与轨道编号。';return;}
    const added=lines.map(line=>{const match=line.match(/^([^：:]{1,30})[：:]\s*(.+)$/);const text=match?match[2]:line;const duration=$('text-bulk-mode').value==='fixed'?fixed:Math.max(1.5,Math.ceil((text.replace(/\s/g,'').length/5+.5)*10)/10);const clip={text,character:match?match[1]:$('text-bulk-role').value,start:cursor,duration,track,subtitleStyle:style()};cursor+=duration+gap;return clip;});
    if(cursor-gap>10800||added.some(c=>c.text.length>2000)){$('text-bulk-error').textContent='每条文字最多两千字，整个时间轴最多三小时。';return;}
    clips.push(...added);selected=clips.length-added.length;extend();commit();select(selected);dialog.close();$('text-bulk-input').value='';};
  $('text-srt').onclick=async()=>{
    if(importingSrt)return;
    importingSrt=true;$('text-srt').disabled=true;
    const epoch=projectEpoch,offset=Number($('dialogue-preview-time').value)||0,subtitleStyle=style();
    try{
      const result=await editor.api('/api/audio/srt',{});
      if(!result.cues)return;
      if(epoch!==projectEpoch)throw Error('项目已切换，字幕未添加。请在目标项目重新导入。');
      if(!result.cues.length){$('text-status').textContent='字幕文件中没有可导入的内容。';return;}
      if(clips.length+result.cues.length>2000)throw Error('独立文字最多两千条');
      if(result.cues.some(c=>!Number.isFinite(c.start)||!Number.isFinite(c.end)||c.start<0||c.end<=c.start||c.end-c.start>3600||offset+c.end>10800))throw Error('字幕超出时间范围：单条最多一小时，时间轴最多三小时。');
      clips.push(...result.cues.map(c=>({text:c.text,character:'旁白',start:offset+c.start,duration:c.end-c.start,track:0,subtitleStyle:structuredClone(subtitleStyle)})));
      selected=clips.length-result.cues.length;extend();commit();select(selected);
      $('text-status').textContent=`已导入 ${result.cues.length} 条字幕。`;
    }catch(error){$('text-status').textContent=error.message;}
    finally{importingSrt=false;$('text-srt').disabled=false;}
  };
  function renderPreview(){const preview=$('cut-preview');preview.querySelectorAll('.standalone-text').forEach(n=>n.remove());const time=Number($('dialogue-preview-time').value)||0;
    clips.forEach((clip,index)=>{if(time<clip.start||time>=clip.start+clip.duration)return;if(clip.layout){renderStory(clip,index,preview);return;}const cs=clip.subtitleStyle,node=document.createElement('div');node.className='preview-subtitle standalone-text';node.textContent=window.cutWrapLegacy((cs.showCharacter&&clip.character?clip.character+'：':'')+clip.text);node.style.maxWidth='none';node.style.whiteSpace='pre';node.style.left=(1+cs.x)*50+'%';node.style.top=(1-cs.y)*50+'%';node.style.color=cs.color;node.style.fontSize=Math.max(8,preview.clientHeight*cs.size/108)+'px';node.style.webkitTextStroke=cs.borderWidth/40+'px '+cs.borderColor;
      let dragging=false;
      node.onpointerdown=event=>{if(event.button!==0||dragging)return;event.preventDefault();dragging=true;const before={x:cs.x,y:cs.y};let pending={...before};node.setPointerCapture(event.pointerId);select(index,{seek:false});
        const place=value=>{node.style.left=(1+value.x)*50+'%';node.style.top=(1-value.y)*50+'%';};
        const finish=apply=>{if(!dragging)return;dragging=false;node.onpointermove=node.onpointerup=node.onpointercancel=node.onlostpointercapture=null;const changed=Math.abs(pending.x-before.x)>1e-9||Math.abs(pending.y-before.y)>1e-9;
          if(apply&&changed&&node.isConnected&&clips.includes(clip)&&clip.subtitleStyle===cs){Object.assign(cs,pending);commit();renderEditor();}else place(before);
        };
        node.onpointermove=ev=>{const rect=preview.getBoundingClientRect();if(!rect.width||!rect.height)return;pending={x:Math.max(-1,Math.min(1,(ev.clientX-rect.left)/rect.width*2-1)),y:Math.max(-1,Math.min(1,1-(ev.clientY-rect.top)/rect.height*2))};place(pending);};
        node.onpointerup=()=>finish(true);node.onpointercancel=node.onlostpointercapture=()=>finish(false);
      };preview.append(node);});
  }

  const storyBox=clip=>clip.layout[['narrator','inner'].includes(clip.layout.kind)?'narrator':'dialogue'];
  function renderStoryEditor(clip,target){const b=storyBox(clip),l=clip.layout;
    target.innerHTML=`<label>正文<textarea id="text-content" rows="4">${e(clip.text)}</textarea></label><div class="production-filters"><label>角色名<input id="story-character" value="${e(clip.character)}"></label>${Object.entries({x:'起点 X',y:'起点 Y',width:'文字区域宽',height:'文字区域高',size:'字号',lineHeight:'行高'}).map(([k,label])=>`<label>${label}（像素）<input data-story="${k}" type="number" step="1" value="${b[k]}"></label>`).join('')}<label>角色名 X<input id="story-name-x" type="number" step="1" value="${l.name.x}"></label><label>角色名 Y<input id="story-name-y" type="number" step="1" value="${l.name.y}"></label>${[["start","开始秒数"],["duration","持续秒数"],["track","文字轨道"]].map(([k,label])=>`<label>${label}<input data-story-time="${k}" type="number" step="${k==='track'?1:.1}" value="${k==='track'?clip.track+1:clip[k]}"></label>`).join('')}<label>文字颜色<input id="text-color" type="color" value="${clip.subtitleStyle.color}"></label></div><p>坐标从参考画布左上角起算，整数像素；输入时同步预览。正文与角色名分别定位。</p><label><input id="text-paginate" type="checkbox" ${l.paginate?'checked':''}>长文字自动分页</label><p id="story-overflow" role="status"></p><div class="production-actions"><button id="text-delete">删除文字</button></div>`;
    const refresh=()=>{commit();$('story-overflow').textContent=l.overflow?'文字超出区域，请扩大区域或拆分台词；当前修改可保存，生成前需解决。':'';};
    $('text-paginate').onchange=event=>{l.paginate=event.target.checked;refresh();};
    $('text-content').oninput=()=>{if(!$('text-content').value.trim())return;clip.text=$('text-content').value;refresh();};
    target.querySelectorAll('[data-story-time]').forEach(n=>n.oninput=()=>{const v=Number(n.value),k=n.dataset.storyTime;if(!n.value||!Number.isFinite(v)||v<(k==='duration'?.001:k==='track'?1:0)||v>(k==='duration'?3600:k==='track'?16:10800)||(k==='track'&&!Number.isInteger(v)))return;clip[k]=k==='track'?v-1:v;refresh();});
    $('story-character').oninput=()=>{clip.character=$('story-character').value;refresh();};
    target.querySelectorAll('[data-story]').forEach(n=>n.oninput=()=>{const v=Number(n.value),k=n.dataset.story;if(!n.value||!Number.isInteger(v))return;const candidate={...b,[k]:v};if(candidate.x<0||candidate.y<0||candidate.width<1||candidate.height<1||candidate.x+candidate.width>l.width||candidate.y+candidate.height>l.height||candidate.size<12||candidate.size>240||candidate.lineHeight<candidate.size||candidate.lineHeight>480)return;Object.assign(b,candidate);refresh();});
    for(const axis of ['x','y'])$('story-name-'+axis).oninput=event=>{const v=Number(event.target.value);if(event.target.value&&Number.isInteger(v)&&v>=0&&v+l.name[axis==='x'?'width':'height']<=l[axis==='x'?'width':'height']){l.name[axis]=v;refresh();}};
    $('text-color').oninput=event=>{clip.subtitleStyle.color=event.target.value;refresh();};
    $('text-delete').onclick=()=>{clips.splice(selected,1);selected=Math.min(selected,clips.length-1);commit();renderEditor();};
  }
  function renderStory(clip,index,preview){const l=clip.layout,b=storyBox(clip),context=document.createElement('canvas').getContext('2d');context.font=`${b.size}px "Microsoft YaHei"`;const lines=[];
    for(const paragraph of clip.text.split('\n')){let line='';for(const char of paragraph){if(line&&context.measureText(line+char).width>b.width){lines.push(line);line='';}line+=char;}lines.push(line);}
    l.lines=lines;l.nameText=l.name.enabled&&!['narrator','inner'].includes(l.kind)&&clip.character?'【'+clip.character+'】':'';
    context.font=`${l.name.size}px "Microsoft YaHei"`;const capacity=Math.max(1,Math.floor(b.height/b.lineHeight));l.pages=l.paginate?Array.from({length:Math.ceil(lines.length/capacity)},(_,i)=>lines.slice(i*capacity,(i+1)*capacity)):[lines];l.overflow=(!l.paginate&&lines.length*b.lineHeight>b.height)||b.lineHeight>b.height||(l.nameText&&context.measureText(l.nameText).width>l.name.width);
    const fps=Number($('cut-fps').value)||30,frames=Math.floor(clip.duration*fps+1e-7),frame=Math.floor(Math.max(0,(Number($('dialogue-preview-time').value)-clip.start)*fps+1e-7));let page=0;for(let i=1;i<l.pages.length;i++)if(frame>=Math.floor(i*frames/l.pages.length))page=i;l.overflow ||= frames<l.pages.length;
    const sx=preview.clientWidth/l.width,sy=preview.clientHeight/l.height;
    function node(text,box,name=false){const n=document.createElement('div');n.className='preview-subtitle standalone-text'+(name?' story-name':'')+(selected===index?' story-region':'');n.textContent=text;Object.assign(n.style,{left:box.x*sx+'px',top:box.y*sy+'px',width:box.width*sx+'px',height:box.height*sy+'px',maxWidth:'none',transform:'none',textAlign:'left',fontFamily:'"Microsoft YaHei",sans-serif',fontSize:box.size*sy+'px',lineHeight:box.lineHeight*sy+'px',color:clip.subtitleStyle.color,webkitTextStroke:clip.subtitleStyle.borderWidth/40+'px '+clip.subtitleStyle.borderColor});n.onclick=()=>select(index,{seek:false});preview.append(n);}
    node(l.pages[page].join('\n'),b);if(l.nameText)node(l.nameText,l.name,true);
  }
  window.addEventListener('cut-rendered',renderPreview);
  window.cutText={snapshot:()=>({textClips:clips.map(c=>{c.id??=crypto.randomUUID().replaceAll('-','');return c;})}),adopt(project){clips=structuredClone(project.textClips||[]);clips.forEach(c=>c.id??=crypto.randomUUID().replaceAll('-',''));selected=clips.length?0:-1;renderEditor();},select,update(index,values){Object.assign(clips[index],values);selected=index;commit();renderEditor();},extend,renderPreview};
  renderEditor();
})();

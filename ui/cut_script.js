/*Sentence review workflow: explicit voice and expression choices, then editable tracks.*/
(()=>{
 const $=id=>document.getElementById(id),editor=window.cutEditor,e=editor.escape;
 const kinds={narrator:'旁白',inner:'心理描写',dialogue:'对话'};
 let rows=[],gap=.3,groups=[],audio=[],schedule=[],directives=[],layout=null,timing=null,scriptTiming=null,scriptBase=null,scriptBaseline=null,sceneBindings={};
 const dialog=document.createElement('dialog');dialog.id='script-dialog';dialog.className='studio-dialog script-dialog';
 dialog.innerHTML=`<div class="script-heading"><h3>台词分类与播放节奏</h3><button id="script-close">关闭</button></div><p>确认每句类型、配音和表情。有声句完整播放；无声句按停留时长显示。文字保留至下一句，末句不额外加停顿。</p><details id="script-paste-box"><summary>批量粘贴台词</summary><textarea id="script-paste" rows="4" placeholder="旁白：放学后，教室里只剩我们。\n女主：我在等你。\n女主内心：希望他没有发现。\n男主：那一起走吧。"></textarea><button id="script-add-lines">加入校对表</button></details><div class="script-actions"><button id="script-add">添加一句</button><label>默认句间停顿（秒）<input id="script-gap" type="number" min="0" max="10" step="0.1" value="0.3"></label><button id="script-refresh">刷新音频与表情</button><span id="script-count"></span></div><div class="script-table-scroll"><table class="script-table"><thead><tr><th>顺序</th><th>分类 / 角色</th><th>文字</th><th>配音 / 音频</th><th>表情</th><th>无声停留 / 句间停顿</th><th>操作</th></tr></thead><tbody id="script-rows"></tbody></table></div><audio id="script-audition" controls hidden></audio><p id="script-status" role="status"></p><div id="script-schedule"></div><label class="script-review"><input id="script-reviewed" type="checkbox">已确认每句分类、配音和表情；铺轨将替换镜头、对白与文字，保留 BGM 和音效，可撤销。</label><div class="script-actions"><button id="script-save">保存校对表</button><button id="script-build">按句铺入时间轴</button></div>`;
 document.body.append(dialog);
 const button=document.createElement('button');button.id='studio-script';button.textContent='台词校对';button.onclick=()=>open();$('studio-project-settings').before(button);
 const changed=()=>{$('script-reviewed').checked=false;schedule=[];$('script-schedule').replaceChildren();$('script-status').textContent='校对表已修改，重新铺轨后时间轴才会更新。';editor.markDirty();};
 const key=()=>crypto.randomUUID();
 const blank=(text='请输入台词',kind='narrator',character='')=>({id:key(),text,kind,character,voice:['heroine','inner'].includes(kind),voiceExplicit:false,audio:'',hold:3,holdExplicit:false,pause:null});
 const binding=r=>({id:r.audio,text:String(r.text??'').trim(),character:String(r.character??'').trim()});
 const needsAudioReview=r=>{const expected=binding(r);return Boolean(r.audio&&['id','text','character'].some(k=>r.audioBinding?.[k]!==expected[k]));};
 function expressions(){const base=scriptBase||editor.scenes[editor.activeScene];const options=[];
  for(const actor of base?.actors||[]){options.push({key:`${actor.slot}:${actor.id}`,label:`角色 ${actor.slot+1} · 当前表情`,value:{id:actor.id,slot:actor.slot,...(actor.alignment?{alignment:structuredClone(actor.alignment)}:{})}});
   const g=groups.find(g=>g.id===actor.alignment?.groupId&&g.version===actor.alignment?.version);
   for(const m of g?.members||[])if(m.id!==actor.id){const {id,name,mode,...alignment}=m;options.push({key:`${actor.slot}:${id}`,label:`角色 ${actor.slot+1} · ${name}`,value:{id,slot:actor.slot,alignment}});}
  }return options;
 }
 function render(){const choices=expressions();$('script-gap').value=gap;$('script-count').textContent=rows.length+' 句';
  $('script-rows').innerHTML=rows.map((r,i)=>{
   let expressionKey=r.expression?`${r.expression.slot}:${r.expression.id}`:'';
   const match=choices.find(o=>o.key===expressionKey);
   const stale=r.expression&&(!match||JSON.stringify(match.value.alignment||null)!==JSON.stringify(r.expression.alignment||null));
   if(stale)expressionKey='saved:'+expressionKey;
   return `<tr data-row="${i}"><td>${i+1}</td><td><select data-field="kind" aria-label="第 ${i+1} 句分类">${Object.entries({...kinds,...(['hero','heroine'].includes(r.kind)?{dialogue:undefined,[r.kind]:'对话'}:{})}).filter(([,label])=>label).map(([key,label])=>`<option value="${key}" ${r.kind===key?'selected':''}>${label}</option>`).join('')}</select><input data-field="character" aria-label="第 ${i+1} 句角色" placeholder="角色名（可选）" value="${e(r.character)}"></td><td><textarea data-field="text" rows="3" aria-label="第 ${i+1} 句文字">${e(r.text)}</textarea></td><td><label><input data-field="voice" type="checkbox" ${r.voice?'checked':''}>配音${r.voiceExplicit?'（手动选择）':''}</label><select data-field="audio" aria-label="第 ${i+1} 句音频" ${r.voice?'':'disabled'}><option value="">请选择音频</option>${audio.filter(a=>!a.missing).map(a=>`<option value="${a.id}" ${r.audio===a.id?'selected':''}>${e(a.name)} · ${a.duration.toFixed(2)} 秒</option>`).join('')}${r.audio&&!audio.some(a=>a.id===r.audio&&!a.missing)?`<option value="${e(r.audio)}" selected>音频丢失，请重新选择</option>`:''}</select><button data-action="listen" ${r.voice&&r.audio?'':'disabled'}>试听</button>${needsAudioReview(r)?`<p class="script-audio-warning" role="status">文字或角色已变更，请核对旧音频。</p><button data-action="review-audio" ${r.voice&&audio.some(a=>a.id===r.audio&&!a.missing)?'':'disabled'}>已核对音频</button>`:''}</td><td><select data-field="expression" aria-label="第 ${i+1} 句表情"><option value="">沿用上一句</option>${choices.map(o=>`<option value="${e(o.key)}" ${o.key===expressionKey?'selected':''}>${e(o.label)}</option>`).join('')}${stale?`<option value="${e(expressionKey)}" selected>已保存表情（请核对基础人物）</option>`:''}</select></td><td><label>停留（秒）<input data-field="hold" type="number" min="0.1" max="3590" step="0.1" value="${r.hold}" ${r.voice?'disabled':''}></label><label>停顿（秒）<input data-field="pause" type="number" min="0" max="10" step="0.1" placeholder="默认 ${gap}" value="${r.pause??''}"></label></td><td><button data-action="up" ${i===0?'disabled':''}>上移</button><button data-action="down" ${i===rows.length-1?'disabled':''}>下移</button><button data-action="delete">删除</button></td></tr>`;
  }).join('');
  $('script-rows').querySelectorAll('tr').forEach(tr=>{const index=Number(tr.dataset.row),r=rows[index];
   tr.querySelectorAll('[data-field]').forEach(node=>node.onchange=()=>{const field=node.dataset.field;
    if(field==='expression'){const found=choices.find(o=>o.key===node.value);if(found)r.expression=structuredClone(found.value);else if(!node.value)delete r.expression;}
    else if(field==='voice'){r.voice=node.checked;r.voiceExplicit=true;}
    else if(field==='audio'){r.audio=node.value;delete r.take;if(r.audio)r.audioBinding=binding(r);else delete r.audioBinding;$('script-audition').pause();}
    else if(field==='hold'||field==='pause'){if(field==='hold')r.holdExplicit=true;const n=node.value===''&&field==='pause'?null:Number(node.value);if(n!==null&&(!Number.isFinite(n)||n<(field==='hold'?.1:0)||n>(field==='hold'?3590:10))){$('script-status').textContent='请检查停留与停顿秒数';render();return;}r[field]=n;}
    else {r[field]=node.value;if(field==='kind'&&!r.voiceExplicit)r.voice=['heroine','inner'].includes(r.kind);}
    changed();render();
   });
   tr.querySelectorAll('[data-action]').forEach(node=>node.onclick=()=>{const action=node.dataset.action;
    if(action==='listen'){const player=$('script-audition');player.hidden=false;player.src='/api/audio/media?id='+encodeURIComponent(r.audio);player.play().catch(error=>$('script-status').textContent=error.message);return;}
    if(action==='review-audio'){r.audioBinding=binding(r);changed();render();return;}
    if(action==='delete')rows.splice(index,1);else{const next=index+(action==='up'?-1:1);[rows[index],rows[next]]=[rows[next],rows[index]];}
    changed();render();
   });
  });
 }
 async function refresh(){await window.cutV2.loadAudio();audio=window.cutV2.audioItems();groups=(await editor.api('/api/composition')).groups;render();window.dispatchEvent(new Event('script-plan-rendered'));}
 async function open(){render();dialog.showModal();dialog.inert=true;dialog.dataset.loading='true';$('script-status').textContent='正在读取音频与表情…';try{await refresh();$('script-status').textContent='';}catch(error){$('script-status').textContent=error.message;}finally{dialog.inert=false;dialog.dataset.loading='false';}}
 $('script-close').onclick=()=>dialog.close();dialog.addEventListener('close',()=>{$('script-audition').pause();});
 $('script-add').onclick=()=>{if(rows.length>=500){$('script-status').textContent='最多五百句';return;}rows.push(blank());changed();render();};
 $('script-add-lines').onclick=()=>{const lines=$('script-paste').value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);if(!lines.length||lines.length+rows.length>500){$('script-status').textContent='请输入台词，总数最多五百句';return;}
  const types={'旁白':'narrator','女主':'heroine','女主对白':'heroine','女主内心':'inner','女主内心独白':'inner','男主':'hero','男主对白':'hero'};
  const parsed=lines.map(line=>{const match=line.match(/^([^：:]{1,30})[：:]\s*(.+)$/);return blank(match?match[2]:line,types[match?.[1]]||'narrator',match&&!types[match[1]]?match[1]:'');});
  if(parsed.some(r=>r.text.length>2000)){$('script-status').textContent='每句最多两千字';return;}rows.push(...parsed);$('script-paste').value='';$('script-paste-box').open=false;changed();render();
 };
 $('script-gap').onchange=()=>{const value=Number($('script-gap').value);if(!Number.isFinite(value)||value<0||value>10){render();return;}gap=value;changed();render();};
 $('script-refresh').onclick=()=>refresh().catch(error=>$('script-status').textContent=error.message);
 $('script-save').onclick=async()=>{dialog.inert=true;try{await editor.save();$('script-status').textContent=$('cut-status').textContent;}finally{dialog.inert=false;}};
 const rebuildDialog=document.createElement('dialog');rebuildDialog.id='script-rebuild-dialog';rebuildDialog.className='studio-dialog';rebuildDialog.innerHTML='<h3>重新铺轨影响</h3><p id="rebuild-summary"></p><p id="rebuild-warnings"></p><p>保留可合并的修改包括构图、已用图片、文字区域、正文与音量。人工时间、裁切、新增/删除片段需要在旧项目核对。</p><div class="production-actions"><button id="rebuild-backup">先另存当前精修项目</button><button id="rebuild-preserve">保留可合并的精修并应用</button><button id="rebuild-replace">使用校对表重新铺轨</button><button id="rebuild-cancel">取消</button></div><p id="rebuild-status" role="status"></p>';document.body.append(rebuildDialog);
 let rebuildData=null;
 const rebuild={show(result,snapshot){rebuildData={result,snapshot};const summary=result.summary;$('rebuild-summary').textContent=`画面 ${summary.oldScenes} → ${summary.scenes} 镜；时长 ${summary.oldDuration.toFixed(2)} → ${summary.duration.toFixed(2)} 秒。可保留 ${summary.manualFields} 项人工修改。`;$('rebuild-warnings').textContent=summary.conflicts.join('；')||summary.note;$('rebuild-preserve').disabled=!result.preservedProject;$('rebuild-status').textContent='时间轴尚未修改。';rebuildDialog.showModal();}};
 $('rebuild-cancel').onclick=()=>rebuildDialog.close();
 $('rebuild-backup').onclick=async()=>{try{const backup=structuredClone(rebuildData.snapshot);delete backup.id;backup.name=(backup.name||'项目')+' · 精修备份';const saved=await editor.api('/api/roughcut/save',backup);$('rebuild-status').textContent='已另存：'+saved.name;}catch(error){$('rebuild-status').textContent=error.message;}};
 for(const [id,preserve] of [['rebuild-preserve',true],['rebuild-replace',false]])$(id).onclick=()=>{if(JSON.stringify(rebuildData.snapshot)!==JSON.stringify(editor.snapshot())){$('rebuild-status').textContent='当前项目已变化，请取消并重新计算。';return;}const value=preserve?rebuildData.result.preservedProject:rebuildData.result.project;if(!value)return;editor.applyTimeline(value);rebuildDialog.close();$('script-status').textContent='已应用新时间轴，可撤销。旧剪映草稿不会覆盖。';};
 $('script-build').onclick=async()=>{
  if(!$('script-reviewed').checked){$('script-status').textContent='请先确认分类、配音和表情';return;}
  const build=$('script-build');build.disabled=true;dialog.inert=true;$('script-audition').pause();
  try{const snapshot=structuredClone(editor.snapshot()),result=await editor.api('/api/roughcut/rebuild-preview',{...snapshot,baseScene:Math.max(0,editor.activeScene),reviewed:true});if(snapshot.scriptBaseline){rebuild.show(result,snapshot);$('script-status').textContent='已计算，尚未替换；请查看修改影响。';return;}editor.applyTimeline(result.project);schedule=result.schedule;
   $('script-schedule').textContent=schedule.map((r,i)=>`${i+1}. ${r.start.toFixed(2)}–${r.end.toFixed(2)} 秒（${r.duration.toFixed(2)} 秒${rows[i].voice?'完整配音':'文字'}，停顿 ${r.pause.toFixed(2)} 秒）`).join('　');$('script-status').textContent=`已铺入 ${rows.length} 句；可关闭窗口预览，或撤销。修改校对表后需重新铺轨。`;
  }catch(error){$('script-status').textContent=error.message;}finally{build.disabled=false;dialog.inert=false;}
 };
 window.addEventListener('cut-project-loaded',event=>{if(dialog.open&&event.detail?.preserveHistory)$('script-status').textContent='校对表已随项目保存。';});
 window.cutScript={snapshot:()=>({scriptPlan:{rows,gap,...(Object.keys(sceneBindings).length?{sceneBindings}:{}),...(directives.length?{directives}:{}),...(layout?{layout}:{}),...(timing?{timing}:{})},...(scriptTiming?{scriptTiming}:{}),...(scriptBase?{scriptBase}:{}),...(scriptBaseline?{scriptBaseline}:{})}),
  refresh,render,changed,open,
  actorChoices:expressions,
  bindScene(key,background){if(background)sceneBindings[key]=background;else delete sceneBindings[key];changed();render();window.dispatchEvent(new Event('script-plan-rendered'));},
  captureBase(){const base=editor.scenes[editor.activeScene];if(!base)throw Error('请先选择基础镜头');scriptBase=structuredClone(base);changed();render();},
  configure(values){layout=structuredClone(values.layout);timing=structuredClone(values.timing);changed();render();},
  useDefault(index){rows[index].holdExplicit=false;changed();render();},
  append(plan){if(rows.length+plan.rows.length>500)throw new Error('台词总数最多五百句');rows.push(...structuredClone(plan.rows));directives.push(...structuredClone(plan.directives||[]));changed();render();},
  merge(plan){const current=new Map(rows.map(r=>[r.id,r]));for(const r of plan.rows){const c=current.get(r.id);if(!c||c.text!==r.text||c.character!==r.character)throw new Error('当前剧本已变更，请从任务记录中恢复或手动核对音频');}for(const r of plan.rows){const c=current.get(r.id);for(const k of ['audio','audioBinding','take','versions'])if(k in r)c[k]=structuredClone(r[k]);}changed();render();},
  adopt(project){const plan=project.scriptPlan||{rows:[],gap:project.gap??.3};scriptBase=structuredClone(project.scriptBase||null);scriptBaseline=structuredClone(project.scriptBaseline||null);layout=structuredClone(plan.layout||null);timing=structuredClone(plan.timing||null);scriptTiming=structuredClone(project.scriptTiming||null);rows=structuredClone(plan.rows);directives=structuredClone(plan.directives||[]);sceneBindings=structuredClone(plan.sceneBindings||{});for(const r of rows){r.voiceExplicit??=true;if(r.audio&&!r.audioBinding)r.audioBinding=binding(r);}gap=plan.gap;schedule=[];$('script-audition').pause();$('script-audition').removeAttribute('src');$('script-audition').hidden=true;$('script-paste').value='';$('script-reviewed').checked=false;$('script-schedule').replaceChildren();render();window.dispatchEvent(new Event('script-plan-rendered'));}};
})();

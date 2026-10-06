/*Script import and durable batch voice workflow, layered on the existing review table.*/
(()=>{
 const $=id=>document.getElementById(id),s=window.cutScript,api=window.cutEditor.api,e=window.cutEditor.escape;
 let profiles=[],active=null,timer=null,applied=new Set(),draftId=null;
 const container=document.createElement('section');container.id='script-voice-tools';
 container.innerHTML=`<div class="script-actions"><button id="script-import-file">导入 TXT / DOCX</button><button id="script-import-paste">解析粘贴的剧本</button><button id="script-voice-config">配置角色声音</button><button id="script-capture-voice">保存当前声音为批量预设</button></div>
 <div class="script-actions"><button id="script-save-standalone">保存为独立剧本</button><select id="script-drafts" aria-label="打开独立剧本"><option value="">打开已保存剧本…</option></select></div><details><summary>剧本格式示例与解析规则</summary><pre>【场景】教室
【背景】学院_教室a
【旁白】放学后，教室里只剩我们。
【心理描写】【男主】【无配音】她好像有话想说。
【对话】【莉莉子】【有配音】那个，你今天有空吗？
【对话】【男主】【无配音】当然，有什么事吗？</pre><p>也支持「旁白：…」「莉莉子：…」。未标明类别、角色或配音安排的内容会提示确认。场景和素材名称只保存为说明，不自动匹配同名素材。</p></details>
 <details id="script-voice-rules"><summary>角色默认配音与声音绑定</summary><div class="script-actions"><label>角色<select id="script-rule-character"></select></label><label><input id="script-rule-voice" type="checkbox">默认配音</label><label>声音<select id="script-rule-preset"></select></label><label>语言<select id="script-rule-language"><option value="">随预设</option><option value="zh">中文</option><option value="ja">日语</option><option value="en">英语</option><option value="yue">粤语</option><option value="ko">韩语</option></select></label><button id="script-rule-apply">应用到该角色</button></div><p>手动修改过的配音开关会保留；男主默认无配音，每句都可以单独调整。</p></details>
 <details><summary>场景与素材说明（不自动匹配素材）</summary><div id="script-source-notes"></div></details><div class="script-actions"><button id="script-start-service">启动本机推理</button><button id="script-batch-generate" class="primary-button">生成所有缺少音频的配音句</button><button id="script-batch-stop" hidden>当前句完成后停止</button><button id="script-jobs-refresh">任务记录</button><span id="script-batch-status" role="status" aria-live="polite"></span></div><details id="script-job-errors" hidden><summary>未完成的台词与原因</summary><div id="script-job-error-list"></div></details><details id="script-task-history"><summary>历史配音任务与恢复</summary><div id="script-jobs"></div></details>`;
 $('script-paste-box').after(container);
 const style=document.createElement('style');style.textContent=`#script-voice-tools{border:1px solid #315b73;background:#092138;border-radius:12px;padding:14px;margin:12px 0}#script-voice-tools pre{white-space:pre-wrap;font:inherit;color:#bde7ff}#script-voice-tools details{margin:12px 0}#script-source-notes{color:#9dbcd1;white-space:pre-wrap}.script-voice-extra{border-top:1px solid #315b73;margin-top:10px;padding-top:8px}.script-voice-extra select{max-width:240px}.script-import-warning{color:#ffd18d;font-size:12px}.script-voice-busy #script-rows input,.script-voice-busy #script-rows textarea,.script-voice-busy #script-rows select{opacity:.65}#script-voice-tools .primary-button{width:auto;flex:none}#script-voice-tools .script-actions label{white-space:nowrap}#script-voice-tools .script-actions select{width:auto;min-width:100px;max-width:240px}#script-dialog .script-table-scroll{min-height:220px}#script-jobs{max-height:180px;overflow:auto}#script-jobs article{padding:8px;border-top:1px solid #315b73}#script-voice-tools{max-height:30vh;overflow:auto;flex:none}`;document.head.append(style);
 const message=text=>{$('script-batch-status').textContent=text;};
 const action=fn=>Promise.resolve().then(fn).catch(error=>message(error.message));
 const rows=()=>s.snapshot().scriptPlan.rows;
 const key=r=>r.character||({narrator:'旁白',inner:'心理描写',hero:'男主',heroine:'女主',dialogue:'未指定角色'}[r.kind]);
 const choices=selected=>'<option value="">请选择声音…</option>'+profiles.map(p=>`<option value="${p.id}" ${selected===p.id?'selected':''}>${e(p.name)}</option>`).join('');
 function edit(){s.changed();s.render();enhance();}
 function lock(value){$('script-dialog').classList.toggle('script-voice-busy',value);for(const id of ['script-rows','script-paste-box'])$(id).inert=value;for(const id of ['script-add','script-import-file','script-import-paste','script-batch-generate','script-rule-apply','script-save','script-build','script-refresh','script-add-lines'])$(id).disabled=value;$('script-batch-stop').hidden=!value;}
 function enhance(){
  const plan=s.snapshot().scriptPlan;
  const selected=$('script-rule-character').value;
  $('script-rule-character').innerHTML=[...new Set(rows().map(key))].map(c=>`<option ${selected===c?'selected':''}>${e(c)}</option>`).join('');
  const preset=$('script-rule-preset').value;$('script-rule-preset').innerHTML=choices(preset);
  $('script-source-notes').textContent=(plan.directives||[]).map(d=>`第 ${d.line} 行 · ${d.type}：${d.value}（待素材精修时确认）`).join('\n');
  $('script-rows').querySelectorAll('tr').forEach((tr,index)=>{
   const r=rows()[index];tr.querySelector('.script-voice-extra')?.remove();
   const block=document.createElement('div');block.className='script-voice-extra';
   block.innerHTML=`${r.source?`<small>来源：${e(r.source.file)} · 第 ${e(r.source.line)} 行</small>`:''}${r.warnings?.length?`<p class="script-import-warning">${r.warnings.map(e).join('；')}</p><label><input data-review type="checkbox" ${r.reviewed?'checked':''}>已确认解析与配音安排</label>`:''}<label>声音<select data-voice-preset aria-label="第 ${index+1} 句声音">${choices(r.voicePreset)}</select></label><label>语言<select data-voice-language aria-label="第 ${index+1} 句配音语言"><option value="">随预设</option>${[['zh','中文'],['ja','日语'],['en','英语'],['yue','粤语'],['ko','韩语']].map(([v,n])=>`<option value="${v}" ${r.language===v?'selected':''}>${n}</option>`).join('')}</select></label><button data-generate-one ${r.voice?'':'disabled'}>${r.audio?'重新生成':'生成本句'}</button>${r.versions?.length?`<label>配音版本<select data-take aria-label="第 ${index+1} 句配音版本">${!r.take?'<option value="">手动绑定的音频</option>':''}${r.versions.map((v,i)=>`<option value="${e(v)}" ${r.take===v?'selected':''}>版本 ${i+1}</option>`).join('')}</select></label>`:''}`;
   tr.children[3].append(block);
   block.querySelector('[data-review]')?.addEventListener('change',event=>{r.reviewed=event.target.checked;edit();});
   block.querySelector('[data-voice-preset]').onchange=event=>{r.voicePreset=event.target.value;edit();};
   block.querySelector('[data-voice-language]').onchange=event=>{r.language=event.target.value;edit();};
   block.querySelector('[data-generate-one]').onclick=()=>action(()=>generate([r.id]));
   block.querySelector('[data-take]')?.addEventListener('change',event=>action(async()=>{if(!event.target.value)return;const take=await api('/api/script/take',{id:event.target.value});Object.assign(r,take);edit();await s.refresh();}));
  });lock(Boolean(active));
 }
 //The table rebuilds after edits. Observe only its direct rows, not our nested controls.
 new MutationObserver(()=>enhance()).observe($('script-rows'),{childList:true});
 async function loadProfiles(){profiles=(await api('/api/script/presets')).items;enhance();}
 async function loadDrafts(){const data=await api('/api/script/drafts');$('script-drafts').innerHTML='<option value="">打开已保存剧本…</option>'+data.items.map(d=>`<option value="${d.id}">${e(d.name)} · ${e(new Date(d.updated).toLocaleString())}</option>`).join('');}
 async function saveDraft(){const draft=await api('/api/script/save',{id:draftId,name:$('cut-name').value,scriptPlan:structuredClone(s.snapshot().scriptPlan)});draftId=draft.id;await loadDrafts();message('独立剧本已保存，台词和配音版本都已保留；可在此处再次打开。');$('script-status').textContent='独立剧本已保存，无需先添加背景镜头。';}
 async function jobs(){const data=await api('/api/script/jobs');$('script-jobs').innerHTML=data.items.map(j=>`<article><strong>${e(j.name)}</strong> · ${e(new Date(j.created).toLocaleString())}<p>${e(j.message)}</p><button data-job="${j.id}">应用已生成结果</button><button data-recover="${j.id}">恢复该任务校对表</button>${['running','queued','stopping'].includes(j.state)?`<button data-watch="${j.id}">查看进度</button>`:''}</article>`).join('')||'<p>还没有批量配音任务。</p>';}
 function showErrors(job){const failed=job.results.filter(r=>r.state==='failed');$('script-job-errors').hidden=!failed.length;$('script-job-errors').open=Boolean(failed.length);$('script-job-error-list').innerHTML=failed.map(result=>{const index=job.plan.rows.findIndex(r=>r.id===result.rowId);return `<p>第 ${index+1} 句「${e(job.plan.rows[index]?.text.slice(0,25))}」：${e(result.message)}</p>`;}).join('');}
 async function apply(job){showErrors(job);if(!job.results.some(r=>r.state==='success')){message(job.message+'；本次没有生成新音频。');return;}s.merge(job.plan);await s.refresh();applied.add(job.id);message(job.message+'；已绑定台词，请保存校对表。');}
 async function poll(){if(!active)return;try{const job=await api('/api/script/job?id='+active);message(job.message);if(['queued','running','stopping'].includes(job.state)){timer=setTimeout(poll,2000);return;}active=null;lock(false);if(!applied.has(job.id))await apply(job);await jobs();}catch(error){message(error.message+'；可在任务记录中找回结果。');active=null;lock(false);}}
 async function generate(rowIds){if(active)throw new Error('请等待当前配音任务完成');const plan=structuredClone(s.snapshot().scriptPlan);const job=await api('/api/script/generate',{scriptPlan:plan,rowIds,name:$('cut-name').value});active=job.id;lock(true);message('任务已保存，开始逐句生成；关闭校对窗口后任务仍会继续。');clearTimeout(timer);timer=setTimeout(poll,500);}
 $('script-import-file').onclick=()=>action(async()=>{const pick=await api('/api/script/pick',{});if(!pick.paths?.[0])return;const plan=await api('/api/script/import',{path:pick.paths[0]});s.append(plan);enhance();message(`已导入 ${plan.rows.length} 句，请检查提示和配音安排。`);});
 const saveProject=$('script-save').onclick;
 $('script-save').onclick=()=>window.cutEditor.scenes.length?saveProject():action(saveDraft);
 $('script-save-standalone').onclick=()=>action(saveDraft);
 $('script-drafts').onchange=()=>action(async()=>{const id=$('script-drafts').value;if(!id)return;if(active)throw new Error('请等待配音任务结束');if(rows().length&&!window.confirm('打开剧本将替换当前校对表，请先保存未保存的修改。是否继续？'))return;const draft=await api('/api/script/draft?id='+id);s.adopt({scriptPlan:draft.plan});draftId=id;s.changed();await s.refresh();message('已打开独立剧本；当前画面镜头保留，铺轨前请核对素材。');});
 $('script-import-paste').onclick=()=>action(async()=>{const text=$('script-paste').value;if(!text.trim()){ $('script-paste-box').open=true;$('script-paste').focus();throw new Error('请在上方粘贴剧本后再解析');}const plan=await api('/api/script/import',{text});s.append(plan);$('script-paste').value='';enhance();message(`已解析 ${plan.rows.length} 句，场景说明已保留。`);});
 $('script-voice-config').onclick=()=>{$('script-dialog').close();window.switchPage('localtts');};
 $('script-capture-voice').onclick=()=>action(async()=>{const p=await api('/api/script/preset',{});await loadProfiles();message(`已保存「${p.name}」为批量声音预设；现在可以给角色绑定。`);});
 $('script-rule-character').onchange=()=>{$('script-rule-voice').checked=$('script-rule-character').value==='女主';};
 $('script-rule-apply').onclick=()=>{const character=$('script-rule-character').value;for(const r of rows().filter(r=>key(r)===character)){if(!r.voiceExplicit)r.voice=$('script-rule-voice').checked;r.voicePreset=$('script-rule-preset').value;r.language=$('script-rule-language').value;}edit();message('该角色的默认配音与声音绑定已应用，手动配音选择已保留。');};
 $('script-batch-generate').onclick=()=>action(()=>generate());
 $('script-start-service').onclick=()=>action(async()=>message((await api('/api/localtts/start',{})).message));
 $('script-batch-stop').onclick=()=>action(async()=>{message((await api('/api/script/stop',{id:active})).message);});
 $('script-jobs-refresh').onclick=()=>action(async()=>{await jobs();$('script-task-history').open=true;});
 $('script-jobs').onclick=event=>action(async()=>{const button=event.target.closest('button');if(!button)return;const id=button.dataset.job||button.dataset.recover||button.dataset.watch;const job=await api('/api/script/job?id='+id);if(button.dataset.watch){active=id;lock(true);clearTimeout(timer);poll();return;}if(active)throw new Error('请等待当前任务完成后再应用或恢复');if(button.dataset.recover){if(rows().length&&!window.confirm('恢复将替换当前校对表；当前未保存修改请先保存。是否恢复？'))return;s.adopt({scriptPlan:job.plan});s.changed();await s.refresh();message('已恢复校对表，请检查并保存。');}else await apply(job);});
 $('studio-script').addEventListener('click',()=>action(async()=>{await loadProfiles();await jobs();await loadDrafts();}));
 window.addEventListener('script-plan-rendered',enhance);
 window.addEventListener('cut-project-loaded',()=>{draftId=null;enhance();});
 action(loadProfiles);
})();

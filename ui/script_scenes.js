/*Explicit media identities: duplicated display names never pick a file for the author.*/
(()=>{
 const $=id=>document.getElementById(id),s=window.cutScript,e=window.cutEditor.escape;
 const panel=document.createElement('details');panel.id='script-scenes';panel.innerHTML='<summary>场景素材确认</summary><p>每段场景选一次实际图片，之后按素材编号沿用。名称相同也不会自动猜测；不涉及动态视频。</p><div id="script-scene-bindings"></div><p id="script-scenes-status" role="status"></p>';$('script-source-notes').closest('details').after(panel);
 let backgrounds=[];
 function render(){const plan=s.snapshot().scriptPlan,keys=new Set(plan.rows.map(r=>r.sceneKey).filter(Boolean)),notes=(plan.directives||[]).filter(d=>keys.has(d.id));
  $('script-scene-bindings').innerHTML=notes.length?notes.map(d=>{const id=plan.sceneBindings?.[d.id]||'',item=backgrounds.find(b=>b.id===id);return `<div class="script-scene-binding"><strong>第 ${e(d.line)} 行 · ${e(d.type)}：${e(d.value)}</strong><label>实际背景<select data-scene-key="${e(d.id)}"><option value="">请选择具体图片…</option>${backgrounds.filter(b=>b.kind==='image').map(b=>`<option value="${b.id}" ${b.id===id?'selected':''}>${e(b.name)} · ${b.width}×${b.height} · ${b.id.slice(0,8)}</option>`).join('')}${id&&!item?`<option value="${e(id)}" selected>已绑定图片丢失，请重新选择</option>`:''}</select></label>${item?`<img src="/api/backgrounds/thumb?id=${item.id}" alt="当前场景背景" style="width:160px;height:90px;object-fit:contain">`:''}</div>`;}).join(''):'<p>剧本没有场景标记，沿用基础镜头背景。</p>';
  $('script-scene-bindings').querySelectorAll('[data-scene-key]').forEach(n=>n.onchange=()=>s.bindScene(n.dataset.sceneKey,n.value));
 }
 async function refresh(){try{backgrounds=(await window.cutEditor.api('/api/backgrounds')).items;render();}catch(err){$('script-scenes-status').textContent=err.message;}}
 panel.addEventListener('toggle',()=>{if(panel.open)refresh();});window.addEventListener('script-plan-rendered',render);$('studio-script').addEventListener('click',refresh);render();
})();

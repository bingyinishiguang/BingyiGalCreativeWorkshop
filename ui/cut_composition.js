/*Expression calibration and aspect-specific composition presets.*/
(()=>{
  const $=id=>document.getElementById(id),editor=window.cutEditor,e=editor.escape;
  let groups=[],presets=[],selected=new Set(),draft=null,current=0,presetVisible=false;
  const assets=$('cut-assets').parentElement,bar=assets.querySelector('.production-actions');
  const groupButton=document.createElement('button');groupButton.id='cut-create-group';groupButton.textContent='建立表情组';
  const presetButton=document.createElement('button');presetButton.id='cut-preset-tab';presetButton.textContent='我的预设';
  bar.append(groupButton,presetButton);
  const presetPanel=document.createElement('div');presetPanel.id='cut-presets';presetPanel.hidden=true;assets.append(presetPanel);
  const dialog=document.createElement('dialog');dialog.id='expression-dialog';dialog.className='text-bulk-dialog';
  dialog.innerHTML='<h3>表情组与对齐</h3><p>同姿势共用一张画布。原始坐标可直接复用；只有 PNG 时请逐张核对。图片偏移以组画布左上角为原点，Y 向下。</p><label>组名<input id="group-name"></label><div class="production-filters"><label>画布宽<input id="group-width" type="number" min="1" max="20000"></label><label>画布高<input id="group-height" type="number" min="1" max="20000"></label><label>当前表情<select id="group-member"></select></label></div><div id="group-stage" class="group-stage"></div><label><input id="group-reference" type="checkbox" checked>叠加第一张作为对齐参考</label><p id="group-source"></p><div class="production-filters"><label>偏移 X<input id="group-left" type="number" step="1" min="-20000" max="20000"></label><label>偏移 Y<input id="group-top" type="number" step="1" min="-20000" max="20000"></label><label>校准缩放 %<input id="group-scale" type="number" min="5" max="2000" step="0.1"></label><button id="group-next" type="button">下一表情</button></div><p id="group-error" role="status"></p><div class="production-actions"><button id="group-save">保存表情组</button><button id="group-cancel">取消</button></div>';
  document.body.append(dialog);
  async function refresh(){const data=await editor.api('/api/composition');groups=data.groups;presets=data.presets;renderPresets();}
  async function action(fn){try{await fn();}catch(error){$('cut-status').textContent=error.message;}}
  const aspect=(w,h)=>{const gcd=(a,b)=>b?gcd(b,a%b):a,d=gcd(w,h);return `${w/d}:${h/d}`;};
  function decorateAssets(grid,items){
    const isSprite=$('cut-sprite-tab').classList.contains('active');groupButton.hidden=!isSprite;
    if(!isSprite)return;
    [...grid.children].forEach((card,index)=>{const item=items[index];if(!item||card.querySelector('.expression-pick'))return;
      const label=document.createElement('label');label.className='expression-pick';const input=document.createElement('input');input.type='checkbox';input.checked=selected.has(item.id);input.setAttribute('aria-label','选入表情组 '+(item.displayName||item.face));input.onchange=()=>{if(input.checked)selected.add(item.id);else selected.delete(item.id);};label.append(input,document.createTextNode('选入表情组'));card.append(label);
    });
  }
  function showDraft(value){draft=structuredClone(value);current=0;$('group-name').value=draft.name;$('group-width').value=draft.width;$('group-height').value=draft.height;$('group-member').innerHTML=draft.members.map((m,i)=>`<option value="${i}">${e(m.name||m.id)}</option>`).join('');$('group-error').textContent='';dialog.showModal();renderMember();}
  function renderMember(){const m=draft.members[current];$('group-member').value=current;$('group-left').value=m.left;$('group-top').value=m.top;$('group-scale').value=m.scale*100;$('group-source').textContent=m.mode||'人工校准';renderStage();}
  function renderStage(){const stage=$('group-stage');stage.replaceChildren();const stageWidth=Math.min(dialog.clientWidth-40,300*draft.width/draft.height);stage.style.width=stageWidth+'px';stage.style.height=stageWidth*draft.height/draft.width+'px';
    const add=(m,reference)=>{const image=new Image();image.src='/api/library/image?id='+encodeURIComponent(m.id);image.className='group-image';image.style.opacity=reference?.35:1;image.onload=()=>{image.style.width=image.naturalWidth*m.scale/draft.width*100+'%';image.style.height=image.naturalHeight*m.scale/draft.height*100+'%';};image.style.left=m.left/draft.width*100+'%';image.style.top=m.top/draft.height*100+'%';stage.append(image);};
    if($('group-reference').checked&&current!==0)add(draft.members[0],true);add(draft.members[current],false);
  }
  groupButton.onclick=()=>action(async()=>showDraft(await editor.api('/api/composition/group-suggest',{ids:[...selected]})));
  $('group-member').onchange=event=>{current=Number(event.target.value);renderMember();};
  $('group-next').onclick=()=>{current=(current+1)%draft.members.length;renderMember();};
  $('group-reference').onchange=renderStage;
  for(const [id,key] of [['group-left','left'],['group-top','top'],['group-scale','scale']])$(id).oninput=event=>{if(!event.target.value||!event.target.checkValidity())return;draft.members[current][key]=Number(event.target.value)/(key==='scale'?100:1);renderStage();};
  for(const [id,key] of [['group-width','width'],['group-height','height']])$(id).onchange=event=>{if(!event.target.value||!event.target.checkValidity())return;draft[key]=Number(event.target.value);renderStage();};
  $('group-cancel').onclick=()=>dialog.close();
  $('group-save').onclick=async()=>{try{if(![...dialog.querySelectorAll('input[type=number]')].every(n=>n.value&&n.checkValidity()))throw Error('请检查对齐参数');draft.name=$('group-name').value;await editor.api('/api/composition/group-save',draft);selected.clear();dialog.close();await refresh();editor.render();assets.querySelectorAll('.expression-pick input').forEach(n=>n.checked=false);$('cut-status').textContent='表情组已保存，请在角色属性中绑定';}catch(error){$('group-error').textContent=error.message;}};
  function memberPlacement(m){const {width,height,left,top,scale,groupId,version}=m;return {width,height,left,top,scale,groupId,version};}
  function replaceAlignment(actor,id){if(!actor.alignment)return;const group=groups.find(g=>g.id===actor.alignment.groupId&&g.version===actor.alignment.version);const m=group?.members.find(m=>m.id===id);if(m)actor.alignment=memberPlacement(m);else delete actor.alignment;}
  function renderActor(panel,actor){
    const available=groups.filter(g=>g.members.some(m=>m.id===actor.id));
    const section=document.createElement('div');section.className='expression-controls';section.innerHTML=`<label>表情组<select id="actor-expression-group"><option value="">单张立绘</option>${available.map(g=>`<option value="${g.id}">${e(g.name)}</option>`).join('')}</select></label><small>首次绑定共同画布后，请调整一次构图。</small>`;panel.append(section);
    $('actor-expression-group').value=actor.alignment?.groupId||'';
    $('actor-expression-group').onchange=event=>{const g=groups.find(g=>g.id===event.target.value);if(g){actor.alignment=memberPlacement(g.members.find(m=>m.id===actor.id));delete actor.transform;}else{delete actor.alignment;delete actor.transform;}editor.markDirty();editor.render();};
    const g=groups.find(g=>g.id===actor.alignment?.groupId);
    if(!g)return;
    const select=document.createElement('select');select.id='actor-expression';select.setAttribute('aria-label','切换表情');select.innerHTML=g.members.map(m=>`<option value="${m.id}">${e(m.name||m.id)}</option>`).join('');select.value=actor.id;select.onchange=()=>{const m=g.members.find(m=>m.id===select.value);actor.id=m.id;actor.alignment=memberPlacement(m);editor.markDirty();editor.render();};select.disabled=g.version!==actor.alignment.version;section.append(select);
    const edit=document.createElement('button');edit.id='edit-expression-group';edit.textContent='检查 / 校准表情组';edit.onclick=()=>showDraft(g);section.append(edit);
    if(g.version!==actor.alignment.version){const note=document.createElement('small');note.textContent='本项目仍保留旧版对齐；重新绑定才更新。';section.append(note);const update=document.createElement('button');update.textContent='重新绑定当前版';update.onclick=()=>{actor.alignment=memberPlacement(g.members.find(m=>m.id===actor.id));editor.markDirty();editor.render();};section.append(update);}
  }
  function renderPresets(){const {width,height}=editor.snapshot(),r=aspect(width,height),matching=presets.filter(p=>p.ratio===r);
    presetPanel.innerHTML=`<h3>我的构图预设 · ${r}</h3><p>保存当前镜头的人物与背景构图；同画幅可跨项目调用。应用时保留当前背景，载入预设人物。</p><button id="save-composition-preset">保存当前构图</button><div id="composition-preset-list">${matching.map(p=>`<div class="composition-preset"><strong>${e(p.name)}</strong><small>${p.width} × ${p.height} · ${p.actors.length} 位人物</small><div class="production-actions"><button data-apply-preset="${p.id}">应用</button><button data-rename-preset="${p.id}">改名</button><button data-delete-preset="${p.id}">删除</button></div></div>`).join('')||'<p>当前画幅还没有预设。</p>'}</div>`;
    $('save-composition-preset').onclick=()=>action(async()=>{const snapshot=structuredClone(editor.snapshot()),scene=snapshot.scenes[editor.activeScene];if(!scene)throw Error('请先添加镜头');if(scene.actors.some(a=>!a.transform))throw Error('请等待人物加载完成');const name=window.prompt('构图预设名称');if(!name?.trim())return;await editor.api('/api/composition/preset-save',{name,width:snapshot.width,height:snapshot.height,scene});await refresh();$('cut-status').textContent='构图预设已保存';});
    presetPanel.querySelectorAll('[data-apply-preset]').forEach(b=>b.onclick=()=>action(async()=>{const snapshot=editor.snapshot(),scene=snapshot.scenes[editor.activeScene];if(!scene)throw Error('请先添加镜头');const p=await editor.api('/api/composition/preset-apply',{id:b.dataset.applyPreset,width:snapshot.width,height:snapshot.height});scene.backgroundTransform=p.backgroundTransform;scene.actors=p.actors;editor.markDirty();editor.render();$('cut-status').textContent='构图预设已应用，可撤销';}));
    presetPanel.querySelectorAll('[data-rename-preset]').forEach(b=>b.onclick=()=>action(async()=>{const p=presets.find(p=>p.id===b.dataset.renamePreset),name=window.prompt('修改预设名称',p.name);if(!name?.trim())return;await editor.api('/api/composition/preset-rename',{id:p.id,name});await refresh();}));
    presetPanel.querySelectorAll('[data-delete-preset]').forEach(b=>b.onclick=()=>action(async()=>{if(!window.confirm('删除这份构图预设？已有项目不受影响。'))return;await editor.api('/api/composition/preset-delete',{id:b.dataset.deletePreset});await refresh();}));
  }
  presetButton.onclick=()=>action(async()=>{presetVisible=true;$('cut-assets').hidden=true;$('cut-asset-search').hidden=true;$('cut-assets-more').hidden=true;$('editor-audio-assets').hidden=true;groupButton.hidden=true;presetPanel.hidden=false;for(const id of ['cut-bg-tab','cut-sprite-tab','cut-audio-tab'])$(id).classList.remove('active');presetButton.classList.add('active');await refresh();});
  for(const id of ['cut-bg-tab','cut-sprite-tab','cut-audio-tab'])$(id).addEventListener('click',()=>{presetVisible=false;presetPanel.hidden=true;presetButton.classList.remove('active');groupButton.hidden=id!=='cut-sprite-tab';});
  window.addEventListener('cut-rendered',()=>{if(presetVisible)renderPresets();});
  window.addEventListener('workshop-page',event=>{if(event.detail==='roughcut')action(async()=>{await refresh();editor.render();});});
  window.cutComposition={decorateAssets,renderActor,replaceAlignment};
  groupButton.hidden=true;
})();
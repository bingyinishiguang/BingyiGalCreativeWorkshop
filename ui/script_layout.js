/*Story text templates and shared silent timing, independent of voice presets.*/
(()=>{
 const $=id=>document.getElementById(id),s=window.cutScript;
 const defaults=()=>({width:1920,height:1080,paginate:true,narrator:{x:192,y:840,width:1536,height:192,size:36,lineHeight:48},dialogue:{x:240,y:840,width:1488,height:192,size:36,lineHeight:48},name:{x:240,y:780,width:1488,height:48,size:36,lineHeight:48,enabled:true}});
 const panel=document.createElement('details');panel.id='script-layout';
 panel.innerHTML='<summary>剧情文字排版与默认时长</summary><p>坐标从画布左上角起算，使用整数像素；旁白和心理描写共用区域。角色名单独显示，正文起点固定。区域按参考画布比例适配项目。</p><div class="story-layout-fields"></div><div class="production-actions"><button id="script-layout-apply">应用排版与默认时长</button></div><p id="script-layout-status" role="status"></p>';
 $('script-paste-box').before(panel);
 const css=document.createElement('style');css.textContent='#script-layout{max-height:24vh}#script-layout .production-filters{display:grid;grid-template-columns:repeat(6,minmax(90px,1fr));gap:6px}#script-layout .production-filters label{font-size:12px}#script-layout input[type=number]{width:100%;box-sizing:border-box}#script-dialog:has(#script-layout[open]) #script-voice-tools{display:none}#script-dialog:has(#script-layout[open]) .script-table-scroll{min-height:120px}';document.head.append(css);
 function show(){const plan=s.snapshot().scriptPlan,l=plan.layout||defaults(),t=plan.timing||{silentHold:3,dialogueHold:3};
  panel.querySelector('.story-layout-fields').innerHTML=`<label><input id="story-paginate" type="checkbox" ${l.paginate?'checked':''}>长文字自动分页（整句时长内均分，配音只播放一次）</label><div class="production-filters"><label>参考画布宽<input data-layout="width" type="number" step="1" value="${l.width}"></label><label>参考画布高<input data-layout="height" type="number" step="1" value="${l.height}"></label><label>旁白 / 心理停留（秒）<input id="story-silent" type="number" min="0.1" max="3590" step="0.1" value="${t.silentHold}"></label><label>无配音对话停留（秒）<input id="story-dialogue" type="number" min="0.1" max="3590" step="0.1" value="${t.dialogueHold}"></label></div>`+Object.entries({narrator:'旁白 / 心理正文',dialogue:'对话正文',name:'角色名'}).map(([key,label])=>`<fieldset><legend>${label}</legend><div class="production-filters">${Object.entries({x:'起点 X',y:'起点 Y',width:'宽度',height:'高度',size:'字号',lineHeight:'行高'}).map(([f,n])=>`<label>${n}<input data-box="${key}" data-prop="${f}" type="number" step="1" value="${l[key][f]}"></label>`).join('')}${key==='name'?`<label><input id="story-name-enabled" type="checkbox" ${l.name.enabled?'checked':''}>对话显示角色名</label>`:''}</div></fieldset>`).join('');
 }
 $('script-layout-apply').onclick=()=>{try{const l=defaults();panel.querySelectorAll('[data-layout]').forEach(n=>l[n.dataset.layout]=Number(n.value));panel.querySelectorAll('[data-box]').forEach(n=>l[n.dataset.box][n.dataset.prop]=Number(n.value));l.name.enabled=$('story-name-enabled').checked;l.paginate=$('story-paginate').checked;
   if(![l.width,l.height].every(n=>Number.isInteger(n)&&n>=320&&n<=3840))throw Error('参考画布边长应为 320–3840 整数像素');
   for(const k of ['narrator','dialogue','name']){const b=l[k];if(!Object.values(b).filter(v=>typeof v==='number').every(Number.isInteger)||b.x<0||b.y<0||b.width<1||b.height<1||b.x+b.width>l.width||b.y+b.height>l.height||b.size<12||b.size>240||b.lineHeight<b.size||b.lineHeight>480)throw Error('请检查文字区域：字号 12–240，行高不小于字号，区域须位于画布内');}
   const timing={silentHold:Number($('story-silent').value),dialogueHold:Number($('story-dialogue').value)};if(!Object.values(timing).every(n=>Number.isFinite(n)&&n>=.1&&n<=3590))throw Error('默认停留应为 0.1–3590 秒');
   s.configure({layout:l,timing});enhance();$('script-layout-status').textContent='已应用；确认校对后重新计算并铺轨。单句手动时长保留，可点击“使用默认时长”恢复。';
  }catch(err){$('script-layout-status').textContent=err.message;}};
 function enhance(){const plan=s.snapshot().scriptPlan;document.querySelectorAll('#script-rows tr').forEach((tr,i)=>{if(!plan.timing||tr.querySelector('.story-default-hold'))return;const r=plan.rows[i],field=tr.querySelector('[data-field="hold"]');if(!field)return;
   const inherited=r.holdExplicit===false;field.value=inherited?plan.timing[['narrator','inner'].includes(r.kind)?'silentHold':'dialogueHold']:r.hold;
   const button=document.createElement('button');button.className='story-default-hold';button.textContent=inherited?'使用默认时长 ✓':'使用默认时长';button.disabled=r.voice;button.onclick=()=>{s.useDefault(i);enhance();};field.parentElement.after(button);
  });}
 new MutationObserver(enhance).observe($('script-rows'),{childList:true});
 window.addEventListener('script-plan-rendered',()=>{show();enhance();});
 $('studio-script').addEventListener('click',show);
 $('script-build').textContent='计算并铺入时间轴';show();
})();

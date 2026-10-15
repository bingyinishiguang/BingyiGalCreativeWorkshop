/*Pure timeline checks: editing feedback; server validation remains authoritative.*/
(() => {
  function check(project,audioItems=[]) {
    const stable=value=>JSON.stringify(value,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.entries(v).sort(([a],[b])=>a.localeCompare(b))):v);
    const buckets=[[],[],[],[]],audio=project.audioClips||[],texts=project.textClips||[];
    let errorCount=0,warningCount=0,totalIssueCount=0,firstSave=null,firstExport=null;
    const fps=Number(project.fps)||30;
    const visualEnd=(project.scenes||[]).reduce((sum,s)=>sum+Math.round(Number(s.duration)*fps)/fps,0);
    const add=(code,message,kind,index,extra={})=>{
      const issue={code,message,kind,index,level:'error',blocksSave:true,blocksExport:true,...extra};
      const entry={issue,order:totalIssueCount++};
      if(issue.level==='warning')warningCount++;else errorCount++;
      if(issue.blocksSave&&!firstSave)firstSave=entry;
      if(issue.blocksExport&&!firstExport)firstExport=entry;
      const priority=issue.blocksSave?3:issue.blocksExport?2:issue.level==='error'?1:0;
      //Bound display storage, while all checks still contribute to the verdict.
      if(buckets[priority].length<100)buckets[priority].push(entry);
    };
    const finite=value=>Number.isFinite(Number(value));
    const groups=new Map();
    audio.forEach((clip,index)=>{
      const name=audioItems.find(item=>item.id===clip.audio)?.name||`音频 ${index+1}`;
      const item=audioItems.find(item=>item.id===clip.audio);
      if(!finite(clip.start)||clip.start<0||!finite(clip.duration)||clip.duration<=0||clip.start+clip.duration>10800)add('audio-time',`${name}：开始时间或时长无效`,'audio',index);
      if(!finite(clip.sourceStart)||clip.sourceStart<0||(item&&clip.sourceStart+clip.duration>item.duration+.001))add('audio-source',`${name}：裁切超出原音频范围`,'audio',index);
      if(!finite(clip.track)||clip.track<0||clip.track>15)add('audio-track',`${name}：轨道编号应为 1–16`,'audio',index);
      const volume=clip.volume??1;
      if(!finite(volume)||volume<0||volume>2)add('audio-volume',`${name}：音量倍率应为 0–2`,'audio',index);
      if(item?.missing)add('audio-missing',`${name}：素材文件丢失`,'audio',index);
      if(clip.start+clip.duration>visualEnd+.001)add('coverage',`${name}：超出画面 ${(clip.start+clip.duration-visualEnd).toFixed(2)} 秒`,'audio',index,{blocksSave:false,fix:'extend'});
      const key=clip.kind+':'+clip.track;if(!groups.has(key))groups.set(key,[]);groups.get(key).push({...clip,index,name});
      const cues=(clip.cues||[]).map((cue,cueIndex)=>({...cue,cueIndex}));
      cues.forEach(cue=>{if(!finite(cue.start)||!finite(cue.end)||cue.start<0||cue.end<=cue.start||(item&&cue.end>item.duration+.05)||!String(cue.text||'').trim()||String(cue.text).length>2000)add('cue-invalid',`${name}：第 ${cue.cueIndex+1} 条字幕的时间或文字无效`,'caption',index,{cueIndex:cue.cueIndex});});
      const sorted=cues.filter(c=>finite(c.start)&&finite(c.end)).sort((a,b)=>a.start-b.start);let latest=null;
      sorted.forEach(cue=>{if(latest&&cue.start<latest.end-1e-6)add('cue-overlap',`${name}：字幕 ${latest.cueIndex+1} 与 ${cue.cueIndex+1} 重叠；预览保留两条，同坐标可能叠字`,'caption',index,{cueIndex:cue.cueIndex,level:'warning',blocksSave:false,blocksExport:false});if(!latest||cue.end>latest.end)latest=cue;});
    });
    groups.forEach(clips=>{clips.sort((a,b)=>a.start-b.start);let latest=null;clips.forEach(clip=>{if(latest&&clip.start<latest.start+latest.duration-1e-6)add('audio-overlap',`${latest.name} 与 ${clip.name} 在同一音频轨重叠，请换轨或调整时间`,'audio',clip.index,{otherIndex:latest.index,fix:'track'});if(!latest||clip.start+clip.duration>latest.start+latest.duration)latest=clip;});});
    if(project.scriptTiming&&(stable(project.scriptTiming.plan)!==stable(project.scriptPlan)||(project.scriptTiming.base&&stable(project.scriptTiming.base)!==stable(project.scriptBase))))add('script-stale','台词或配音已修改，请在台词校对中重新计算并铺轨','script',0,{blocksSave:false});
    texts.forEach((clip,index)=>{
      if(clip.layout?.pages?.length>1&&clip.duration/clip.layout.pages.length<.8)add('page-reading',`文字 ${index+1}：平均每页少于 0.8 秒，请试听并检查阅读节奏`,'text',index,{level:'warning',blocksSave:false,blocksExport:false});
      if(clip.layout?.overflow)add('text-overflow',`文字 ${index+1}：超出剧情文字区域，请扩大区域或拆分台词`,'text',index,{blocksSave:false});
      if(!finite(clip.start)||clip.start<0||!finite(clip.duration)||clip.duration<=0||clip.duration>3600||clip.start+clip.duration>10800)add('text-time',`文字 ${index+1}：开始时间或时长无效`,'text',index);
      if(!String(clip.text||'').trim()||String(clip.text).length>2000)add('text-content',`文字 ${index+1}：内容不能为空且最多两千字`,'text',index);
      if(clip.start+clip.duration>visualEnd+.001)add('coverage',`文字 ${index+1}：超出画面 ${(clip.start+clip.duration-visualEnd).toFixed(2)} 秒`,'text',index,{blocksSave:false,fix:'extend'});
    });
    const displayed=[...buckets[3],...buckets[2],...buckets[1],...buckets[0]].slice(0,100);
    //Both failed actions must have a visible explanation, even with mixed blockers.
    for(const required of [firstSave,firstExport])if(required&&!displayed.includes(required)){
      const replace=displayed.findLastIndex(entry=>entry!==firstSave&&entry!==firstExport);
      if(replace>=0)displayed[replace]=required;
    }
    const issues=displayed.sort((a,b)=>a.order-b.order).map(entry=>entry.issue);
    return {issues,visualEnd,canSave:!firstSave,canExport:!firstExport,errorCount,warningCount,totalIssueCount};
  }
  globalThis.cutValidation={check};
})();

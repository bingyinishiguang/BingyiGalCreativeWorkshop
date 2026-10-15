const {test}=require('node:test');
const assert=require('node:assert/strict');
require('../ui/cut_validation.js');
const check=globalThis.cutValidation.check;
const items=[{id:'voice',name:'测试配音',duration:4,missing:false}];
const clip=(values={})=>({audio:'voice',start:0,sourceStart:0,duration:4,kind:'dialogue',track:0,volume:1,cues:[],...values});
const project=(values={})=>({fps:30,scenes:[{duration:10}],audioClips:[],textClips:[],...values});

test('fast text pages are a reading warning, not an artificial voice cutoff',()=>{
  const checked=check(project({textClips:[{text:'长文字',start:0,duration:2,track:0,layout:{pages:[['一'],['二'],['三']]}}]}));
  assert(checked.issues.some(i=>i.code==='page-reading'&&i.level==='warning'));
  assert.equal(checked.canExport,true);
});

test('same-kind same-track overlap blocks saving; other tracks and kinds remain independent',()=>{
  const invalid=check(project({audioClips:[clip(),clip({start:2})]}),items);
  assert.equal(invalid.canSave,false);assert.equal(invalid.issues[0].code,'audio-overlap');
  for(const changed of [{track:1},{kind:'bgm'}])assert.equal(check(project({audioClips:[clip(),clip({start:2,...changed})]}),items).canExport,true);
});
test('coverage is editable and savable but cannot be exported, with explicit extend action',()=>{
  const result=check(project({scenes:[{duration:2}],audioClips:[clip()],textClips:[{start:3,duration:2,text:'无声旁白'}]}),items);
  assert.equal(result.canSave,true);assert.equal(result.canExport,false);
  assert.equal(result.issues.filter(i=>i.fix==='extend').length,2);
});
test('audio trim cannot exceed the original file',()=>{
  assert.equal(check(project({audioClips:[clip({sourceStart:1,duration:4})]}),items).issues[0].code,'audio-source');
  assert.equal(check(project({audioClips:[clip({sourceStart:1,duration:3})]}),items).canSave,true);
});
test('overlapping cues retain their original indexes and produce a warning without silently deleting text',()=>{
  const cues=[{start:2,end:3,text:'后一句'},{start:1,end:2.5,text:'前一句'}];
  const result=check(project({audioClips:[clip({cues})]}),items);
  assert.equal(result.canExport,true);assert.equal(result.issues.length,1);
  assert.equal(result.issues[0].code,'cue-overlap');assert.equal(result.issues[0].cueIndex,0);
  assert.equal(cues.length,2);
});
test('invalid subtitle text and out-of-source ranges block save',()=>{
  for(const cue of [{start:0,end:1,text:''},{start:0,end:5,text:'超出'},{start:NaN,end:1,text:'坏时间'}])assert.equal(check(project({audioClips:[clip({cues:[cue]})]}),items).canSave,false);
});
test('visual coverage uses frame-quantized scene boundaries',()=>{
  const result=check(project({fps:30,scenes:[{duration:.05},{duration:.05}],textClips:[{start:0,duration:.12,text:'按帧覆盖'}]}));
  assert.equal(result.canExport,true);assert.ok(Math.abs(result.visualEnd-4/30)<1e-8);
});
test('invalid volume and excessively long cues are caught before save',()=>{
  assert.equal(check(project({audioClips:[clip({volume:3})]}),items).canSave,false);
  assert.equal(check(project({audioClips:[clip({cues:[{start:0,end:1,text:'字'.repeat(2001)}]})]}),items).canSave,false);
});

const readingWarnings=count=>Array.from({length:count},(_,index)=>({text:'阅读提醒',start:index/30,duration:1/30,layout:{pages:[['一'],['二']]}}));

test('display limit cannot hide a later invalid text or change the full issue counts',()=>{
  const result=check(project({textClips:[...readingWarnings(100),{text:'',start:5,duration:1}]}));
  assert.equal(result.issues.length,100);
  assert.equal(result.canSave,false);assert.equal(result.canExport,false);
  assert.equal(result.issues.find(i=>i.blocksSave).code,'text-content');
  assert.equal(result.errorCount,1);assert.equal(result.warningCount,100);assert.equal(result.totalIssueCount,101);
  assert.deepEqual(result.issues.filter(i=>i.level==='warning').map(i=>i.index),Array.from({length:99},(_,i)=>i));
});

test('export-only blockers remain visible after warnings while saving stays allowed',()=>{
  const result=check(project({textClips:[...readingWarnings(100),{text:'画面以外',start:10,duration:1}]}));
  assert.equal(result.canSave,true);assert.equal(result.canExport,false);
  assert.equal(result.issues.find(i=>i.blocksExport).code,'coverage');
  assert.equal(result.errorCount,1);assert.equal(result.warningCount,100);assert.equal(result.totalIssueCount,101);
});

test('a later save blocker is retained after one hundred export-only blockers',()=>{
  const outside=Array.from({length:100},(_,index)=>({text:'画面以外',start:20+index,duration:1}));
  const result=check(project({textClips:[...outside,{text:'',start:0,duration:1}]}));
  assert.equal(result.issues.length,100);assert.equal(result.canSave,false);assert.equal(result.canExport,false);
  assert.equal(result.issues.find(i=>i.blocksSave).code,'text-content');
  assert(result.issues.find(i=>i.blocksExport));
  assert.equal(result.errorCount,101);assert.equal(result.totalIssueCount,101);
  assert.deepEqual(result.issues.filter(i=>i.code==='coverage').map(i=>i.index),Array.from({length:99},(_,i)=>i));
});

test('warning-only overflow keeps the original first hundred and accurate totals',()=>{
  const result=check(project({textClips:readingWarnings(125)}));
  assert.equal(result.canSave,true);assert.equal(result.canExport,true);
  assert.equal(result.issues.length,100);assert.equal(result.warningCount,125);assert.equal(result.errorCount,0);assert.equal(result.totalIssueCount,125);
  assert.deepEqual(result.issues.map(i=>i.index),Array.from({length:100},(_,i)=>i));
});

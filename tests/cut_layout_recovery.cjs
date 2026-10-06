const assert=require('node:assert/strict');
const {createCutLayoutRecovery}=require('../ui/cut_workspace.js');
const frames=[],timers=[];
let visible=false,width=0,measurements=[],calls=0;
const recovery=createCutLayoutRecovery({frame:callback=>frames.push(callback),delay:(callback,ms)=>timers.push({callback,ms}),measure:()=>{calls++;if(visible&&width>0)measurements.push(width);}});
const flush=()=>{while(frames.length)frames.shift()();};
//Restore notification arrives before webview has a nonzero viewport.
recovery.recover();recovery.schedule();flush();
assert.deepEqual(measurements,[]);assert.equal(calls,1);
visible=true;width=900;
timers.find(t=>t.ms===100).callback();flush();
assert.deepEqual(measurements,[900]);
width=1100;timers.find(t=>t.ms===300).callback();flush();
assert.deepEqual(measurements,[900,1100]);
assert.equal(timers.length,2,'recovery has a bounded retry budget');
//A newer restore supersedes old delayed work; resize bursts coalesce.
timers.length=0;recovery.recover();recovery.recover();flush();
const before=calls;timers[0].callback();timers[1].callback();flush();assert.equal(calls,before);
for(let i=0;i<20;i++)recovery.schedule();flush();assert.equal(calls,before+1);
console.log('cut layout recovery passed');

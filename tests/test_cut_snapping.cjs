const assert=require('node:assert/strict');
const {resolveCutSnap:snap}=require('../ui/cut_workspace.js');
const near=(a,b)=>assert(Math.abs(a-b)<1e-8,`${a} != ${b}`);
for(const zoom of [5,35,120]){
  near(snap(5+7/zoom,{zoom,targets:[5]}).time,5);
  assert.equal(snap(5+9/zoom,{zoom,targets:[5]}).guide,null);
}
near(snap(4.9,{targets:[5,4.933333333],zoom:35}).time,4.933333333333333);
near(snap(3.1,{targets:[5],offsets:[0,2]}).time,3);
near(snap(4.9,{targets:[5],enabled:false}).time,4.9);
assert.equal(snap(4.9,{targets:[5],enabled:false}).guide,null);
assert.equal(snap(4.9,{targets:[5],max:4.95}).guide,null);
near(snap(-.1,{targets:[0]}).time,0);
near(snap(2.06,{fps:25,enabled:false}).time,2.08);
near(snap(4.9,{targets:[NaN,Infinity,5]}).time,5);
assert.equal(snap(4.9,{targets:[]}).guide,null);
// Source-media limits can fall between frames; clamping cannot grow past them.
near(snap(5,{targets:[5],max:4.913}).time,4.913);
console.log('Cut snapping: pixel tolerance, nearest edge, trailing-edge move, bypass, frame quantization and source bounds passed');

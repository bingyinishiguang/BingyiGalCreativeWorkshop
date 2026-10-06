const test=require('node:test'),assert=require('node:assert/strict');
const g=require('../ui/cut_geometry.js');
test('replacement preserves a manually adjusted half-body framing',()=>{
  const original={id:'smile',slot:0,x:0,height:.9,transform:{scaleX:180,scaleY:180,x:120,y:-360,rotation:8,uniform:true}};
  const replacement=g.replaceActor(original,'surprise',0,false);
  assert.deepEqual(replacement,{...original,id:'surprise'});
  assert.equal(original.id,'smile');
});
test('old bottom-aligned placement survives migration',()=>{
  const t=g.defaults(1920,1080,101,401,{x:.45,height:.9});
  const style=g.style(1920,1080,101,401,t);
  assert.equal(style.height,'90%');assert.equal(style.left,'72.5%');
  assert.ok(Math.abs(parseFloat(style.top)-55)<1e-8);
});
test('pixel position, independent scales and clockwise rotation reach preview',()=>{
  const style=g.style(1080,1920,400,700,{scaleX:200,scaleY:100,x:108,y:-192,rotation:15});
  assert.equal(style.left,'60%');assert.equal(style.top,'60%');
  assert.equal(style.width,'200%');assert.equal(style.transform,'translate(-50%,-50%) rotate(15deg)');
});

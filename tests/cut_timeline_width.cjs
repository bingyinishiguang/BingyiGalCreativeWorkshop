const assert=require('node:assert/strict');
const {calculateCutTimelineWidth}=require('../ui/cut_workspace.js');
for(const viewport of [700,1160,1920])for(const zoom of [5,35,120]){
 const width=calculateCutTimelineWidth(10,zoom,viewport);
 assert(width+180>=viewport,'empty or short projects fill viewport');
 assert(width>=10*zoom,'clips retain seconds-to-pixel scale');
}
assert(calculateCutTimelineWidth(600,120,1920)>1920,'long projects retain horizontal scrolling');
console.log('timeline viewport coverage passed');
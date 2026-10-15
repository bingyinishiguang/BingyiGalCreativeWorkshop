const fs = require('node:fs');
const path = require('node:path');

function createDraftFixture(file) {
  const texts = ['今天想说几句话。','yinggaidou 向大家问好。','最后谢谢大家。','备用字幕。'];
  const material = (text,i) => ({id:`text-${i}`,content:JSON.stringify({text,styles:[{range:[0,text.length],size:8,color:[1,1,1]}]}),font_size:8});
  const segment = (i,start) => ({id:`segment-${i}`,material_id:`text-${i}`,target_timerange:{start,duration:1000000},source_timerange:{start:0,duration:1000000},clip:{transform:{x:0,y:-0.6},scale:{x:1,y:1}}});
  const draft = {id:'fixture-draft',duration:4000000,materials:{texts:texts.map(material),videos:[]},tracks:[
    {type:'video',segments:[]},
    {type:'text',name:'主字幕',segments:[segment(0,0),segment(1,1000000),segment(2,2000000)]},
    {type:'text',name:'备用字幕',segments:[segment(3,0)]}
  ]};
  fs.mkdirSync(path.dirname(file),{recursive:true});
  fs.writeFileSync(file,JSON.stringify(draft));
  return file;
}

module.exports = {createDraftFixture};

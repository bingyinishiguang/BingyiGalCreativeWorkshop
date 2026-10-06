/*Positions use canvas pixels, centre origin, X right / Y up.*/
((root) => {
  const defaults=(w,h,sw,sh,actor=null)=>{
    const fit=Math.min(w/sw,h/sh),height=actor?.height??.9;
    const scale=actor?h*height/(sh*fit)*100:Math.max(w/sw,h/sh)/fit*100;
    return {scaleX:scale,scaleY:scale,x:actor?(actor.x??0)*w/2:0,
      y:actor?(height-1)*h/2:0,rotation:0,uniform:true};
  };
  const style=(w,h,sw,sh,t)=>{
    const fit=Math.min(w/sw,h/sh);
    return {width:sw*fit*t.scaleX/100/w*100+'%',height:sh*fit*t.scaleY/100/h*100+'%',
      left:(.5+t.x/w)*100+'%',top:(.5-t.y/h)*100+'%',
      transform:`translate(-50%,-50%) rotate(${t.rotation}deg)`};
  };
  const replaceActor=(previous,id,slot,hasOther)=>previous?{...previous,id}:
    {id,slot,x:slot===0?(hasOther?-.45:0):.45,height:.9};
  const api={defaults,style,replaceActor};
  if(typeof module!=='undefined')module.exports=api;
  else root.cutGeometry=api;
})(globalThis);

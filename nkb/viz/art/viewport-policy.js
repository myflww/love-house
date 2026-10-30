/* Pure, deterministic viewport policy for the 2D and 3D knowledge graph.
 * Sizes are CSS pixels. targetReadableCoreDiameter is the visible neuron core,
 * NOT the point-sprite quad (the renderer supplies its own shader falloff).
 * Bounds always include every supplied point: this policy never clips outliers
 * to make the remaining graph appear bigger. Layout may compact components.
 */
const clamp=(value,low,high)=>Math.max(low,Math.min(high,value));
const finite=(value,fallback=0)=>typeof value==='number'&&Number.isFinite(value)?value:fallback;
const MAX_MAGNITUDE=1e100;
function sensible(value){return typeof value==='number'&&Number.isFinite(value)&&Math.abs(value)<=MAX_MAGNITUDE;}
function countOf(value){return Math.floor(clamp(finite(value),0,10000000));}

function viewportRect(value={}){
 const x=finite(value.x,finite(value.left)),y=finite(value.y,finite(value.top));
 const width=finite(value.width,finite(value.w)),height=finite(value.height,finite(value.h));
 const valid=sensible(x)&&sensible(y)&&width>0&&height>0&&width<=MAX_MAGNITUDE&&height<=MAX_MAGNITUDE;
 return {x:sensible(x)?x:0,y:sensible(y)?y:0,width:clamp(width||1,1,MAX_MAGNITUDE),height:clamp(height||1,1,MAX_MAGNITUDE),valid};
}

/** Count/available-area policy. Pass the canvas area AFTER subtracting panels. */
export function nodeCountPolicy(count,viewport={width:1000,height:700}){
 const n=countOf(count),v=viewportRect(viewport),short=Math.min(v.width,v.height);
 const basePad=clamp(short*.055,12,44);
 // Clamped fractional insets leave a usable frame even for very small windows.
 const padding={left:Math.min(basePad,v.width*.22),right:Math.min(basePad,v.width*.22),
                top:Math.min(basePad+22,v.height*.22),bottom:Math.min(basePad+24,v.height*.22)};
 const width=v.width-padding.left-padding.right,height=v.height-padding.top-padding.bottom;
 const area=Math.max(.01,width*height),density=n?Math.pow(n/(n+120),.45):0;
 const pitch=n?Math.sqrt(area/n):short;
 const desiredCore=n?2+18/(1+Math.pow(n/45,.9)):0;
 const core=n?Math.max(.65,Math.min(desiredCore,pitch*.4)):0;
 const labelsByArea=clamp(Math.floor(area/6500),1,96);
 const labelBudget=n?Math.min(n,Math.max(1,Math.floor(labelsByArea/(1+Math.pow(n/180,1.6))))):0;
 return {count:n,density,padding,
   coverage:n ? .70+.20*Math.exp(-Math.sqrt(n)/18) : 0,
   maxAutoScale:n ? .9+6/(1+Math.pow(n/9,.68)) : 1,
   targetReadableCoreDiameter:core,targetNodeDiameter:core,
   labelBudget,labelMaxChars:Math.round(clamp(v.width*.026,8,28)),
   // These replace the old fixed large gaps which made 3 or 72 isolated memories
   // orbit hundreds of units from the center. Connected groups still grow sqrt(N).
   nodeSpacing:12+8*density,groupSpacing:10+6*density,
   minMainRadius:24+42*density,minComponentRadius:16+13*density,
   minGroupRadius:12+9*density,componentGap:18+54*density,
   componentSpacing:15+23*density};
}

function boundsRect(value,minimumSpan){
 let x,y,w,h;
 if(value&&sensible(value.x)&&sensible(value.y)&&sensible(value.w)&&sensible(value.h)){
  ({x,y,w,h}=value);
 }else if(value&&['minX','minY','maxX','maxY'].every(key=>sensible(value[key]))){
  x=value.minX;y=value.minY;w=value.maxX-x;h=value.maxY-y;
 }else{return {x:-minimumSpan/2,y:-minimumSpan/2,w:minimumSpan,h:minimumSpan,valid:false};}
 if(w<0){x+=w;w=-w;}if(h<0){y+=h;h=-h;}
 if(![x,y,w,h,x+w,y+h].every(sensible))return {x:-minimumSpan/2,y:-minimumSpan/2,w:minimumSpan,h:minimumSpan,valid:false};
 const cx=x+w/2,cy=y+h/2;
 w=Math.max(w,minimumSpan);h=Math.max(h,minimumSpan);
 return {x:cx-w/2,y:cy-h/2,w,h,valid:true};
}

function insetFrame(v,padding){
 const p=typeof padding==='number'?{left:padding,right:padding,top:padding,bottom:padding}:padding||{};
 const left=clamp(finite(p.left),0,v.width*.45),right=clamp(finite(p.right),0,v.width*.45);
 const top=clamp(finite(p.top),0,v.height*.45),bottom=clamp(finite(p.bottom),0,v.height*.45);
 return {x:v.x+left,y:v.y+top,width:v.width-left-right,height:v.height-top-bottom,padding:{left,right,top,bottom}};
}

/**
 * Fit a world-space or projected-at-unit-scale bounding rectangle. x/y/k describe
 * a 2D affine camera: screen = world*k + (x,y). For 3D, consume scale/center/frame
 * and perform the renderer's projection-aware translation rather than reusing
 * the 2D affine translation. Every bound is contained, even beyond nominal zoom
 * limits; minScale is a preference and cannot force a crop.
 */
export function planViewport(bounds,viewport,count=0,options={}){
 const policy=nodeCountPolicy(count,viewport),v=viewportRect(viewport);
 const frame=insetFrame(v,options.padding??policy.padding);
 const center={x:frame.x+frame.width/2,y:frame.y+frame.height/2};
 if(!policy.count)return {scale:1,k:1,x:center.x,y:center.y,center,frame,
   content:{x:center.x,y:center.y,width:0,height:0},bounds:null,policy,
   empty:true,valid:v.valid,fullyVisible:true,minScaleRelaxed:false,limitedBy:'empty'};
 const minimumSpan=clamp(finite(options.minimumSpan,36),.001,1000000);
 const b=boundsRect(bounds,minimumSpan);
 const coverage=clamp(finite(options.coverage,policy.coverage),.05,1);
 const widthScale=frame.width/b.w,heightScale=frame.height/b.h;
 const fitting=Math.min(widthScale,heightScale)*coverage;
 const maxScale=clamp(finite(options.maxScale,policy.maxAutoScale),1e-100,1000000);
 const requestedMin=Math.max(0,finite(options.minScale));
 // The lower zoom limit must never hide far-away memories. A very large extent
 // can legitimately need a smaller scale than manual wheel controls normally use.
 const scale=Math.max(1e-100,Math.min(fitting,maxScale));
 const x=center.x-(b.x+b.w/2)*scale,y=center.y-(b.y+b.h/2)*scale;
 const content={x:b.x*scale+x,y:b.y*scale+y,width:b.w*scale,height:b.h*scale};
 const tolerance=1e-7*Math.max(1,frame.width,frame.height);
 const contained=content.x>=frame.x-tolerance&&content.y>=frame.y-tolerance
   &&content.x+content.width<=frame.x+frame.width+tolerance
   &&content.y+content.height<=frame.y+frame.height+tolerance;
 return {scale,k:scale,x,y,center,frame,content,bounds:b,policy,empty:false,
   valid:v.valid&&b.valid,fullyVisible:contained&&v.valid&&b.valid,
   minScaleRelaxed:requestedMin>scale,
   limitedBy:maxScale<fitting?'maxScale':widthScale<heightScale?'width':'height'};
}

export function fitScale(bounds,viewport,options={}){
 const count=typeof options==='number'?options:options.count;
 return planViewport(bounds,viewport,count,typeof options==='number'?{}:options).scale;
}

export const viewportPolicy={nodeCountPolicy,fitScale,planViewport};

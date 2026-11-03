/* Keep the pinned OrbitControls gesture state in sync with pointer ownership.
 * A lost capture or window blur need not deliver pointerup. Without cancellation
 * the next mouse-down can reuse the old pointer's Shift/PAN state indefinitely.
 */
import {MOUSE, TOUCH} from 'three';

export function bindOrbitInput(controls, surface){
 const active=new Map(),releases=[];
 const doc=surface.ownerDocument||globalThis.document,host=doc?.defaultView||globalThis.window;
 const listen=(target,type,handler,options)=>{
  if(!target?.addEventListener)return;
  target.addEventListener(type,handler,options);
  releases.push(()=>target.removeEventListener(type,handler,options));
 };
 controls.mouseButtons.LEFT=MOUSE.ROTATE;
 controls.touches.ONE=TOUCH.ROTATE;
 // The host owns two-finger screen-anchor zoom/pan. Do not also pan the
 // OrbitControls camera for that same movement.
 controls.touches.TWO=null;
 listen(surface,'pointerdown',event=>{
  active.set(event.pointerId,event.pointerType||'mouse');
  // OrbitControls normally treats Ctrl/Meta like Shift. The host advertises
  // Shift-only panning, so compensate its built-in modifier inversion using
  // the public mouse mapping, based on this actual event (no sticky key flag).
  if(event.button===0&&event.pointerType!=='touch')
   controls.mouseButtons.LEFT=(event.ctrlKey||event.metaKey)&&!event.shiftKey?MOUSE.PAN:MOUSE.ROTATE;
 },true);
 const end=event=>active.delete(event.pointerId);
 listen(surface,'pointerup',end,true);listen(surface,'pointercancel',end,true);
 const cancel=pointerId=>{
  const pointerType=active.get(pointerId);if(pointerType===undefined)return;
  active.delete(pointerId);
  // Dispatch through the surface so OrbitControls AND host selection/pinch
  // bookkeeping observe the same cancellation. No private controls fields.
  const EventClass=host?.Event||globalThis.Event;
  const event=new EventClass('pointercancel');
  Object.defineProperties(event,{pointerId:{value:pointerId},pointerType:{value:pointerType}});
  surface.dispatchEvent(event);
 };
 const cancelAll=()=>{for(const pointerId of [...active.keys()])cancel(pointerId);};
 listen(surface,'lostpointercapture',event=>cancel(event.pointerId));
 listen(host,'blur',cancelAll);
 listen(doc,'visibilitychange',()=>{if(doc.hidden)cancelAll();});
 return()=>{for(const release of releases)release();active.clear();};
}

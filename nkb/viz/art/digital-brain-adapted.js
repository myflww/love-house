/*
 * Adapted from Digital-Brain, Copyright (c) 2026 Sahil K, MIT.
 * Upstream: https://github.com/SahilK-027/Digital-Brain
 * Commit: 366cf81dad855ea238dec170fcc65579d6d9ba4b
 * Sources: NeuralThreads.class.js (wave splines), ThreadParticles.class.js,
 * Shaders/threads/thread.{vert,frag}.glsl, Shaders/brain/brain.frag.glsl.
 * Changes: fixed real graph endpoints, deterministic phase, batched geometry,
 * bounded samples, procedural texture, real recall-trail visibility/alpha.
 * The upstream random cluster generator and external model/assets are omitted.
 */
import * as THREE from 'three';
// Upstream createSingleThread: perpendicular basis + two sine/cosine waves,
// then CatmullRomCurve3. Envelope pins both ends to actual knowledge nodes.
export function createWaveSpline(start,end,phase,phase2,amplitude,frequency,strand=0){
 const direction=new THREE.Vector3().subVectors(end,start),length=direction.length()||1;direction.normalize();
 const perp=new THREE.Vector3();if(Math.abs(direction.x)<.9)perp.set(0,direction.z,-direction.y).normalize();else perp.set(-direction.z,0,direction.x).normalize();
 const perp2=new THREE.Vector3().crossVectors(direction,perp).normalize(),points=[];
 for(let i=0;i<=12;i++){const t=i/12,envelope=Math.sin(t*Math.PI);const wave1=Math.sin(t*Math.PI*frequency+phase)*amplitude*envelope;const wave2=Math.cos(t*Math.PI*frequency*.7+phase2)*amplitude*.6*envelope;const p=new THREE.Vector3().copy(start).addScaledVector(direction,t*length).addScaledVector(perp,wave1+strand*envelope*.65).addScaledVector(perp2,wave2);points.push(p);}
 const curve=new THREE.CatmullRomCurve3(points);curve.tension=.5;return{curve,perp,perp2};
}
// Actual upstream point shader, adapted only for world scale and visibility.
export const threadVertex=`uniform float uTime;uniform float uSize;uniform float uDpr;attribute float aProgress;attribute float aSpeed;attribute float aRandom;attribute float aSize;attribute float aAlpha;varying float vRandom;varying float vProgress;varying float vAlpha;void main(){vec4 modelPosition=modelMatrix*vec4(position,1.);vec4 viewPosition=viewMatrix*modelPosition;vec4 projectedPosition=projectionMatrix*viewPosition;gl_Position=projectedPosition;float pulse=sin(uTime*2.+aRandom*6.28)*.3+.7;float sizeVariation=aSize*pulse;gl_PointSize=uSize*sizeVariation*uDpr;gl_PointSize*=clamp(1200./-viewPosition.z,.55,2.);gl_PointSize=max(gl_PointSize,1.);vRandom=aRandom;vProgress=aProgress;vAlpha=aAlpha;}`;
export const threadFragment=`uniform float uTime;uniform vec3 uColor1;uniform vec3 uColor2;uniform sampler2D uTexture;uniform float uLight;varying float vRandom;varying float vProgress;varying float vAlpha;void main(){vec4 particleTexture=texture2D(uTexture,gl_PointCoord);float alpha=particleTexture.r;if(alpha<.01){vec2 center=gl_PointCoord-.5;float dist=length(center);if(dist>.5)discard;alpha=1.-smoothstep(0.,.5,dist);alpha=pow(alpha,2.);}float colorMix=vProgress;vec3 color=mix(uColor1,uColor2,colorMix)*3.;color=mix(color,vec3(.08),uLight);float fadeOut=1.-smoothstep(.85,1.,vProgress);float twinkle=sin(uTime*4.+vRandom*20.)*.2+.8;alpha*=twinkle*fadeOut*vAlpha;float monochrome=dot(color,vec3(.2126,.7152,.0722));gl_FragColor=vec4(vec3(monochrome),alpha);#include <colorspace_fragment>}`.replace('#include','\n#include');
// Upstream Brain material functions: specular, Fresnel, ambient occlusion,
// weighted three-axis electric waves and sparkle. Applied to each real neuron.
export const brainSurface=`float dbSpecular(vec3 normal,vec3 viewDir,vec3 lightDir,float shininess){vec3 halfVector=normalize(lightDir+viewDir);float specAngle=max(dot(halfVector,normal),0.);return pow(specAngle,shininess);}float dbFresnel(vec3 normal,vec3 viewDir,float power){return pow(1.-max(dot(normal,viewDir),0.),power);}vec3 digitalBrainSurface(vec3 normal,vec3 viewDir,vec3 worldPosition,vec3 baseColor,float time){vec3 lightDir=normalize(vec3(-.5,.8,1.6));float diffuse=mix(.3,1.,max(dot(normal,lightDir),0.));float ao=mix(.6,1.,smoothstep(0.,.5,dot(normal,viewDir)));vec3 color=baseColor*diffuse*ao;float spec=dbSpecular(normal,viewDir,lightDir,32.)*.7;color+=vec3(1.)*spec*.6;float fresnelValue=dbFresnel(normal,viewDir,2.5);color+=vec3(.70,.63,.81)*fresnelValue*1.2;color+=vec3(1.)*pow(fresnelValue,3.)*.3;float electricEdge=pow(fresnelValue,1.5);float wave1=sin(worldPosition.y*.045+time*1.5)*.5+.5;float wave2=sin(worldPosition.x*.045*1.3-time*1.5*.8)*.5+.5;float wave3=sin(worldPosition.z*.045*.7+time*1.5*1.2)*.5+.5;float electricPulse=pow(wave1*.5+wave2*.3+wave3*.2,2.);float electricHighlight=pow(electricEdge*electricPulse,.8);vec3 electricGlow=vec3(.545,.36,.965)*electricHighlight*.9;electricGlow+=vec3(1.,.9,.8)*pow(electricHighlight,3.)*1.1;return color+electricGlow;}`;

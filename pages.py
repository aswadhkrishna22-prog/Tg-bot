"""Adolf-StreamX presentation layer.

Contains HTML renderers only; route registration and runtime state remain in
server.py and are passed into the renderers explicitly.
"""

import html
from datetime import datetime
from urllib.parse import quote

def render_error_page():
    """Production 404 page using the wet-glass WebGL compositor, with DOM fallback."""
    bot_link = "https://t.me/AdolfFTLbot?start=unavailable"
    return r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#05070d">
<title>Adolf-StreamX | 404</title>
<style id="bgcss">
.pg{width:100%;height:100%;overflow:hidden;color:#eef2ff;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:radial-gradient(circle at 8% 8%,rgba(124,58,237,.28),transparent 35%),radial-gradient(circle at 92% 42%,rgba(6,182,212,.18),transparent 32%),linear-gradient(180deg,#070a14,#05070d)}
.in{width:min(1120px,calc(100% - 28px));margin:0 auto;padding:22px 0}
.h{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}
.br{font-size:22px;font-weight:900}.br span{color:#9b7cff}
.pill{font-style:normal;padding:8px 12px;border:1px solid rgba(110,140,190,.25);border-radius:99px;background:rgba(12,17,30,.8);color:#aeb9cc;font-size:12px;font-weight:700}
.mc{border-radius:24px;border:1px solid rgba(125,145,190,.2);background:#050913;overflow:hidden}
.po{position:relative;aspect-ratio:16/9;background:linear-gradient(135deg,#1d4a29,#0b3a3c 55%,#0a1a14)}
.pl{position:absolute;left:50%;top:50%;width:76px;height:76px;margin:-38px 0 0 -38px;border-radius:50%;background:rgba(5,10,20,.7);border:1px solid rgba(255,255,255,.3);display:grid;place-items:center;font-size:28px}
.ft{padding:20px 22px}
.sk{display:block;height:20px;width:70%;border-radius:8px;background:rgba(148,163,184,.2)}
.sk.b{height:13px;width:34%;margin-top:10px;background:rgba(148,163,184,.13)}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px}
.ab{min-height:58px;border-radius:16px;border:1px solid rgba(125,145,190,.2);background:linear-gradient(180deg,#0d1423,#090f1b);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:15px}
.ic{margin-top:16px;border:1px solid rgba(125,145,190,.18);border-radius:20px;background:rgba(8,12,21,.8);overflow:hidden}
.ih{padding:16px 20px;border-bottom:1px solid rgba(125,145,190,.14);font-weight:900;font-size:13px;color:#c6d0e2}
.ir{display:flex;justify-content:space-between;align-items:center;padding:14px 20px;border-bottom:1px solid rgba(125,145,190,.08);font-size:13px;color:#8995aa}
.ir i{display:block;width:45%;height:12px;border-radius:6px;background:rgba(148,163,184,.16)}
.hero h1{font-size:clamp(32px,6vw,54px);line-height:1.05;margin:26px 0 12px;font-weight:800;letter-spacing:-1.2px}
.hero p{color:#94a0b8;max-width:42ch;font-size:17px;line-height:1.5}
.bt{display:inline-flex;margin:18px 10px 0 0;padding:14px 22px;border-radius:13px;background:linear-gradient(120deg,#8b7cff,#6555df);font-weight:700}
.bt.o{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.14)}
.c3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:26px}
.c3 div{padding:16px;border:1px solid rgba(140,150,255,.2);border-radius:18px;background:#0e1424;font-weight:700}
.c3 small{display:block;color:#94a0b8;font-weight:500;margin-top:6px}
</style>
<style id="pgcss">
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:#05070d;overflow:hidden}
body.nogl #bgpage{filter:blur(2px) brightness(.7)}
body.nogl #glass{display:none!important}
#bgpage{position:fixed;inset:0}
#bgpage.fb{filter:blur(2px) brightness(.7)}
#glass{position:fixed;inset:0;width:100%;height:100%;display:none}
.stage{position:fixed;inset:0;z-index:5;display:grid;place-items:center;padding:20px;pointer-events:none;font-family:"Plus Jakarta Sans",Inter,system-ui,-apple-system,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
.card{pointer-events:auto;width:min(340px,100%);padding:24px 20px 20px;text-align:center;color:#eef1fb;border-radius:24px;border:1px solid rgba(255,255,255,.2);background:linear-gradient(160deg,rgba(255,255,255,.1),rgba(255,255,255,.03) 55%,rgba(0,0,0,.2));-webkit-backdrop-filter:blur(10px) saturate(130%);backdrop-filter:blur(10px) saturate(130%);box-shadow:0 30px 90px rgba(0,0,0,.6),inset 0 1px 0 rgba(255,255,255,.18);animation:pop .55s cubic-bezier(.2,.9,.25,1.12) .35s both}
@keyframes pop{from{opacity:0;transform:translateY(14px) scale(.9)}to{opacity:1;transform:none}}
.warn{width:44px;height:44px;fill:none;stroke:#ff4b55;stroke-width:2.6;stroke-linecap:round;stroke-linejoin:round;filter:drop-shadow(0 0 7px rgba(255,60,70,.9)) drop-shadow(0 0 18px rgba(255,40,60,.55))}
.code{margin:4px 0 0;font-size:clamp(76px,24vw,112px);line-height:1;font-weight:300;letter-spacing:.04em;color:#ff5560;text-shadow:0 0 6px rgba(255,70,80,.95),0 0 26px rgba(255,40,60,.6),0 0 70px rgba(255,30,50,.38)}
.title{margin-top:12px;font-size:12px;font-weight:600;letter-spacing:.3em;color:#e6e9f2}
.rule{display:flex;align-items:center;gap:10px;margin:14px auto 0;max-width:230px;color:rgba(255,255,255,.45);font-size:13px}
.rule i{flex:1;height:1px;background:rgba(255,255,255,.22)}
.msg{margin:14px auto 0;max-width:270px;font-size:13.5px;line-height:1.6;color:#c3c9d8}
.btn{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;min-height:48px;margin-top:18px;border-radius:14px;border:1px solid rgba(255,255,255,.22);background:rgba(10,12,20,.45);color:#eef1fb;font:inherit;font-size:12.5px;font-weight:600;letter-spacing:.16em;text-decoration:none}
.btn svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
body.gl .card{opacity:0;animation:none}
.proto{position:fixed;left:50%;top:10px;transform:translateX(-50%);z-index:20;display:flex;gap:6px;align-items:center;padding:6px 8px;border-radius:99px;background:rgba(8,10,18,.82);border:1px solid rgba(255,255,255,.15);font:600 12px system-ui,sans-serif;color:#aab3c7;white-space:nowrap}
.proto button{font:inherit;color:#fff;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.14);border-radius:99px;padding:6px 12px}
.proto button.on{background:#6555df;border-color:#8b7cff}
</style>
</head>
<body>
<div id="bgpage"></div>
<canvas id="glass" aria-hidden="true"></canvas>
<main class="stage"><section class="card" role="alertdialog" aria-labelledby="et">
<svg class="warn" viewBox="0 0 48 48" aria-hidden="true"><path d="M24 6 3 41h42z"/><path d="M24 18v12M24 35v.5"/></svg>
<h1 class="code">404</h1>
<div id="et" class="title">FILE NOT AVAILABLE</div>
<div class="rule"><i></i><b>&times;</b><i></i></div>
<p class="msg">Sorry, this file is currently unavailable or the link has expired.</p>
<a class="btn" href="__BOT_LINK__"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 11 12 3l9 8M5 10v10h5v-6h4v6h5V10"/></svg>RETURN HOME</a>
<button class="btn ghost" type="button" onclick="location.reload()">RELOAD PAGE</button>
</section></main>
<script id="fs" type="x-shader/x-fragment">
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
uniform sampler2D bg,dm,cd;uniform vec2 R;uniform vec4 CR;uniform float K,POP,RAD;
vec2 cuv(vec2 uv){vec2 c=(CR.xy+CR.zw*.5)/R;float s=.9+.1*POP;vec2 q=uv+vec2(0.,14.*(1.-POP))/R;return c+(q-c)/s;}
float cmask(vec2 cu){vec2 p=cu*R-(CR.xy+CR.zw*.5);vec2 q=abs(p)-CR.zw*.5+RAD;float d=length(max(q,vec2(0.)))+min(max(q.x,q.y),0.)-RAD;return 1.-smoothstep(-1.,1.,d);}
vec3 scene(vec2 uv,float bb,float cb){
  float pa=smoothstep(0.,.5,POP);
  vec2 cu=cuv(uv);
  float mk=cmask(cu)*pa;
  vec3 b=texture2D(bg,uv,bb).rgb;
  b=mix(b,texture2D(bg,uv,bb+2.4).rgb*.92,mk);
  vec4 c=texture2D(cd,cu,cb);
  return b*(1.-c.a*pa)+c.rgb*pa;
}
void main(){
  vec2 uv=gl_FragCoord.xy/R;vec2 px=1./R;
  vec4 m=texture2D(dm,uv);
  vec2 n=vec2(m.r*2.-1.,-(m.g*2.-1.));
  float amp=m.b;
  float pres=smoothstep(.02,.07,amp);
  float w=amp;
  for(int i=0;i<8;i++){float t=float(i)*.7854;w+=texture2D(dm,uv+vec2(cos(t),sin(t))*9.*px).b*.5;}
  float halo=clamp(w*1.4,0.,1.);
  vec3 frost=scene(uv,1.7,halo*2.8);
  vec3 refr=scene(uv-n*amp*K*px,0.,1.5);
  vec3 col=mix(frost,refr*1.12,pres);
  float l=length(n);
  vec3 N=normalize(vec3(n*.85,sqrt(max(0.,1.-l*l))*.9+.12));
  vec3 L=normalize(vec3(-.5,.65,.6));
  float spec=pow(max(dot(N,normalize(L+vec3(0.,0.,1.))),0.),70.);
  float cau=pow(max(dot(N.xy,-L.xy),0.),2.5)*smoothstep(.2,.9,l);
  col*=1.-pres*smoothstep(.55,1.,l)*.42;
  col+=pres*(spec*.9+cau*.16);
  float sh=texture2D(dm,uv+vec2(3.,-4.)*px).b;
  col*=1.-smoothstep(.02,.1,sh)*(1.-pres)*.28;
  col*=.95*(1.-.35*pow(length(uv-.5)*1.1,2.));
  gl_FragColor=vec4(col,1.);
}
</script>
<script>
(function(){
var $=function(i){return document.getElementById(i)};
var bgp=$("bgpage"),cv=$("glass"),cardEl=document.querySelector(".card"),gl=null,prog,texBG,texDM,texCD,U={},mapC=document.createElement("canvas"),mx=mapC.getContext("2d");
var TPL={
watch:'<div class="pg"><div class="in"><div class="h"><b class="br">Adolf-<span>StreamX</span></b><i class="pill">ONLINE</i></div><div class="mc"><div class="po"><div class="pl">&#9654;</div></div><div class="ft"><u class="sk"></u><u class="sk b"></u></div></div><div class="g2"><div class="ab">Download File</div><div class="ab">Copy Share Link</div></div><div class="g2" style="grid-template-columns:1fr"><div class="ab">External Players</div></div><div class="ic"><div class="ih">File Information</div><div class="ir">File Name<i></i></div><div class="ir">File Size<i></i></div><div class="ir">File Owner<i></i></div></div></div></div>'
};
var RC=[1.6,2.4,3.6,5.2,7.5,10.5,14.5],sprites=[],beads=[],movers=[],W,H,D,T=0,running=false,last=0,kind="watch",cardGL=false,tPop=0,CC={x:-999,y:-999,w:0,h:0};
function build(){
  sprites=RC.map(function(r){
    var S=64,c=document.createElement("canvas");c.width=c.height=S;var x=c.getContext("2d"),im=x.createImageData(S,S),amp=Math.round(255*r/RC[RC.length-1]);
    for(var j=0;j<S;j++)for(var i=0;i<S;i++){
      var u=(i+.5-S/2)/(S/2),v=(j+.5-S/2)/(S/2),l=Math.hypot(u,v),k=(j*S+i)*4;
      im.data[k]=128+127*u;im.data[k+1]=128+127*v;im.data[k+2]=amp;im.data[k+3]=l>=1?0:l>.88?255*(1-l)/.12:255;
    }
    x.putImageData(im,0,0);return{c:c,r:r};
  });
}
function spr(r){for(var i=0;i<sprites.length;i++)if(sprites[i].r>=r)return sprites[i];return sprites[sprites.length-1]}
function bead(x,y,r,l,fi,fo,s,b){beads.push({x:x,y:y,r:r,b:b===undefined?T:b,l:l,fi:fi,fo:fo,s:s})}
function al(b){var a=T-b.b;if(a<0)return 0;var v=Math.min(1,a/b.fi);if(b.l-a<b.fo)v=Math.min(v,(b.l-a)/b.fo);return Math.max(0,v)}
function inCard(x,y,p){return x>CC.x-p&&x<CC.x+CC.w+p&&y>CC.y-p&&y<CC.y+CC.h+p}
function sbead(life,fi,b){var x,y,t=0;do{x=Math.random()*W;y=Math.random()*H;t++}while(inCard(x,y,8)&&Math.random()>.1&&t<8);bead(x,y,1.8+Math.pow(Math.random(),2.1)*9.5,life,fi,3,true,b)}
function seed(){beads=[];movers=[];var n=Math.min(700,W*H/1500)|0;for(var i=0;i<n;i++)sbead(25+Math.random()*60,.01,T-Math.random()*20)}
function mover(x,y,r){movers.push({x:x,y:y,r:r,v:0,age:0,hold:.3+Math.random()*1.2,wob:Math.random()*100,sp:.55+Math.random()*.9,stall:0,acc:0,on:false})}
function sim(dt){
  var mt=Math.max(6,Math.min(14,W*H/40000))|0,stat=0,i,j;
  for(i=0;i<beads.length;i++)if(beads[i].s)stat++;
  if(stat<Math.min(700,W*H/1500)&&Math.random()<dt*6)sbead(25+Math.random()*60,2.5);
  if(movers.length<mt&&Math.random()<dt*2)mover(Math.random()*W,Math.random()*H*.7,6+Math.random()*7);
  if(CC.w>0&&movers.length<mt+3&&Math.random()<dt*.3)mover(CC.x+30+Math.random()*(CC.w-60),Math.max(8,CC.y-50-Math.random()*60),6+Math.random()*4);
  for(i=movers.length-1;i>=0;i--){
    var m=movers[i];m.age+=dt;
    if(m.age<m.hold)continue;
    if(m.stall>0){m.stall-=dt;m.v*=Math.pow(.02,dt)}
    else{m.v=Math.min(m.v+m.r*26*dt,m.r*30*m.sp);if(m.v>25&&Math.random()<dt*.6)m.stall=.15+Math.random()*.7}
    var dy=m.v*dt;m.y+=dy;m.x+=Math.sin(m.y*.045+m.wob)*dy*.16;m.r-=dy*.0045;m.acc+=dy;
    if(!m.on&&inCard(m.x,m.y,0)){m.on=true;m.r=Math.min(14,m.r*1.3);m.sp*=1.35}
    var rt=Math.max(1,m.r*.27),st=rt*1.15;
    while(m.acc>=st){m.acc-=st;bead(m.x+(Math.random()-.5)*.8,m.y-m.r*.7,rt*(.85+Math.random()*.3),3.5+Math.random()*2.5,.04,2.6,false)}
    for(j=0;j<beads.length;j++){var b=beads[j];if(b.s&&b.r<m.r*.65&&Math.abs(b.x-m.x)<m.r&&Math.abs(b.y-m.y)<m.r*1.1){b.l=0;m.r+=b.r*.05}}
    if(m.r<2.3){bead(m.x,m.y,m.r,30,.3,3,true);movers.splice(i,1)}
    else if(m.y>H+20)movers.splice(i,1);
  }
  beads=beads.filter(function(b){return T-b.b<b.l});
  if(beads.length>1100)beads.splice(0,beads.length-1100);
}
function paint(){
  var w=mapC.width,h=mapC.height;
  mx.globalAlpha=1;mx.fillStyle="rgb(128,128,0)";mx.fillRect(0,0,w,h);
  for(var i=0;i<beads.length;i++){var b=beads[i],a=al(b);if(a<=0)continue;mx.globalAlpha=a;var s=spr(b.r);mx.drawImage(s.c,(b.x-b.r)*D,(b.y-b.r)*D,2*b.r*D,2*b.r*D)}
  mx.globalAlpha=1;
  for(i=0;i<movers.length;i++){var m=movers[i],s2=spr(m.r);mx.globalAlpha=Math.min(1,m.age/.5);mx.drawImage(s2.c,(m.x-m.r)*D,(m.y-m.r*1.1)*D,2*m.r*D,2.4*m.r*D)}
  var e=cardGL?Math.min(1,Math.max(0,(T-tPop)/.65)):0;e=1-Math.pow(1-e,3);
  gl.uniform1f(U.POP,e);
  gl.activeTexture(gl.TEXTURE1);gl.bindTexture(gl.TEXTURE_2D,texDM);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,true);
  gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,mapC);
  gl.drawArrays(gl.TRIANGLES,0,3);
}
function frame(now){
  var dt=Math.min(.05,(now-last)/1000||.016);last=now;T=now/1000;
  sim(dt);paint();
  if(!document.hidden)requestAnimationFrame(frame);else running=false;
}
function go(){if(!running){running=true;last=performance.now();requestAnimationFrame(frame)}}
function p2(n){var k=1;while(k<n)k<<=1;return k}
function snap(inner,unit,tex){
  return new Promise(function(res,rej){
    var w=Math.round(W),h=Math.round(H);
    var svg='<svg xmlns="http://www.w3.org/2000/svg" width="'+w+'" height="'+h+'"><foreignObject width="100%" height="100%"><style xmlns="http://www.w3.org/1999/xhtml">'+$("bgcss").textContent+$("pgcss").textContent+'</style>'+inner+'</foreignObject></svg>';
    var img=new Image();
    img.onload=function(){try{
      var pw=Math.min(1024,p2(w*D)),ph=Math.min(1024,p2(h*D)),bc=document.createElement("canvas");
      bc.width=pw;bc.height=ph;bc.getContext("2d").drawImage(img,0,0,pw,ph);
      gl.activeTexture(gl.TEXTURE0+unit);gl.bindTexture(gl.TEXTURE_2D,tex);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,true);gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL,unit===2);
      gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,bc);gl.generateMipmap(gl.TEXTURE_2D);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR_MIPMAP_LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL,false);
      res()}catch(e){rej(e)}};
    img.onerror=rej;img.src="data:image/svg+xml;charset=utf-8,"+encodeURIComponent(svg);
  });
}
function bgMarkup(){var cl=bgp.firstElementChild.cloneNode(true);cl.setAttribute("style","width:"+Math.round(W)+"px;height:"+Math.round(H)+"px");return new XMLSerializer().serializeToString(cl)}
function cardMarkup(){var cl=cardEl.cloneNode(true);cl.setAttribute("style","position:absolute;left:"+CC.x+"px;top:"+CC.y+"px;width:"+CC.w+"px;margin:0;animation:none;opacity:1;-webkit-backdrop-filter:none;backdrop-filter:none;font-family:'Plus Jakarta Sans',Inter,system-ui,-apple-system,'Segoe UI',sans-serif");return new XMLSerializer().serializeToString(cl)}
function measure(){
  CC={x:cardEl.offsetLeft,y:cardEl.offsetTop,w:cardEl.offsetWidth,h:cardEl.offsetHeight};
  if(gl)gl.uniform4f(U.CR,CC.x*D,(H-CC.y-CC.h)*D,CC.w*D,CC.h*D);
}
function size(){
  W=innerWidth;H=innerHeight;D=Math.min(window.devicePixelRatio||1,1.25);
  cv.width=mapC.width=Math.round(W*D);cv.height=mapC.height=Math.round(H*D);
  gl.viewport(0,0,cv.width,cv.height);gl.uniform2f(U.R,cv.width,cv.height);
  gl.uniform1f(U.K,2*RC[RC.length-1]*D);gl.uniform1f(U.RAD,24*D);
}
function show(k,full){
  kind="watch";bgp.innerHTML=TPL.watch;
  if(!gl)return;
  var jobs=[snap(bgMarkup(),0,texBG)];
  if(full){measure();jobs.push(snap(cardMarkup(),2,texCD).then(function(){cardGL=true},function(){cardGL=false}))}
  Promise.all(jobs).then(function(){
    bgp.style.visibility="hidden";bgp.className="";cv.style.display="block";
    document.body.classList.toggle("gl",cardGL);
    if(full)tPop=performance.now()/1000+.35;
    go();
  }).catch(function(){bgp.style.visibility="visible";bgp.className="fb";cv.style.display="none"});
}
function init(){
  gl=cv.getContext("webgl",{antialias:false,alpha:false});if(!gl)return;
  function sh(t,s){var o=gl.createShader(t);gl.shaderSource(o,s);gl.compileShader(o);return o}
  prog=gl.createProgram();gl.attachShader(prog,sh(gl.VERTEX_SHADER,"attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}"));
  gl.attachShader(prog,sh(gl.FRAGMENT_SHADER,$("fs").textContent));gl.linkProgram(prog);
  if(!gl.getProgramParameter(prog,gl.LINK_STATUS)){gl=null;return}
  gl.useProgram(prog);gl.bindBuffer(gl.ARRAY_BUFFER,gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,3,-1,-1,3]),gl.STATIC_DRAW);
  var l=gl.getAttribLocation(prog,"p");gl.enableVertexAttribArray(l);gl.vertexAttribPointer(l,2,gl.FLOAT,false,0,0);
  ["R","K","CR","POP","RAD"].forEach(function(n){U[n]=gl.getUniformLocation(prog,n)});
  texBG=gl.createTexture();texDM=gl.createTexture();texCD=gl.createTexture();
  gl.activeTexture(gl.TEXTURE1);gl.bindTexture(gl.TEXTURE_2D,texDM);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
  gl.uniform1i(gl.getUniformLocation(prog,"bg"),0);gl.uniform1i(gl.getUniformLocation(prog,"dm"),1);gl.uniform1i(gl.getUniformLocation(prog,"cd"),2);
  gl.uniform1f(U.POP,0);
}
function fallback(){
  document.body.classList.add("nogl");
  bgp.style.visibility="visible";
  cv.style.display="none";
  cardEl.style.opacity="1";
  cardEl.style.animation="pop .55s cubic-bezier(.2,.9,.25,1.12) .35s both";
}
build();init();
if(gl){
  try{size();measure();seed();show("watch",true)}catch(e){fallback()}
}else{fallback()}
var rt;addEventListener("resize",function(){if(!gl)return;clearTimeout(rt);rt=setTimeout(function(){try{size();measure();seed();show(kind,true)}catch(e){fallback()}},250)});
document.addEventListener("visibilitychange",function(){if(!document.hidden&&gl&&cv.style.display==="block")go()});
})();
</script>
</body>
</html>
'''.replace("__BOT_LINK__", bot_link)

def render_home_page(stady_css=""):
    """Landing page: professional dark violet theme, mobile-first."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#070a14">
<meta name="description" content="Adolf-StreamX: send a file to the Telegram bot, get a share page, and watch it in your browser or on your TV.">
<title>Adolf-StreamX | Telegram file streaming</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;700;800&display=swap" rel="stylesheet">
<style>
:root{--bg:#070a14;--panel:#0e1424;--line:rgba(140,150,255,.15);--tx:#eef1fb;--mu:#94a0b8;--v:#8b7cff;--v2:#6555df;--c:#4cc9ff}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--tx);font:500 16px/1.6 "Plus Jakarta Sans",Inter,system-ui,-apple-system,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased;overflow-x:hidden}
a{color:inherit;text-decoration:none}
a:focus-visible,button:focus-visible{outline:2px solid var(--c);outline-offset:3px}
.page{position:relative}
.glow{position:absolute;inset:0 0 auto 0;height:680px;pointer-events:none;background:radial-gradient(620px 340px at 12% 8%,rgba(139,124,255,.30),transparent 70%),radial-gradient(520px 320px at 92% 28%,rgba(76,201,255,.15),transparent 70%)}
.w{position:relative;width:min(1080px,calc(100% - 32px));margin:0 auto}
.nav{position:sticky;top:0;z-index:20;background:rgba(7,10,20,.72);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
.nav .w{display:flex;align-items:center;justify-content:space-between;height:64px}
.brand{display:flex;align-items:center;gap:10px;font-weight:800;font-size:18px;letter-spacing:-.3px}
.mark{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,var(--v),var(--v2));display:grid;place-items:center}
.mark svg{width:16px;height:16px;fill:#fff}
.links{display:flex;align-items:center;gap:22px;color:var(--mu);font-size:14px;font-weight:700}
.links a:hover{color:var(--tx)}
.links .hide{display:none}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:9px;padding:13px 20px;border-radius:12px;border:1px solid var(--line);background:rgba(255,255,255,.04);font-weight:700;font-size:15px;color:var(--tx);transition:transform .15s,border-color .15s}
.btn:hover{border-color:rgba(160,170,255,.45);transform:translateY(-1px)}
.btn svg{width:18px;height:18px;fill:currentColor}
.btn.pri{border:0;background:linear-gradient(120deg,var(--v),var(--v2));box-shadow:0 10px 30px rgba(101,85,223,.42)}
.btn.sm{padding:9px 15px;font-size:14px}
.hero{display:grid;gap:44px;padding:56px 0 48px}
h1{margin:0;font-size:clamp(36px,7vw,60px);line-height:1.04;letter-spacing:-1.6px;font-weight:800}
.lead{margin:20px 0 0;max-width:46ch;color:var(--mu);font-size:18px}
.cta{display:flex;flex-wrap:wrap;gap:12px;margin-top:28px}
.facts{display:flex;flex-wrap:wrap;gap:8px;margin:26px 0 0;padding:0;list-style:none}
.facts li{padding:6px 12px;border:1px solid var(--line);border-radius:999px;color:var(--mu);font-size:13px;font-weight:700}
.dev{border:1px solid var(--line);border-radius:22px;background:var(--panel);overflow:hidden;box-shadow:0 40px 90px rgba(0,0,0,.55),0 0 80px rgba(139,124,255,.14)}
.dev-top{display:flex;align-items:center;gap:7px;padding:12px 16px;border-bottom:1px solid var(--line);color:var(--mu);font-size:12px;font-weight:700}
.dev-top i{width:9px;height:9px;border-radius:50%;background:#2a3350}
.dev-top span{margin-left:8px}
.poster{position:relative;aspect-ratio:16/9;background:linear-gradient(135deg,#1c2150,#0d3b4c 70%,#0a2230)}
.play{position:absolute;left:50%;top:50%;width:64px;height:64px;margin:-32px 0 0 -32px;border-radius:50%;background:rgba(7,10,20,.6);border:1px solid rgba(255,255,255,.3);display:grid;place-items:center;backdrop-filter:blur(8px)}
.play svg{width:24px;height:24px;fill:#fff;margin-left:3px}
.seek{position:absolute;left:16px;right:16px;bottom:14px;display:flex;align-items:center;gap:10px;font-size:11px;color:#cfd8ee;font-weight:700}
.bar{flex:1;height:5px;border-radius:5px;background:rgba(255,255,255,.18);overflow:hidden}
.bar i{display:block;height:100%;width:62%;border-radius:5px;background:linear-gradient(90deg,var(--v),var(--c));animation:prog 7s ease-in-out infinite alternate}
@keyframes prog{from{width:6%}to{width:62%}}
.dev-body{padding:16px 18px 18px}
.dev-body b{display:block;font-size:16px}
.dev-body small{color:var(--mu);font-size:13px}
.dev-act{display:flex;gap:8px;margin-top:14px}
.dev-act span{flex:1;text-align:center;padding:10px 6px;border:1px solid var(--line);border-radius:10px;font-size:12px;font-weight:700;background:rgba(255,255,255,.03)}
.sec{padding:56px 0 8px}
h2{margin:0;font-size:clamp(26px,4.5vw,36px);letter-spacing:-.8px;line-height:1.15;font-weight:800;max-width:20ch}
.steps{list-style:none;margin:32px 0 0;padding:0;display:grid;gap:26px;counter-reset:s}
.steps li{position:relative;padding-left:56px}
.steps li::before{counter-increment:s;content:counter(s);position:absolute;left:0;top:0;width:38px;height:38px;border-radius:50%;display:grid;place-items:center;font-weight:800;background:var(--panel);border:1px solid var(--v);color:var(--tx)}
.steps li::after{content:"";position:absolute;left:19px;top:44px;bottom:-22px;width:1px;background:var(--line)}
.steps li:last-child::after{display:none}
.steps h3,.card h3{margin:0 0 4px;font-size:18px}
.steps p,.card p{margin:0;color:var(--mu);font-size:15px}
.bento{display:grid;gap:14px;margin-top:32px}
.card{padding:24px;border:1px solid var(--line);border-radius:20px;background:var(--panel)}
.card.big{background:linear-gradient(150deg,#161c3d,var(--panel) 60%)}
.pair{display:flex;gap:8px;margin:16px 0 14px}
.pair span{flex:1;max-width:46px;padding:10px 0;text-align:center;border:1px solid var(--line);border-radius:10px;background:var(--bg);font-size:22px;font-weight:800;letter-spacing:0}
.link{display:inline-block;margin-top:14px;color:var(--c);font-weight:700;font-size:14px}
.link:hover{text-decoration:underline}
.big .tags{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}
.tags span{padding:6px 12px;border-radius:8px;background:rgba(139,124,255,.14);color:#cfc9ff;font-size:13px;font-weight:700}
.foot{margin-top:72px;border-top:1px solid var(--line);padding:26px 0 36px;color:var(--mu);font-size:14px}
.foot .w{display:flex;flex-wrap:wrap;gap:12px 28px;justify-content:space-between}
.foot a:hover{color:var(--tx)}
@media(min-width:760px){
.links .hide{display:inline}
.hero{grid-template-columns:1.05fr .95fr;align-items:center;gap:56px;padding:84px 0 64px}
.steps{grid-template-columns:repeat(3,1fr);gap:28px}
.steps li{padding:56px 0 0}
.steps li::after{left:50px;right:-28px;top:19px;bottom:auto;width:auto;height:1px}
.bento{grid-template-columns:repeat(6,1fr)}
.big{grid-column:span 4}
.card{grid-column:span 2}
}
@media(prefers-reduced-motion:reduce){.bar i{animation:none}.btn{transition:none}}
</style>
</head>
<body>
<div class="page"><div class="glow"></div>
<header class="nav"><div class="w">
  <a class="brand" href="/"><span class="mark"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg></span>Adolf-StreamX</a>
  <nav class="links"><a class="hide" href="#how">How it works</a><a class="hide" href="/pair">Pair TV</a><a class="hide" href="/privacy">Privacy</a>
  <a class="btn pri sm" href="https://t.me/AdolfFTLbot" target="_blank" rel="noopener noreferrer">Open bot</a></nav>
</div></header>

<main class="w">
<section class="hero">
  <div>
    <h1>Send a file on Telegram. Watch it on any screen.</h1>
    <p class="lead">Forward a video to the Adolf-StreamX bot and get a share page that streams in your browser or on your TV. No download, no compression.</p>
    <div class="cta">
      <a class="btn pri" href="https://t.me/AdolfFTLbot" target="_blank" rel="noopener noreferrer"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21.9 4.3 18.7 19.5c-.2 1-.9 1.3-1.7.8l-4.8-3.6-2.3 2.3c-.3.3-.5.5-1 .5l.4-4.9 8.9-8c.4-.3-.1-.5-.6-.2L6.6 13.3 1.9 11.8c-1-.3-1-1 .2-1.5L20.4 3.3c.9-.3 1.6.2 1.5 1z"/></svg>Open Telegram bot</a>
      <a class="btn" href="/pair">Pair your TV</a>
    </div>
    <ul class="facts"><li>Original quality</li><li>Links expire in 12 hours</li><li>Works with VLC</li></ul>
  </div>
  <div class="dev" aria-hidden="true">
    <div class="dev-top"><i></i><i></i><i></i><span>Adolf-StreamX share page</span></div>
    <div class="poster"><div class="play"><svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg></div>
      <div class="seek">12:41<div class="bar"><i></i></div>48:20</div></div>
    <div class="dev-body"><b>weekend-trip.mp4</b><small>1.4 GB &middot; link expires in 12 hours</small>
      <div class="dev-act"><span>Download</span><span>Copy link</span><span>Players</span></div></div>
  </div>
</section>

<section class="sec" id="how">
  <h2>From Telegram to your screen in three steps</h2>
  <ol class="steps">
    <li><h3>Send</h3><p>Send a video or file to the bot on Telegram.</p></li>
    <li><h3>Open</h3><p>The bot replies with a share link. Open it on your phone or computer.</p></li>
    <li><h3>Watch</h3><p>Play in the browser, or pair your TV and keep watching there.</p></li>
  </ol>
</section>

<section class="sec">
  <h2>Made for watching, not just sharing</h2>
  <div class="bento">
    <article class="card big"><h3>Stream, pause, jump anywhere</h3><p>Playback starts while the file is still loading, and you can seek to any point. Prefer your own player? VLC and other external players work too.</p>
      <div class="tags"><span>Seek</span><span>Resume</span><span>Fullscreen</span><span>External players</span></div></article>
    <article class="card"><h3>Pair your TV</h3><p>Type a short code on your TV instead of a long link.</p>
      <div class="pair" aria-hidden="true"><span>4</span><span>8</span><span>2</span><span>9</span></div>
      <a class="link" href="/pair">Get a pairing code</a></article>
    <article class="card"><h3>Large files</h3><p>Share big videos straight from Telegram without compressing them first.</p></article>
    <article class="card"><h3>Links that expire</h3><p>Share links stop working after 12 hours, so files don't stay online forever.</p></article>
    <article class="card big"><h3>Privacy first</h3><p>The bot only processes what it needs to provide its features. Read the full policy for details.</p><a class="link" href="/privacy">Read the privacy policy</a></article>
  </div>
</section>
</main>

<footer class="foot"><div class="w">
  <div>&copy; 2026 Adolf-StreamX</div>
  <a href="/privacy">Privacy Policy</a>
  <div>Made with &#10084;&#65039; by <a href="https://www.instagram.com/2aswadhh_._kr" target="_blank" rel="noopener noreferrer">@aswadh_kr</a></div>
</div></footer>
</div>
</body>
</html>"""


async def render_watch_page(token, row, public_url, stady_css, get_owner_display_func, create_share_token_func, get_stream_mime_func, error_page_func):
    filename = row["filename"]
    safe_name = html.escape(filename)
    encoded_filename = quote(filename, safe="")

    stream_url = (
        f"{public_url}/{token}/"
        f"{encoded_filename}?action=stream"
    )

    file_size = int(row["size"])
    mime = get_stream_mime_func(filename, row["mime"])

    if file_size >= 1024**3:
        size_str = f"{file_size / 1024**3:.2f} GB"
    elif file_size >= 1024**2:
        size_str = f"{file_size / 1024**2:.2f} MB"
    else:
        size_str = f"{file_size / 1024:.2f} KB"

    created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    owner_display = html.escape(await get_owner_display_func(row))

    try:
        share_token = row.get("share_token") if hasattr(row, "get") else None
        if not share_token:
            share_token = create_share_token_func(token)
        share_url = f"{public_url}/share/{share_token}"
    except Exception:
        share_url = stream_url

    # The poster is intentionally clean: forest image + play button only.
    # The real <video> element is created after the user taps play, so native
    # browser controls provide reliable pause, seek, volume and fullscreen.
    forest_image = (
        "https://images.unsplash.com/photo-1448375240586-882707db888b"
        "?auto=format&fit=crop&w=1600&q=90"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#05070d">
<title>Adolf-StreamX | {safe_name}</title>
<style>
{stady_css}

/* ==========================================================
   PREMIUM WATCH PLAYER — clean poster, native video controls
   ========================================================== */
.watch-page {{
    width: min(1120px, calc(100% - 28px));
    margin: 0 auto;
    padding: 28px 0 48px;
}}

.watch-header {{
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:16px;
    margin-bottom:22px;
}}

.watch-brand {{
    font-size:22px;
    font-weight:900;
    letter-spacing:-.4px;
}}
.watch-brand span {{
    background:linear-gradient(90deg,#9b5cff,#4cc9ff);
    -webkit-background-clip:text;
    background-clip:text;
    color:transparent;
}}
.watch-status {{
    display:inline-flex;
    align-items:center;
    gap:8px;
    padding:8px 12px;
    border:1px solid rgba(110,140,190,.18);
    border-radius:999px;
    background:rgba(12,17,30,.72);
    color:#aeb9cc;
    font-size:12px;
    font-weight:700;
}}
.watch-status i {{
    width:7px;
    height:7px;
    border-radius:50%;
    background:#5ee7a5;
    box-shadow:0 0 12px rgba(94,231,165,.7);
}}

.media-card {{
    overflow:hidden;
    border-radius:24px;
    border:1px solid rgba(125,145,190,.18);
    background:#050913;
    box-shadow:0 24px 80px rgba(0,0,0,.42);
}}

.poster {{
    position:relative;
    aspect-ratio:16/9;
    min-height:240px;
    overflow:hidden;
    background:#07100b;
}}
.poster::before {{
    content:"";
    position:absolute;
    inset:0;
    background-image:url("{forest_image}");
    background-size:cover;
    background-position:center;
    transform:scale(1.015);
}}
.poster::after {{
    content:"";
    position:absolute;
    inset:0;
    background:linear-gradient(180deg,rgba(2,5,10,.06),rgba(2,5,10,.38));
}}

.poster.playing::before,
.poster.playing::after {{
    display:none;
}}


.poster-play {{
    position:absolute;
    z-index:2;
    left:50%;
    top:50%;
    transform:translate(-50%,-50%);
    width:92px;
    height:92px;
    border:1px solid rgba(255,255,255,.45);
    border-radius:50%;
    background:rgba(5,10,20,.82);
    color:white;
    display:grid;
    place-items:center;
    font-size:34px;
    padding:0 0 0 5px;
    cursor:pointer;
    box-shadow:0 12px 42px rgba(0,0,0,.45), 0 0 0 7px rgba(120,95,255,.10);
    backdrop-filter:blur(14px);
    transition:transform .18s ease, box-shadow .18s ease, background .18s ease;
}}
.poster-play:hover {{
    transform:translate(-50%,-50%) scale(1.06);
    background:rgba(10,16,30,.92);
    box-shadow:0 16px 48px rgba(0,0,0,.5), 0 0 0 9px rgba(120,95,255,.13);
}}
.poster-play:active {{
    transform:translate(-50%,-50%) scale(.97);
}}

.video-shell {{
    position:relative;
    width:100%;
    aspect-ratio:16/9;
    background:#000;
}}
.video-shell video {{
    display:block;
    width:100%;
    height:100%;
    object-fit:contain;
    background:#000;
}}

.video-error {{
    display:none;
    position:absolute;
    left:16px;
    right:16px;
    bottom:70px;
    z-index:3;
    padding:12px 14px;
    border:1px solid rgba(255,120,120,.25);
    border-radius:12px;
    background:rgba(20,5,8,.86);
    color:#ffd4d4;
    text-align:center;
    font-size:13px;
    backdrop-filter:blur(12px);
}}

.file-title-card {{
    padding:20px 22px;
    border-top:1px solid rgba(125,145,190,.12);
}}
.file-title {{
    margin:0;
    color:#f4f7ff;
    font-size:18px;
    font-weight:800;
    line-height:1.4;
    overflow-wrap:anywhere;
}}
.file-sub {{
    margin-top:6px;
    color:#8995aa;
    font-size:13px;
}}

.action-grid {{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:12px;
    margin-top:16px;
}}
.action-btn {{
    min-height:58px;
    border-radius:16px;
    border:1px solid rgba(125,145,190,.16);
    background:linear-gradient(180deg,#0d1423,#090f1b);
    color:#edf2fb;
    text-decoration:none;
    display:flex;
    align-items:center;
    justify-content:center;
    gap:9px;
    font-size:15px;
    font-weight:800;
    cursor:pointer;
    transition:transform .16s ease,border-color .16s ease,background .16s ease;
}}
.action-btn:hover {{
    transform:translateY(-2px);
    border-color:rgba(126,95,255,.55);
    background:linear-gradient(180deg,#11192b,#0b1220);
}}
.action-btn.primary {{
    background:linear-gradient(135deg,#7139d8,#2e74d8);
    border-color:rgba(155,120,255,.48);
}}
.footer {{
    margin-top: 28px;
    padding: 18px 0 8px;
    text-align: center;
    font-size: 13px;
    color: rgba(255, 255, 255, 0.45);
}}

.footer .heart {{
    color: #ff4d6d;
    font-size: 15px;
    margin: 0 3px;
}}

.instagram-link {{
    margin-left: 4px;
    text-decoration: none;
    font-weight: 600;

    background: linear-gradient(
        45deg,
        #feda75,
        #fa7e1e,
        #d62976,
        #962fbf,
        #4f5bd5
    );

    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;

    transition: opacity 0.2s ease;
}}

.instagram-link:hover {{
    opacity: 0.8;
}}

.instagram-icon {{
    font-size: 16px;
    margin-right: 3px;
    -webkit-text-fill-color: #d62976;
}}
.info-card {{
    margin-top:18px;
    overflow:hidden;
    border:1px solid rgba(125,145,190,.14);
    border-radius:20px;
    background:rgba(8,12,21,.78);
}}
.info-head {{
    padding:18px 20px;
    border-bottom:1px solid rgba(125,145,190,.12);
    font-size:13px;
    font-weight:900;
    letter-spacing:.8px;
    text-transform:uppercase;
    color:#c6d0e2;
}}
.info-row {{
    display:grid;
    grid-template-columns:150px 1fr;
    gap:16px;
    padding:15px 20px;
    border-bottom:1px solid rgba(125,145,190,.08);
}}
.info-row:last-child {{ border-bottom:0; }}
.info-label {{ color:#727f95; font-size:13px; }}
.info-value {{ color:#dce4f1; font-size:14px; overflow-wrap:anywhere; }}

@media (max-width:650px) {{
    .watch-page {{ width:calc(100% - 20px); padding-top:16px; }}
    .watch-header {{ margin-bottom:14px; }}
    .watch-brand {{ font-size:19px; }}
    .watch-status {{ font-size:10px; padding:7px 9px; }}
    .media-card {{ border-radius:18px; }}
    .poster {{ min-height:205px; }}
    .poster-play {{ width:72px; height:72px; font-size:27px; }}
    .file-title-card {{ padding:16px; }}
    .action-grid {{ grid-template-columns:1fr; }}
    .info-row {{ grid-template-columns:1fr; gap:5px; padding:13px 16px; }}
}}

/* ==========================================================
   AMBIENT CINEMA MODE: playing video glows across the page
   ========================================================== */
:root {{ --amb-blur: 40px; }}
#amb {{ position: fixed; left: -6%; top: -6%; width: 112%; height: 112%; z-index: 0; pointer-events: none; opacity: 0; transition: opacity 1s ease; filter: blur(var(--amb-blur)) saturate(1.5) brightness(.62); }}
.watch-page {{ position: relative; z-index: 1; }}
body.cinema {{ background: #020308; }}
body.cinema #amb {{ opacity: 1; }}
body.cinema .media-card {{ background: rgba(4,8,16,.5); border-color: rgba(255,255,255,.14); box-shadow: 0 30px 120px rgba(0,0,0,.65); }}
body.cinema .info-card, body.cinema .action-btn, body.cinema .players button, body.cinema .status, body.cinema .watch-status {{ background: rgba(8,12,22,.38); border-color: rgba(255,255,255,.13); -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px); }}
body.cinema .watch-header, body.cinema .footer, body.cinema .info-card {{ opacity: .6; transition: opacity .4s; }}
body.cinema .watch-header:hover, body.cinema .footer:hover, body.cinema .info-card:hover {{ opacity: 1; }}
@media (prefers-reduced-motion: reduce) {{ #amb {{ transition: none; }} }}
</style>
</head>
<body>
<canvas id="amb" width="64" height="36" aria-hidden="true"></canvas>
<main class="watch-page">

<header class="watch-header">
    <div class="watch-brand">Adolf-<span>StreamX</span></div>
    <div class="watch-status"><i></i> ONLINE</div>
</header>

<section class="media-card">
    <div class="poster" id="playerArea" aria-label="Video preview">
        <button class="poster-play" type="button" onclick="startVideo()" aria-label="Play video">▶</button>
    </div>
    <div class="file-title-card">
        <p class="file-title">{safe_name}</p>
        <div class="file-sub">{size_str} · {html.escape(mime)}</div>
    </div>
</section>

<div class="action-grid">
    <a class="action-btn primary" href="{stream_url}&action=download" download>⇩ Download File</a>
    <button class="action-btn" type="button" onclick="copyShareLink()">⛓ Copy Share Link</button>
</div>

<div class="action-grid" style="margin-top:12px;">
    <button class="action-btn" type="button" onclick="togglePlayers()">🎬 External Players</button>
</div>

<div class="players" id="players" style="display:none;">
    <button type="button" onclick="openPlayer('mx')">MX Player</button>
    <button type="button" onclick="openPlayer('vlc')">VLC Mobile</button>
    <button type="button" onclick="openPlayer('playit')">PlayIt</button>
    <button type="button" onclick="openPlayer('kmplayer')">KMPlayer</button>
    <button type="button" onclick="openPlayer('nplayer')">nPlayer</button>
</div>

<section class="info-card">
    <div class="info-head">▣ File Information</div>
    <div class="info-row"><div class="info-label">File Name</div><div class="info-value">{safe_name}</div></div>
    <div class="info-row"><div class="info-label">File Size</div><div class="info-value">{size_str}</div></div>
    <div class="info-row"><div class="info-label">File Owner</div><div class="info-value">{owner_display}</div></div>
    <div class="info-row"><div class="info-label">Created Time</div><div class="info-value">{created}</div></div>
</section>

<div class="status" id="status" style="margin-top:18px;">Adolf-StreamX • READY</div>


<footer class="footer">
    <div>
        Made with <span class="heart">❤️</span> by
        <a href="https://www.instagram.com/2aswadhh_._kr"
           class="instagram-link"
           target="_blank"
           rel="noopener noreferrer"
           aria-label="Instagram @aswadh_kr">
            <svg class="instagram-icon" width="17" height="17" viewBox="0 0 24 24"
                 aria-label="Instagram" role="img" fill="none"
                 xmlns="http://www.w3.org/2000/svg">
                <defs>
                    <linearGradient id="instagram-gradient"
                                    x1="4" y1="20" x2="20" y2="4"
                                    gradientUnits="userSpaceOnUse">
                        <stop stop-color="#FFDC80"/>
                        <stop offset="0.25" stop-color="#FCAD45"/>
                        <stop offset="0.5" stop-color="#F77737"/>
                        <stop offset="0.75" stop-color="#E1306C"/>
                        <stop offset="1" stop-color="#833AB4"/>
                    </linearGradient>
                </defs>

                <rect x="3.25" y="3.25" width="17.5" height="17.5"
                      rx="5" stroke="url(#instagram-gradient)" stroke-width="2"/>

                <circle cx="12" cy="12" r="4.15"
                        stroke="url(#instagram-gradient)" stroke-width="2"/>

                <circle cx="17.35" cy="6.65" r="1"
                        fill="url(#instagram-gradient)"/>
            </svg>

            <span>@aswadh_kr</span>
        </a>
    </div>

  <br><div class="privacy-footer-link">
        <a href="/privacy">© Privacy &amp; Policy of Adolf-StreamX</a>
    </div>
</footer>

</main>

<script>
const STREAM_URL = {stream_url!r};
const SHARE_URL = {share_url!r};

function setStatus(text) {{
    const el = document.getElementById("status");
    if (el) el.textContent = text;
}}

async function copyShareLink() {{
    try {{
        await navigator.clipboard.writeText(SHARE_URL);
        setStatus("Adolf-StreamX • SHARE LINK COPIED ✓");
    }} catch (_) {{
        window.prompt("Copy this share link:", SHARE_URL);
    }}
}}

const ambCanvas = document.getElementById("amb");
const ambCtx = ambCanvas ? ambCanvas.getContext("2d") : null;
let ambTimer = null;
let ambVideo = null;

function startAmbient(video) {{
    stopAmbient();
    ambVideo = video;
    if (!ambCtx) return;
    ambTimer = setInterval(() => {{
        try {{ ambCtx.drawImage(video, 0, 0, 64, 36); }} catch (_) {{}}
    }}, 70);
}}

function stopAmbient() {{
    if (ambTimer) clearInterval(ambTimer);
    ambTimer = null;
}}

document.addEventListener("visibilitychange", () => {{
    if (document.hidden) stopAmbient();
    else if (ambVideo && !ambVideo.paused && !ambVideo.ended) startAmbient(ambVideo);
}});

function startVideo() {{
    const area = document.getElementById("playerArea");
    if (!area || area.querySelector("video")) return;

    area.classList.add("playing");
    area.innerHTML = `
        <div class="video-shell">
            <video id="mainVideo" controls playsinline preload="metadata" autoplay src="${{STREAM_URL}}"></video>
            <div id="videoError" class="video-error">
                Browser could not decode this video's codec/container.
            </div>
        </div>`;

    const video = document.getElementById("mainVideo");
    const errorBox = document.getElementById("videoError");

    video.addEventListener("loadstart", () => setStatus("Adolf-StreamX • LOADING…"));
    video.addEventListener("waiting", () => setStatus("Adolf-StreamX • BUFFERING…"));
    video.addEventListener("canplay", () => setStatus("Adolf-StreamX • READY ▶"));
    video.addEventListener("play", () => setStatus("Adolf-StreamX • PLAYING ▶"));
    video.addEventListener("pause", () => setStatus("Adolf-StreamX • PAUSED"));
    video.addEventListener("ended", () => setStatus("Adolf-StreamX • ENDED"));
    video.addEventListener("play", () => {{ document.body.classList.add("cinema"); startAmbient(video); }});
    video.addEventListener("pause", stopAmbient);
    video.addEventListener("ended", () => {{ stopAmbient(); setTimeout(() => document.body.classList.remove("cinema"), 1200); }});
    video.addEventListener("error", () => {{
        errorBox.style.display = "block";
        setStatus("Adolf-StreamX • BROWSER CODEC ERROR");
    }});

    // This call is made from the user's button click, so mobile browsers are
    // allowed to start playback with audio in normal circumstances.
    video.play().catch(() => {{
        setStatus("Adolf-StreamX • TAP PLAY TO START");
    }});
}}

function togglePlayers() {{
    const players = document.getElementById("players");
    if (!players) return;
    players.style.display = players.style.display === "grid" ? "none" : "grid";
}}

function openPlayer(player) {{
    const noScheme = STREAM_URL.replace("https://", "").replace("http://", "");
    const scheme = STREAM_URL.startsWith("https://") ? "https" : "http";
    let intent = "";

    if (player === "mx") intent = "intent://" + noScheme + "#Intent;scheme=" + scheme + ";package=com.mxtech.videoplayer.ad;type=video/*;end;";
    else if (player === "vlc") intent = "intent://" + noScheme + "#Intent;scheme=" + scheme + ";package=org.videolan.vlc;type=video/*;end;";
    else if (player === "playit") intent = "intent://" + noScheme + "#Intent;scheme=" + scheme + ";package=com.playit.videoplayer;type=video/*;end;";
    else if (player === "kmplayer") intent = "intent://" + noScheme + "#Intent;scheme=" + scheme + ";package=com.kmplayer;type=video/*;end;";
    else if (player === "nplayer") intent = "intent://" + noScheme + "#Intent;scheme=" + scheme + ";type=video/*;end;";

    if (intent) location.href = intent;
}}
</script>
</body>
</html>"""



def render_receive_page(
    share_token,
    row,
    public_url,
    stady_css,
    get_stream_mime_func,
    owner_display=None,
    remote_session_id=None,
):
    """Render the QR/TV receiver page with an embedded browser player.

    The receiver keeps the TV inside the Adolf-StreamX UI: scanning the QR
    does not send the TV to a bare stream URL. The same forest/glass visual
    language is used as the main watch page, and the Browser Player is the
    primary in-page player.
    """
    filename = row["filename"]
    safe_name = html.escape(filename)
    encoded_filename = quote(filename, safe="")
    stream_url = (
        f"{public_url}/{row['token']}/"
        f"{encoded_filename}?action=stream"
    )
    mime = get_stream_mime_func(filename, row.get("mime") if hasattr(row, "get") else None)

    file_size = int(row["size"])
    if file_size >= 1024**3:
        size_str = f"{file_size / 1024**3:.2f} GB"
    elif file_size >= 1024**2:
        size_str = f"{file_size / 1024**2:.2f} MB"
    else:
        size_str = f"{file_size / 1024:.2f} KB"

    owner_text = "Adolf-StreamX"
    if owner_display:
        owner_text = html.escape(str(owner_display))

    forest_image = (
        "https://images.unsplash.com/photo-1448375240586-882707db888b"
        "?auto=format&fit=crop&w=1600&q=90"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,viewport-fit=cover">
<meta name="theme-color" content="#05070d">
<title>Adolf-StreamX | TV Player</title>
<style>
{stady_css}

.tv-page{{width:min(1120px,calc(100% - 28px));margin:0 auto;padding:28px 0 48px}}
.tv-header{{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:22px}}
.tv-brand{{font-size:22px;font-weight:900;letter-spacing:-.4px}}
.tv-brand span{{background:linear-gradient(90deg,#9b5cff,#4cc9ff);-webkit-background-clip:text;background-clip:text;color:transparent}}
.tv-status{{display:inline-flex;align-items:center;gap:8px;padding:8px 12px;border:1px solid rgba(110,140,190,.18);border-radius:999px;background:rgba(12,17,30,.72);color:#aeb9cc;font-size:12px;font-weight:700}}
.tv-status i{{width:7px;height:7px;border-radius:50%;background:#5ee7a5;box-shadow:0 0 12px rgba(94,231,165,.7)}}
.tv-card{{overflow:hidden;border-radius:24px;border:1px solid rgba(125,145,190,.18);background:#050913;box-shadow:0 24px 80px rgba(0,0,0,.42)}}
.tv-player{{position:relative;width:100%;aspect-ratio:16/9;background:#07100b;overflow:hidden}}
.tv-poster{{position:absolute;inset:0;background-image:url("{forest_image}");background-size:cover;background-position:center;transition:opacity .25s ease}}
.tv-poster::after{{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(2,5,10,.08),rgba(2,5,10,.50))}}
.tv-video{{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#000;z-index:2}}
.tv-video[hidden]{{display:none}}
.tv-start{{position:absolute;z-index:3;left:50%;top:50%;transform:translate(-50%,-50%);width:92px;height:92px;border:1px solid rgba(255,255,255,.45);border-radius:50%;background:rgba(5,10,20,.82);color:#fff;display:grid;place-items:center;font-size:34px;padding-left:5px;cursor:pointer;box-shadow:0 12px 42px rgba(0,0,0,.45),0 0 0 7px rgba(120,95,255,.10);backdrop-filter:blur(14px);transition:transform .18s ease,background .18s ease}}
.tv-start:hover{{transform:translate(-50%,-50%) scale(1.06);background:rgba(10,16,30,.92)}}
.tv-start[hidden]{{display:none}}
.tv-meta{{padding:20px 22px;border-top:1px solid rgba(125,145,190,.12)}}
.tv-title{{margin:0;color:#f4f7ff;font-size:18px;font-weight:800;line-height:1.4;overflow-wrap:anywhere}}
.tv-sub{{margin-top:6px;color:#8995aa;font-size:13px}}
.tv-actions{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px}}
.tv-btn{{min-height:58px;border-radius:16px;border:1px solid rgba(125,145,190,.16);background:linear-gradient(180deg,#0d1423,#090f1b);color:#edf2fb;text-decoration:none;display:flex;align-items:center;justify-content:center;gap:9px;font-size:15px;font-weight:800;cursor:pointer}}
.tv-btn.primary{{background:linear-gradient(135deg,#7139d8,#2e74d8);border-color:rgba(155,120,255,.48)}}
.tv-info{{margin-top:18px;overflow:hidden;border:1px solid rgba(125,145,190,.14);border-radius:20px;background:rgba(8,12,21,.78)}}
.tv-info-head{{padding:18px 20px;border-bottom:1px solid rgba(125,145,190,.12);font-size:13px;font-weight:900;letter-spacing:.8px;text-transform:uppercase;color:#c6d0e2}}
.tv-info-row{{display:grid;grid-template-columns:150px 1fr;gap:16px;padding:15px 20px;border-bottom:1px solid rgba(125,145,190,.08)}}
.tv-info-row:last-child{{border-bottom:0}}
.tv-label{{color:#727f95;font-size:13px}}
.tv-value{{color:#dce4f1;font-size:14px;overflow-wrap:anywhere}}
.tv-note{{margin-top:18px;padding:15px 18px;border:1px solid rgba(125,145,190,.12);border-radius:16px;background:rgba(8,12,21,.72);color:#aeb9cc;text-align:center;font-size:13px;line-height:1.6}}
.tv-error{{display:none;position:absolute;z-index:4;left:16px;right:16px;bottom:70px;padding:12px 14px;border:1px solid rgba(255,120,120,.25);border-radius:12px;background:rgba(20,5,8,.88);color:#ffd4d4;text-align:center;font-size:13px;backdrop-filter:blur(12px)}}
@media(max-width:650px){{.tv-page{{width:calc(100% - 20px);padding-top:16px}}.tv-header{{margin-bottom:14px}}.tv-brand{{font-size:19px}}.tv-status{{font-size:10px;padding:7px 9px}}.tv-card{{border-radius:18px}}.tv-start{{width:72px;height:72px;font-size:27px}}.tv-meta{{padding:16px}}.tv-actions{{grid-template-columns:1fr}}.tv-info-row{{grid-template-columns:1fr;gap:5px;padding:13px 16px}}}}

/* AMBIENT CINEMA MODE: playing video glows across the TV page */
:root {{ --amb-blur: 40px; }}
#amb {{ position: fixed; left: -6%; top: -6%; width: 112%; height: 112%; z-index: 0; pointer-events: none; opacity: 0; transition: opacity 1s ease; filter: blur(var(--amb-blur)) saturate(1.5) brightness(.62); }}
.tv-page {{ position: relative; z-index: 1; }}
body.cinema {{ background: #020308; }}
body.cinema #amb {{ opacity: 1; }}
body.cinema .tv-card {{ background: rgba(4,8,16,.5); border-color: rgba(255,255,255,.14); box-shadow: 0 30px 120px rgba(0,0,0,.65); }}
body.cinema .tv-info, body.cinema .tv-btn, body.cinema .tv-note, body.cinema .tv-status {{ background: rgba(8,12,22,.38); border-color: rgba(255,255,255,.13); -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px); }}
body.cinema .tv-btn.primary {{ background: linear-gradient(135deg,rgba(113,57,216,.55),rgba(46,116,216,.55)); }}
body.cinema .tv-header, body.cinema .footer, body.cinema .tv-info {{ opacity: .6; transition: opacity .4s; }}
body.cinema .tv-header:hover, body.cinema .footer:hover, body.cinema .tv-info:hover {{ opacity: 1; }}
@media (prefers-reduced-motion: reduce) {{ #amb {{ transition: none; }} }}
</style>
</head>
<body>
<canvas id="amb" width="64" height="36" aria-hidden="true"></canvas>
<main class="tv-page">
<header class="tv-header">
    <div class="tv-brand">Adolf-<span>StreamX</span></div>
    <div class="tv-status"><i></i> TV CONNECTED</div>
</header>

<section class="tv-card">
    <div class="tv-player" id="tvPlayer">
        <div class="tv-poster" id="tvPoster"></div>
        <button class="tv-start" id="tvStart" type="button" onclick="startTvVideo()" aria-label="Play video">▶</button>
        <video class="tv-video" id="tvVideo" controls playsinline preload="metadata" hidden></video>
        <div class="tv-error" id="tvError">Browser could not decode this video's codec/container.</div>
    </div>
    <div class="tv-meta">
        <p class="tv-title">{safe_name}</p>
        <div class="tv-sub">{size_str} · {html.escape(mime)} · Browser Player</div>
    </div>
</section>

<div class="tv-actions">
    <button class="tv-btn primary" type="button" onclick="startTvVideo()">▶ BROWSER PLAYER</button>
    <button class="tv-btn" type="button" onclick="copyStreamLink()">⛓ COPY STREAM LINK</button>
</div>

{("<div class=\"tv-note\" style=\"margin-top:12px\"><a class=\"tv-btn\" href=\"/remote/" + html.escape(str(remote_session_id)) + "\">📱 OPEN PHONE REMOTE</a></div>") if remote_session_id else ""}

<section class="tv-info">
    <div class="tv-info-head">▣ File Information</div>
    <div class="tv-info-row"><div class="tv-label">File Name</div><div class="tv-value">{safe_name}</div></div>
    <div class="tv-info-row"><div class="tv-label">File Size</div><div class="tv-value">{size_str}</div></div>
    <div class="tv-info-row"><div class="tv-label">File Owner</div><div class="tv-value">{owner_text}</div></div>
</section>

<div class="tv-note" id="tvStatus">📺 QR connection ready · Tap <b>Browser Player</b> to play on this page.</div>
</main>
<footer class="footer">
<div>Made with <span class="heart">❤️</span> by</div>  <a href="https://www.instagram.com/2aswadhh_._kr"
class="instagram-link"
target="_blank"
rel="noopener noreferrer"
aria-label="Instagram @aswadh_kr">
<svg class="instagram-icon" width="17" height="17" viewBox="0 0 24 24"
aria-label="Instagram" role="img" fill="none"
xmlns="http://www.w3.org/2000/svg">
<defs>
<linearGradient id="instagram-gradient"
x1="4" y1="20" x2="20" y2="4"
gradientUnits="userSpaceOnUse">
<stop stop-color="#FFDC80"/>
<stop offset="0.25" stop-color="#FCAD45"/>
<stop offset="0.5" stop-color="#F77737"/>
<stop offset="0.75" stop-color="#E1306C"/>
<stop offset="1" stop-color="#833AB4"/>
</linearGradient>
</defs>

<rect x="3.25" y="3.25" width="17.5" height="17.5"
          rx="5" stroke="url(#instagram-gradient)" stroke-width="2"/>

    <circle cx="12" cy="12" r="4.15"
            stroke="url(#instagram-gradient)" stroke-width="2"/>

    <circle cx="17.35" cy="6.65" r="1"
            fill="url(#instagram-gradient)"/>
</svg>

<span>@aswadh_kr</span>

</div>  </footer>
<script>
const STREAM_URL = {stream_url!r};
const tvVideo = document.getElementById("tvVideo");
const tvPoster = document.getElementById("tvPoster");
const tvStart = document.getElementById("tvStart");
const tvError = document.getElementById("tvError");
const tvStatus = document.getElementById("tvStatus");
const REMOTE_SESSION_ID = {remote_session_id!r};
const REMOTE_WS_URL = (() => {{
    if (!REMOTE_SESSION_ID) return "";
    const scheme = location.protocol === "https:" ? "wss:" : "ws:";
    return scheme + "//" + location.host + "/ws/tv/" + encodeURIComponent(REMOTE_SESSION_ID);
}})();
let remoteSocket = null;

function connectRemote() {{
    if (!REMOTE_WS_URL || remoteSocket) return;
    try {{
        remoteSocket = new WebSocket(REMOTE_WS_URL);
        remoteSocket.onopen = () => setTvStatus("📺 TV remote connected · Browser Player ready");
        remoteSocket.onclose = () => {{ remoteSocket = null; }};
        remoteSocket.onerror = () => {{ remoteSocket = null; }};
        remoteSocket.onmessage = (event) => {{
            try {{ handleRemoteCommand(JSON.parse(event.data)); }} catch (_) {{}}
        }};
    }} catch (_) {{ remoteSocket = null; }}
}}

function handleRemoteCommand(payload) {{
    if (!payload || !payload.command) return;
    const command = payload.command;
    if (command === "play") startTvVideo();
    else if (command === "pause") tvVideo.pause();
    else if (command === "toggle") {{ if (tvVideo.paused) startTvVideo(); else tvVideo.pause(); }}
    else if (command === "seek_forward") tvVideo.currentTime = Math.min((tvVideo.duration || Infinity), tvVideo.currentTime + (Number(payload.seconds) || 10));
    else if (command === "seek_backward") tvVideo.currentTime = Math.max(0, tvVideo.currentTime - (Number(payload.seconds) || 10));
    else if (command === "seek") tvVideo.currentTime = Math.max(0, Math.min(tvVideo.duration || Infinity, Number(payload.seconds) || 0));
    else if (command === "volume_up") tvVideo.volume = Math.min(1, tvVideo.volume + 0.1);
    else if (command === "volume_down") tvVideo.volume = Math.max(0, tvVideo.volume - 0.1);
    else if (command === "set_volume") tvVideo.volume = Math.max(0, Math.min(1, (Number(payload.value) || 0) / 100));
    else if (command === "mute") tvVideo.muted = !tvVideo.muted;
    else if (command === "fullscreen") {{ if (tvVideo.requestFullscreen) tvVideo.requestFullscreen().catch(() => {{}}); }}
    else if (command === "exit_fullscreen") {{ if (document.exitFullscreen) document.exitFullscreen().catch(() => {{}}); }}
    else if (command === "stop") {{ tvVideo.pause(); tvVideo.currentTime = 0; }}
}}

if (REMOTE_WS_URL) window.addEventListener("load", connectRemote);

const ambCanvas = document.getElementById("amb");
const ambCtx = ambCanvas ? ambCanvas.getContext("2d") : null;
let ambTimer = null;

function startAmbient() {{
    stopAmbient();
    if (!ambCtx) return;
    ambTimer = setInterval(() => {{
        try {{ ambCtx.drawImage(tvVideo, 0, 0, 64, 36); }} catch (_) {{}}
    }}, 80);
}}

function stopAmbient() {{
    if (ambTimer) clearInterval(ambTimer);
    ambTimer = null;
}}

document.addEventListener("visibilitychange", () => {{
    if (document.hidden) stopAmbient();
    else if (!tvVideo.paused && !tvVideo.ended) startAmbient();
}});

function setTvStatus(text) {{
    if (tvStatus) tvStatus.textContent = text;
}}

function startTvVideo() {{
    if (!tvVideo) return;

    tvPoster.style.opacity = "0";
    tvStart.hidden = true;
    tvVideo.hidden = false;

    if (!tvVideo.src) tvVideo.src = STREAM_URL;

    tvVideo.play().then(() => {{
        setTvStatus("▶ Playing on Adolf-StreamX Browser Player");
    }}).catch(() => {{
        setTvStatus("▶ Player ready · tap the play control to start");
    }});
}}

function copyStreamLink() {{
    navigator.clipboard.writeText(STREAM_URL).then(() => {{
        setTvStatus("✅ Stream link copied");
    }}).catch(() => {{
        window.prompt("Copy this stream link:", STREAM_URL);
    }});
}}

tvVideo.addEventListener("loadstart", () => setTvStatus("⏳ Loading stream…"));
tvVideo.addEventListener("waiting", () => setTvStatus("⏳ Buffering…"));
tvVideo.addEventListener("canplay", () => setTvStatus("✓ Stream ready"));
tvVideo.addEventListener("play", () => setTvStatus("▶ Playing on Adolf-StreamX Browser Player"));
tvVideo.addEventListener("pause", () => setTvStatus("⏸ Paused"));
tvVideo.addEventListener("ended", () => setTvStatus("✓ Playback finished"));
tvVideo.addEventListener("play", () => {{ document.body.classList.add("cinema"); startAmbient(); }});
tvVideo.addEventListener("pause", stopAmbient);
tvVideo.addEventListener("ended", () => {{ stopAmbient(); setTimeout(() => document.body.classList.remove("cinema"), 1200); }});
tvVideo.addEventListener("error", () => {{
    tvError.style.display = "block";
    setTvStatus("⚠ Browser codec/container not supported");
}});
</script>
</body>
</html>"""

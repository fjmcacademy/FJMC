const $=id=>document.getElementById(id), letters=["A","B","C","D"];let key={},responses={},lastResult=null;const count=()=>Number($("questionCount").value);
function makeGrid(id,values,changed){const root=$(id);root.innerHTML="";for(let i=1;i<=count();i++){const box=document.createElement("div");box.className="answer-item";const title=document.createElement("strong");title.textContent="Question "+i;const s=document.createElement("select");s.setAttribute("aria-label","Question "+i);let o=document.createElement("option");o.value="";o.textContent="— Blank —";s.append(o);letters.forEach(x=>{o=document.createElement("option");o.value=x;o.textContent=x;s.append(o)});s.value=values[i]||"";s.onchange=()=>changed(i,s.value);box.append(title,s);root.append(box)}}
function renderKey(){makeGrid("keyGrid",key,(i,v)=>{key[i]=v;save()})}function renderResponses(){makeGrid("responseGrid",responses,(i,v)=>responses[i]=v)}
function save(){try{localStorage.setItem("fjmc_omr_settings",JSON.stringify({testName:$("testName").value,count:count(),correctMarks:$("correctMarks").value,negativeMarks:$("negativeMarks").value,key}))}catch(e){}}
function load(){try{const d=JSON.parse(localStorage.getItem("fjmc_omr_settings")||"null");if(d){$("testName").value=d.testName||$("testName").value;$("questionCount").value=String(d.count||100);$("correctMarks").value=d.correctMarks??2;$("negativeMarks").value=d.negativeMarks??.5;key=d.key||{}}}catch(e){}}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function renderSheet(){let h=`<div class="paper-head"><h2>FJMC ACADEMY</h2><p>MATHEMATICS · TEST SERIES</p><b>${esc($("testName").value)}</b><p>Fill one bubble per question using a dark pen.</p></div><div class="paper-info"><div>Student name: <span class="name-line">&nbsp;</span></div><div>Date: ______________</div></div><b style="font-size:11px">ROLL NUMBER (fill one bubble per column)</b><div class="roll-digits">`;for(let c=0;c<8;c++){h+=`<div class="digit-col"><b>${c+1}</b>`;for(let d=0;d<=9;d++)h+=`<span class="bubble">${d}</span>`;h+="</div>"}h+='</div><b style="font-size:11px">ANSWER BUBBLES</b><div class="omr-questions">';for(let i=1;i<=count();i++)h+=`<div class="omr-q"><span class="qnum">${i}.</span><div class="bubbles">${letters.map(l=>`<span class="answer-bubble">${l}</span>`).join("")}</div></div>`;h+='</div><div class="paper-foot">FJMC Academy · Smart OMR · Keep all page corners visible when scanning</div>';$("printableSheet").innerHTML=h}
function tab(name){document.querySelectorAll(".tab").forEach(b=>b.classList.toggle("active",b.dataset.tab===name));document.querySelectorAll(".panel").forEach(p=>p.classList.toggle("hidden",p.id!=="tab-"+name));if(name==="sheet")renderSheet();if(name==="evaluate")renderResponses()}
document.querySelectorAll(".tab").forEach(b=>b.onclick=()=>tab(b.dataset.tab));
$("questionCount").onchange=()=>{responses={};renderKey();renderResponses();renderSheet();save()};["testName","correctMarks","negativeMarks"].forEach(id=>$(id).onchange=()=>{save();renderSheet()});
$("saveSettings").onclick=()=>{save();renderSheet();alert("Settings saved in this browser.")};$("fillDemo").onclick=()=>{key={};for(let i=1;i<=count();i++)key[i]=letters[(i-1)%4];renderKey();save()};
$("printSheet").onclick=()=>{renderSheet();window.print()};
$("evaluateBtn").onclick=()=>{const cm=Number($("correctMarks").value),nm=Number($("negativeMarks").value);if(cm<0||nm<0||!Number.isFinite(cm)||!Number.isFinite(nm)){alert("Marks must be zero or positive.");return}let correct=0,wrong=0,blank=0,unkeyed=0,score=0;for(let i=1;i<=count();i++){if(!key[i]){unkeyed++;continue}if(!responses[i]){blank++;continue}if(responses[i]===key[i]){correct++;score+=cm}else{wrong++;score-=nm}}const max=Object.values(key).filter(Boolean).length*cm;lastResult={test:$("testName").value,name:$("studentName").value,roll:$("rollNumber").value,correct,wrong,blank,unkeyed,score,max,percentage:max?score/max*100:0};const r=lastResult;$("result").innerHTML=`<h3>Result summary</h3><div class="score">${r.score.toFixed(2)} / ${r.max.toFixed(2)} marks</div><p><b>${esc(r.name||"Student not named")}</b> · Roll: ${esc(r.roll||"—")}</p><div class="stats"><div class="stat"><b>${r.correct}</b>Correct</div><div class="stat"><b>${r.wrong}</b>Wrong</div><div class="stat"><b>${r.blank}</b>Blank</div><div class="stat"><b>${r.percentage.toFixed(2)}%</b>Percentage</div></div><p class="muted">Questions without key: ${r.unkeyed}</p>`;$("result").classList.remove("hidden")};
$("clearResponses").onclick=()=>{responses={};renderResponses();$("result").classList.add("hidden");lastResult=null};
$("downloadCsv").onclick=()=>{if(!lastResult){alert("Calculate the result first.");return}const r=lastResult,rows=[["Test","Student Name","Roll Number","Correct","Wrong","Blank","Score","Maximum Marks","Percentage"],[r.test,r.name,r.roll,r.correct,r.wrong,r.blank,r.score.toFixed(2),r.max.toFixed(2),r.percentage.toFixed(2)]],csv=rows.map(row=>row.map(v=>`"${String(v??"").replace(/"/g,'""')}"`).join(",")).join("\r\n"),url=URL.createObjectURL(new Blob(["\ufeff"+csv],{type:"text/csv;charset=utf-8"})),a=document.createElement("a");a.href=url;a.download="fjmc-omr-result.csv";a.click();URL.revokeObjectURL(url)};
$("printResult").onclick=()=>{if(!lastResult){alert("Calculate result first.");return}window.print()};
function previewSelectedImage(input){
  const f=input.files && input.files[0];
  if(!f)return;
  if(!f.type.startsWith("image/")){alert("Please choose an image file (JPG, PNG, or WebP).");input.value="";return;}
  const url=URL.createObjectURL(f);
  $("photoPreview").src=url;
  $("photoPreview").classList.remove("hidden");
  $("photoPreview").dataset.objectUrl=url;
}
$("omrPhoto").addEventListener("change",e=>previewSelectedImage(e.target));
$("omrCamera").addEventListener("change",e=>previewSelectedImage(e.target));
$("year").textContent=new Date().getFullYear();load();renderKey();renderResponses();renderSheet();

// Experimental browser-side OMR reader. It detects circular answer bubbles and
// ranks their interior darkness. It works best with a straight, full-page photo
// of a sheet printed by this website. Always review the responses before scoring.
let selectedImageFile=null;
const statusEl=()=>$("readStatus");
function setReadStatus(msg){if(statusEl())statusEl().textContent=msg;}
function loadCv(){return new Promise((resolve,reject)=>{if(window.cv&&window.cv.Mat){resolve(window.cv);return;}let tries=0;const t=setInterval(()=>{tries++;if(window.cv&&window.cv.Mat){clearInterval(t);resolve(window.cv);}else if(tries>100){clearInterval(t);reject(new Error('OpenCV could not load. Check internet connection and reload the page.'));}},100);});}
function detectBubbleContours(cv, src){
 const gray=new cv.Mat(), blur=new cv.Mat(), bin=new cv.Mat(), contours=new cv.MatVector(), hierarchy=new cv.Mat();
 cv.cvtColor(src,gray,cv.COLOR_RGBA2GRAY); cv.GaussianBlur(gray,blur,new cv.Size(5,5),0);
 cv.threshold(blur,bin,0,255,cv.THRESH_BINARY_INV+cv.THRESH_OTSU); cv.findContours(bin,contours,hierarchy,cv.RETR_LIST,cv.CHAIN_APPROX_SIMPLE);
 const found=[];
 for(let i=0;i<contours.size();i++){
  const c=contours.get(i), area=cv.contourArea(c); if(area<22||area>1800){c.delete();continue;}
  const peri=cv.arcLength(c,true); if(peri<=0){c.delete();continue;} const circ=4*Math.PI*area/(peri*peri);
  const r=cv.boundingRect(c); const ratio=r.width/r.height;
  if(circ>0.62&&ratio>0.72&&ratio<1.35&&r.width>=5&&r.width<=55){
   const cx=r.x+r.width/2,cy=r.y+r.height/2;
   // Interior darkness, excluding the printed outline.
   let dark=0,total=0;const rad=Math.max(2,Math.floor(Math.min(r.width,r.height)*0.22));
   for(let yy=Math.max(0,Math.floor(cy)-rad);yy<Math.min(gray.rows,Math.floor(cy)+rad+1);yy++)for(let xx=Math.max(0,Math.floor(cx)-rad);xx<Math.min(gray.cols,Math.floor(cx)+rad+1);xx++){total++;if(gray.ucharPtr(yy,xx)[0]<100)dark++;}
   found.push({x:cx,y:cy,w:r.width,h:r.height,fill:total?dark/total:0});
  }
  c.delete();
 }
 gray.delete();blur.delete();bin.delete();contours.delete();hierarchy.delete();
 // Merge nested/duplicate contours around the same printed bubble.
 found.sort((a,b)=>a.y-b.y||a.x-b.x);const unique=[];
 for(const b of found){const old=unique.find(u=>Math.hypot(u.x-b.x,u.y-b.y)<Math.max(5,Math.min(b.w,b.h)*0.35));if(!old)unique.push(b);else if(b.fill>old.fill)Object.assign(old,b);}
 return unique;
}
function groupRows(bubbles){
 const sorted=[...bubbles].sort((a,b)=>a.y-b.y),rows=[];
 for(const b of sorted){let row=rows.find(r=>Math.abs(r.y-b.y)<Math.max(7,b.h*0.7));if(!row){row={y:b.y,items:[]};rows.push(row);}row.items.push(b);row.y=row.items.reduce((s,x)=>s+x.y,0)/row.items.length;}
 return rows.map(r=>r.items.sort((a,b)=>a.x-b.x)).sort((a,b)=>a[0].y-b[0].y);
}
async function autoReadOMR(){
 if(!selectedImageFile){setReadStatus('First choose or take an OMR photo.');return;}
 const btn=$("autoReadBtn");btn.disabled=true;setReadStatus('Analyzing image… keep this page open.');
 try{
  const cv=await loadCv();const img=new Image();img.src=URL.createObjectURL(selectedImageFile);await new Promise((res,rej)=>{img.onload=res;img.onerror=rej;});
  const canvas=document.createElement('canvas');const scale=Math.min(1,1800/Math.max(img.naturalWidth,img.naturalHeight));canvas.width=Math.round(img.naturalWidth*scale);canvas.height=Math.round(img.naturalHeight*scale);const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(img,0,0,canvas.width,canvas.height);
  const src=cv.imread(canvas);const bubbles=detectBubbleContours(cv,src);src.delete();URL.revokeObjectURL(img.src);
  const rows=groupRows(bubbles);const answerRows=rows.filter(r=>r.length>=4&&r.length<=7);
  // Pick rows that contain four evenly spaced answer bubbles; ignore roll-number columns.
  const valid=answerRows.filter(r=>{const q=r.slice(-4);const gaps=q.slice(1).map((x,i)=>x.x-q[i].x);return gaps.length===3&&gaps.every(g=>g>4)&&Math.max(...gaps)/Math.min(...gaps)<3.5;});
  if(valid.length<count()){setReadStatus(`Detected ${valid.length}/${count()} answer rows (${bubbles.length} circular marks). Could not read reliably. Use a straight, well-lit photo of the website's newly printed sheet; correct any answers manually.`);return;}
  responses={};let uncertain=0;
  valid.slice(0,count()).forEach((r,i)=>{const opts=r.slice(-4).sort((a,b)=>a.x-b.x);const vals=opts.map(o=>o.fill);const order=vals.map((v,j)=>({v,j})).sort((a,b)=>b.v-a.v);if(order[0].v<0.28||(order.length>1&&order[0].v-order[1].v<0.07)){uncertain++;return;}responses[i+1]=letters[order[0].j];});
  renderResponses();tab('evaluate');setReadStatus(`Auto-read finished: ${Object.keys(responses).length}/${count()} answers detected; ${uncertain} uncertain/blank. Please check every answer before calculating marks.`);
 }catch(e){setReadStatus('Auto-read failed: '+(e.message||'unknown error')+'. Check internet and try a clear, straight image.');}
 finally{btn.disabled=false;}
}
const originalPreview=previewSelectedImage;
previewSelectedImage=function(input){originalPreview(input);selectedImageFile=input.files&&input.files[0]||null;if(selectedImageFile)setReadStatus('Image loaded. Tap “Auto-read bubbles” to try reading the answers.');};
$("autoReadBtn").addEventListener('click',autoReadOMR);
$("clearPhotoBtn").addEventListener('click',()=>{$("omrPhoto").value='';$("omrCamera").value='';$("photoPreview").src='';$("photoPreview").classList.add('hidden');selectedImageFile=null;setReadStatus('Photo removed.');});

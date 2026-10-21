const $=id=>document.getElementById(id);
let selectedFile=null, cameraStream=null, cameraBlob=null, latestResults=[];
function cleanKey(s){return (s||"").toUpperCase().replace(/[^ABCD]/g,"")}
function updateCount(){const k=cleanKey($("key").value);$("keyCount").textContent=`${k.length} answers entered · expected ${$("questions").value}`;}
$("key").addEventListener("input",updateCount);$("questions").addEventListener("change",updateCount);
$("fillDemo").onclick=()=>{$("key").value="ABCD".repeat(Math.ceil(Number($("questions").value)/4)).slice(0,Number($("questions").value));updateCount();};
$("makePaper").onclick=async()=>{
 const n=Number($("questions").value), key=cleanKey($("key").value);
 if(key.length!==n){msg("paperMsg",`Answer key has ${key.length} answers; enter exactly ${n}.`,true);return;}
 try{const r=await fetch("/api/template",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({title:$("title").value,questions:n})});
 if(!r.ok)throw new Error((await r.json()).detail||"Could not create PDF");
 downloadBlob(await r.blob(),"fjmc-omr-template.pdf");msg("paperMsg","Paper settings checked. Blank OMR PDF downloaded. Keep the same answer key for scanning.",false);
 }catch(e){msg("paperMsg",e.message,true);}
};
$("file").addEventListener("change",e=>{selectedFile=e.target.files[0]||null;cameraBlob=null;$("fileName").textContent=selectedFile?selectedFile.name:"No sheet selected";$("fileHint").textContent=selectedFile?`${(selectedFile.size/1024/1024).toFixed(2)} MB · ready to analyze`:"Upload a filled sheet to begin";msg("scanMsg","",false);});
$("cameraBtn").onclick=async()=>{
 try{cameraStream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:"environment"}},audio:false});$("video").srcObject=cameraStream;$("video").hidden=false;$("cameraActions").hidden=false;msg("scanMsg","Camera ready. Keep the entire OMR sheet flat and inside the frame.",false);}
 catch(e){msg("scanMsg","Camera could not open. Allow camera permission and use HTTPS, or upload a photo instead.",true);}
};
$("capture").onclick=()=>{const v=$("video"),c=$("canvas");if(!v.videoWidth){msg("scanMsg","Camera is not ready yet.",true);return;}c.width=v.videoWidth;c.height=v.videoHeight;c.getContext("2d").drawImage(v,0,0);c.toBlob(b=>{cameraBlob=b;selectedFile=null;$("fileName").textContent="Camera capture.jpg";$("fileHint").textContent="Photo captured · ready to analyze";stopCamera();},"image/jpeg",.92);};
function stopCamera(){if(cameraStream)cameraStream.getTracks().forEach(t=>t.stop());cameraStream=null;$("video").hidden=true;$("cameraActions").hidden=true;}
$("stopCamera").onclick=stopCamera;
$("runScan").onclick=async()=>{
 const key=cleanKey($("key").value), n=Number($("questions").value);
 if(key.length!==n){msg("scanMsg",`Enter exactly ${n} answer-key letters before scanning.`,true);return;}
 const file=cameraBlob?new File([cameraBlob],"camera-capture.jpg",{type:"image/jpeg"}):selectedFile;
 if(!file){msg("scanMsg","Please upload a photo/PDF or capture a photo with the camera.",true);return;}
 const fd=new FormData();fd.append("file",file);fd.append("answer_key",key);fd.append("marks",$("marks").value||1);fd.append("negative",$("negative").value||0);
 $("runScan").disabled=true;$("runScan").textContent="Analyzing…";msg("scanMsg","Reading bubbles and calculating marks. Please wait.",false);
 try{const r=await fetch("/api/scan",{method:"POST",body:fd});const data=await r.json();if(!r.ok)throw new Error(data.detail||"Scan failed");latestResults=data.results||[];renderResults(latestResults);msg("scanMsg",`Processed ${latestResults.length} page(s). Review flagged/blank answers before using the marks.`,false);$("results").scrollIntoView({behavior:"smooth"});}
 catch(e){msg("scanMsg",e.message,true);}finally{$("runScan").disabled=false;$("runScan").textContent="Analyze & calculate marks";}
};
function renderResults(results){
 const area=$("resultArea");if(!results.length){area.innerHTML="No results returned.";return;}
 area.innerHTML=results.map((r,idx)=>`<div class="resulttop"><div class="resultmetric"><small>Obtained marks · page ${r.page}</small><strong>${r.marks}</strong></div><div class="resultmetric"><small>Correct</small><strong>${r.correct}</strong></div><div class="resultmetric"><small>Wrong</small><strong>${r.wrong}</strong></div><div class="resultmetric"><small>Blank / multiple</small><strong>${r.blank} / ${r.multiple}</strong></div></div><p style="margin-bottom:12px">${esc(r.filename)} · Maximum ${r.maximum} marks ${r.review_required?"· <b style='color:#b7791f'>Review recommended</b>":""}</p><div style="overflow:auto;max-height:430px"><table class="resulttable"><thead><tr><th>Q.</th><th>Detected</th><th>Answer key</th><th>Status</th></tr></thead><tbody>${r.answers.map(a=>`<tr><td>${a.question}</td><td><b>${a.detected}</b></td><td>${a.key}</td><td class="status ${a.status.split(" ")[0]}">${a.status}</td></tr>`).join("")}</tbody></table></div>`).join("")+`<div class="result-actions"><button class="btn secondary" id="exportCsv">Export CSV</button></div>`;
 $("exportCsv").onclick=async()=>{const r=await fetch("/api/export",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({results:latestResults})});downloadBlob(await r.blob(),"fjmc-omr-results.csv");};
}
function msg(id,text,error){$(id).textContent=text;$(id).className="message"+(error?" error":"");}
function downloadBlob(blob,name){const url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1500);}
function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
updateCount();
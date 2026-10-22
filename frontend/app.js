const $=id=>document.getElementById(id);
let selectedFiles=[], cameraStream=null, cameraBlob=null, latestResults=[];
function cleanKey(s){return (s||"").toUpperCase().replace(/[^ABCD]/g,"")}
function updateCount(){const k=cleanKey($("key").value);$("keyCount").textContent=`${k.length} answers entered · expected ${$("questions").value}`;}
$("key").addEventListener("input",updateCount);$("questions").addEventListener("change",updateCount);
$("fillDemo").onclick=()=>{$("key").value="ABCD".repeat(Math.ceil(Number($("questions").value)/4)).slice(0,Number($("questions").value));updateCount();};
$("makePaper").onclick=async()=>{
 const n=Number($("questions").value), key=cleanKey($("key").value);
 if(key.length!==n){msg("paperMsg",`Answer key has ${key.length} answers; enter exactly ${n}.`,true);return;}
 try{const r=await fetch("/api/template",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({title:$("title").value,questions:n})});
 if(!r.ok)throw new Error((await r.json()).detail||"Could not create PDF");
 downloadBlob(await r.blob(),"fjmc-omr-template-8-digit-roll.pdf");msg("paperMsg","OMR template downloaded. Fill exactly one bubble in each of the 8 roll-number columns and print at 100% scale.",false);
 }catch(e){msg("paperMsg",e.message,true);}
};
$("file").addEventListener("change",e=>{selectedFiles=Array.from(e.target.files||[]);cameraBlob=null;$("fileName").textContent=selectedFiles.length?`${selectedFiles.length} file(s) selected` : "No sheet selected";const total=selectedFiles.reduce((s,f)=>s+f.size,0);$("fileHint").textContent=selectedFiles.length?`${(total/1024/1024).toFixed(2)} MB total · each PDF page/image is treated as one sheet` : "Upload images or a multi-page PDF to begin";msg("scanMsg","",false);});
$("cameraBtn").onclick=async()=>{
 try{cameraStream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:"environment"}},audio:false});$("video").srcObject=cameraStream;$("video").hidden=false;$("cameraActions").hidden=false;msg("scanMsg","Camera ready. Keep the entire OMR sheet flat and inside the frame.",false);}
 catch(e){msg("scanMsg","Camera could not open. Allow camera permission and use HTTPS, or upload a photo instead.",true);}
};
$("capture").onclick=()=>{const v=$("video"),c=$("canvas");if(!v.videoWidth){msg("scanMsg","Camera is not ready yet.",true);return;}c.width=v.videoWidth;c.height=v.videoHeight;c.getContext("2d").drawImage(v,0,0);c.toBlob(b=>{cameraBlob=b;selectedFiles=[];$("fileName").textContent="Camera capture.jpg";$("fileHint").textContent="Photo captured · ready to analyze";stopCamera();},"image/jpeg",.92);};
function stopCamera(){if(cameraStream)cameraStream.getTracks().forEach(t=>t.stop());cameraStream=null;$("video").hidden=true;$("cameraActions").hidden=true;}
$("stopCamera").onclick=stopCamera;
$("runScan").onclick=async()=>{
 const key=cleanKey($("key").value), n=Number($("questions").value);
 if(key.length!==n){msg("scanMsg",`Enter exactly ${n} answer-key letters before scanning.`,true);return;}
 const files=cameraBlob?[new File([cameraBlob],"camera-capture.jpg",{type:"image/jpeg"})]:selectedFiles;
 if(!files.length){msg("scanMsg","Please select one or more images/PDFs or capture a photo with the camera.",true);return;}
 const fd=new FormData();for(const f of files)fd.append("files",f);fd.append("answer_key",key);fd.append("marks",$("marks").value||1);fd.append("negative",$("negative").value||0);
 $("runScan").disabled=true;$("runScan").textContent="Analyzing batch…";msg("scanMsg","Reading roll-number bubbles, checking answers and saving per-student records. Large batches may take time.",false);
 try{const r=await fetch("/api/scan",{method:"POST",body:fd});const data=await r.json();if(!r.ok)throw new Error(data.detail||"Scan failed");latestResults=data.results||[];renderResults(latestResults);msg("scanMsg",`Processed ${latestResults.length} sheet(s). Check unreadable roll numbers and review flagged answers.`,false);$("results").scrollIntoView({behavior:"smooth"});}
 catch(e){msg("scanMsg",e.message,true);}finally{$("runScan").disabled=false;$("runScan").textContent="Analyze & calculate marks";}
};
function renderResults(results){
 const area=$("resultArea");if(!results.length){area.innerHTML='<div class="empty"><b>No saved results found</b></div>';return;}
 const ranked=[...results].sort((a,b)=>(Number(a.rank)||999999)-(Number(b.rank)||999999)||String(a.roll_number||"").localeCompare(String(b.roll_number||"")));
 const table=`<div style="overflow:auto;max-height:430px"><table class="resulttable"><thead><tr><th>Rank</th><th>Roll number</th><th>Marks</th><th>Correct</th><th>Wrong</th><th>Blank</th><th>Review</th></tr></thead><tbody>${ranked.map(r=>`<tr><td><b>${esc(r.rank??"—")}</b></td><td>${esc(r.roll_number||"UNREADABLE — REVIEW")}</td><td><b>${esc(r.marks)}</b> / ${esc(r.maximum)}</td><td>${esc(r.correct)}</td><td>${esc(r.wrong)}</td><td>${esc(r.blank)}</td><td>${r.review_required||!r.roll_number?"Review":"OK"}</td></tr>`).join("")}</tbody></table></div>`;
 const details=ranked.map((r,idx)=>`<details style="margin-top:12px;border:1px solid #e2e9f3;border-radius:10px;padding:12px"><summary style="cursor:pointer;font-size:13px;font-weight:700">${esc(r.roll_number||"UNREADABLE")} · Rank ${esc(r.rank??"—")} · ${esc(r.marks)} marks · ${esc(r.filename||"")}</summary><p style="margin:10px 0">${r.review_required||!r.roll_number?"Review recommended":"No obvious blank/multiple answers"} · OMR: ${esc(r.original_file||"not saved")} · Result PDF: ${esc(r.result_pdf||"not saved")}</p><div style="overflow:auto;max-height:300px"><table class="resulttable"><thead><tr><th>Q.</th><th>Detected</th><th>Key</th><th>Status</th></tr></thead><tbody>${(r.answers||[]).map(a=>`<tr><td>${esc(a.question)}</td><td><b>${esc(a.detected)}</b></td><td>${esc(a.key)}</td><td>${esc(a.status)}</td></tr>`).join("")}</tbody></table></div></details>`).join("");
 area.className="";area.innerHTML=`<div class="resulttop"><div class="resultmetric"><small>Sheets processed</small><strong>${ranked.length}</strong></div><div class="resultmetric"><small>Unique readable roll nos.</small><strong>${new Set(ranked.map(r=>r.roll_number).filter(Boolean)).size}</strong></div><div class="resultmetric"><small>Need roll review</small><strong>${ranked.filter(r=>!r.roll_number).length}</strong></div><div class="resultmetric"><small>Highest marks</small><strong>${Math.max(...ranked.map(r=>Number(r.marks)||0))}</strong></div></div><h3>Rank list</h3>${table}<h3 style="margin-top:24px">Question-wise details</h3>${details}<div class="result-actions"><button class="btn secondary" id="exportCsv">Export this batch CSV</button></div>`;
 $("exportCsv").onclick=()=>exportCsv(latestResults,"fjmc-omr-batch-results.csv");
}
async function exportCsv(results,name){const r=await fetch("/api/export",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({results})});if(!r.ok){msg("scanMsg","CSV export failed.",true);return;}downloadBlob(await r.blob(),name);}
$("refreshResults").onclick=async()=>{try{const r=await fetch("/api/results");const d=await r.json();latestResults=d.results||[];renderResults(latestResults);msg("scanMsg",`Loaded ${latestResults.length} saved record(s).`,false);}catch(e){msg("scanMsg","Could not load saved results.",true);}};
$("exportAllCsv").onclick=async()=>{try{const r=await fetch("/api/results");const d=await r.json();await exportCsv(d.results||[],"fjmc-all-students-results.csv");}catch(e){msg("scanMsg","Could not export saved results.",true);}};
function msg(id,text,error){$(id).textContent=text;$(id).className="message"+(error?" error":"");}
function downloadBlob(blob,name){const url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1500);}
function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
updateCount();

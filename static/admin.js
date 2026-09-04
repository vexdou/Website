(()=>{
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const fmt=x=>x?new Date(x).toLocaleString():'';
const toast=t=>{const x=$('#toast');if(!x)return;x.textContent=t;x.classList.add('show');clearTimeout(window._toast);window._toast=setTimeout(()=>x.classList.remove('show'),3000)};
async function api(url,opt={}){
 const r=await fetch(url,{credentials:'same-origin',cache:'no-store',...opt,headers:{'Content-Type':'application/json',...(opt.headers||{})}});
 let d={};try{d=await r.json()}catch{}
 if(r.status===401){location.href='/admin18';throw Error('Session expired')}
 if(!r.ok)throw Error(d.detail||'Request failed');return d
}
const login=$('#login');
if(login){
 login.onsubmit=async e=>{e.preventDefault();$('#err').textContent='';try{await api('/api/admin/login',{method:'POST',body:JSON.stringify({password:$('#password').value})});location.href='/admin18'}catch(x){$('#err').textContent=x.message}};
 return;
}
const content=$('#content');
const titles={dashboard:'Dashboard',downloads:'Downloads',queue:'Queue Monitor',users:'Users',analytics:'Analytics',platforms:'Platforms',errors:'Error Center',system:'System Health',settings:'Website Settings',security:'Security & Emergency',logs:'Audit Logs'};
const platformNames=[['youtube','YouTube'],['tiktok','TikTok'],['instagram','Instagram'],['facebook','Facebook'],['pinterest','Pinterest'],['snapchat','Snapchat'],['x','X / Twitter'],['web','Other web']];
function card(n,v,s){return `<div class="card stat"><small>${esc(n)}</small><strong>${esc(v)}</strong><span class="muted">${esc(s||'')}</span></div>`}
function table(headers,rows){return `<div class="table-wrap"><table class="table"><tr>${headers.map(x=>`<th>${esc(x)}</th>`).join('')}</tr>${rows}</table></div>`}
function dash(d){
 const p=d.platforms||{},max=Math.max(1,...Object.values(p));
 return `<div class="grid stats">
 ${card('Total downloads',d.downloads,'All time')}${card('Today',d.today,'Last 24 hours')}${card('Successful',d.completed,'Completed')}${card('Failed',d.failed,'Needs attention')}
 ${card('Active queue',d.queued+d.downloading,`${d.queued} queued · ${d.downloading} downloading`)}${card('Users',d.users,'Unique visitors')}${card('This week',d.week,'Last 7 days')}${card('Worker',d.worker==='running'?'ONLINE':'CHECK','Downloader worker')}
 </div>
 <div class="grid two section">
 <div class="card"><div class="section-title"><h2>Platform traffic</h2><span class="muted">All time</span></div>
 <div class="bars">${Object.entries(p).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`<div class="barline"><span>${esc(k)}</span><div class="bar"><i style="width:${Math.round(v/max*100)}%"></i></div><b>${v}</b></div>`).join('')||'<div class="empty">No downloads yet.</div>'}</div></div>
 <div class="card"><div class="section-title"><h2>Quick controls</h2></div><div class="actions">
 <button class="action-btn primary" data-go="settings">Website settings</button><button class="action-btn" data-go="platforms">Platform controls</button>
 <button class="action-btn" data-go="queue">Queue monitor</button><button class="action-btn" data-go="system">System health</button>
 <button class="action-btn danger" data-action="clear_failed">Clear failed</button><button class="action-btn danger" data-action="clear_queued">Clear queue</button>
 </div></div></div>
 <div class="card section"><div class="section-title"><h2>Supported platforms</h2><span class="muted">Public media only</span></div>
 <div class="platform-list">${platformNames.map(([k,n])=>`<span class="pill">${esc(n)} · ${d.settings[k+'_enabled']==='true'?'ON':'OFF'}</span>`).join('')}</div></div>`;
}
async function render(page){
 $('#pageTitle').textContent=titles[page]||page;
 $$('.nav').forEach(b=>b.classList.toggle('active',b.dataset.page===page));
 try{
 if(page==='dashboard'){content.innerHTML=dash(await api('/api/admin/overview'));bind();return}
 if(page==='users'){
  const d=await api('/api/admin/users');
  content.innerHTML=`<div class="card"><div class="section-title"><h2>Visitor accounts</h2><span class="muted">Grouped by anonymous visitor cookie</span></div>`+
  table(['Visitor','First seen','Last seen','Downloads','Success','Failed'],d.items.map(x=>`<tr><td><code>${esc(x.visitor_id)}</code></td><td>${fmt(x.first_seen)}</td><td>${fmt(x.last_seen)}</td><td>${x.downloads}</td><td class="ok">${x.completed}</td><td class="bad">${x.failed}</td></tr>`).join(''))+'</div>';return;
 }
 if(page==='downloads'){
  const d=await api('/api/admin/downloads');
  content.innerHTML=`<div class="card"><div class="section-title"><h2>Recent downloads</h2><span class="muted">Latest 200</span></div>`+
  table(['Job','Platform','Title','Status','Created','Error','Action'],d.items.map(x=>`<tr><td><code>${esc(x.job_id.slice(0,10))}</code></td><td>${esc(x.platform)}</td><td>${esc(x.title)}</td><td><span class="pill ${x.status==='completed'?'ok':x.status==='failed'?'bad':'warn'}">${esc(x.status)}</span></td><td>${fmt(x.created_at)}</td><td class="bad">${esc(x.error||'')}</td><td>${x.status==='failed'?`<button class="small-btn" data-retry="${esc(x.job_id)}">Retry</button>`:''}</td></tr>`).join(''))+'</div>';bind();return;
 }
 if(page==='queue'){
  const d=await api('/api/admin/queue');
  content.innerHTML=`<div class="card"><div class="section-title"><h2>Live queue</h2><span class="muted">${d.items.length} active jobs</span></div>`+
  table(['Job','Platform','Title','Kind','Status','Created'],d.items.map(x=>`<tr><td><code>${esc(x.job_id.slice(0,10))}</code></td><td>${esc(x.platform)}</td><td>${esc(x.title)}</td><td>${esc(x.kind)}</td><td><span class="pill warn">${esc(x.status)}</span></td><td>${fmt(x.created_at)}</td></tr>`).join('')||'<tr><td colspan="6">Queue is empty.</td></tr>')+
  `<div class="actions" style="margin-top:18px"><button class="action-btn" id="queueRefresh">Refresh</button><button class="action-btn danger" data-action="clear_queued">Clear queued/downloading</button></div></div>`;bind();return;
 }
 if(page==='analytics'){
  const d=await api('/api/admin/overview'),p=d.platforms||{};
  content.innerHTML=`<div class="grid stats">${card('Success rate',d.downloads?Math.round(d.completed/d.downloads*100)+'%':'—','Completed ÷ total')}${card('Failure rate',d.downloads?Math.round(d.failed/d.downloads*100)+'%':'—','Failed ÷ total')}${card('7-day jobs',d.week,'Recent activity')}${card('Active now',d.queued+d.downloading,'Queue + downloader')}</div>
  <div class="card section"><div class="section-title"><h2>Platform distribution</h2></div><div class="bars">${Object.entries(p).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`<div class="barline"><span>${esc(k)}</span><div class="bar"><i style="width:${d.downloads?Math.round(v/d.downloads*100):0}%"></i></div><b>${v}</b></div>`).join('')||'<div class="empty">No data.</div>'}</div></div>`;return;
 }
 if(page==='platforms'){
  const s=(await api('/api/admin/overview')).settings;
  content.innerHTML=`<div class="card"><div class="section-title"><h2>Platform switches</h2><span class="muted">Apply to new downloads</span></div>${platformNames.map(([k,n])=>`<div class="switch-row"><div><b>${esc(n)}</b><div class="muted">${s[k+'_enabled']==='true'?'Enabled':'Disabled'}</div></div><label class="switch"><input type="checkbox" data-setting="${k}_enabled" ${s[k+'_enabled']==='true'?'checked':''}><span></span></label></div>`).join('')}<div class="actions" style="margin-top:18px"><button class="action-btn primary" id="saveSwitches">Save platform switches</button><button class="action-btn" data-go="dashboard">Back to dashboard</button></div></div>`;$('#saveSwitches').onclick=saveSwitches;bind();return;
 }
 if(page==='errors'){
  const d=await api('/api/admin/errors');
  content.innerHTML=`<div class="card"><div class="section-title"><h2>Failed jobs</h2><span class="muted">Retry a failed public-media job</span></div>`+
  table(['Platform','Error','URL','Time','Action'],d.items.map(x=>`<tr><td>${esc(x.platform)}</td><td class="bad">${esc(x.error)}</td><td title="${esc(x.url)}">${esc(x.url).slice(0,120)}</td><td>${fmt(x.created_at)}</td><td><button class="small-btn" data-retry="${esc(x.job_id)}">Retry</button></td></tr>`).join('')||'<tr><td colspan="5">No failures.</td></tr>')+'</div>';bind();return;
 }
 if(page==='system'){
  const d=await api('/api/admin/system');
  content.innerHTML=`<div class="grid stats">${card('Python',d.python,'Runtime')}${card('yt-dlp',d.yt_dlp,'Extractor')}${card('curl-cffi',d.curl_cffi,'Browser impersonation')}${card('Node',d.node,'YouTube EJS')}${card('FFmpeg',d.ffmpeg,'Media merge/audio')}${card('CPU',d.cpu_count,'Available cores')}${card('Disk free',d.disk_free_gb+' GB','Working storage')}${card('Active',d.queue+d.downloading,'Queue + downloading')}</div>
  <div class="card section"><div class="section-title"><h2>Runtime diagnostics</h2></div><div class="notice">Database: ${esc(d.database)} · Work directory: <code>${esc(d.work_dir)}</code></div><div class="actions" style="margin-top:18px"><button class="action-btn" id="systemRefresh">Run diagnostics again</button><button class="action-btn" data-go="logs">View audit logs</button></div></div>`;bind();return;
 }
 if(page==='settings'){
  const s=(await api('/api/admin/overview')).settings;
  content.innerHTML=`<div class="grid two"><div class="card"><div class="section-title"><h2>Website availability</h2></div>
  <div class="switch-row"><div><b>Maintenance mode</b><div class="muted">Hide the public downloader.</div></div><label class="switch"><input type="checkbox" data-setting="maintenance" ${s.maintenance==='true'?'checked':''}><span></span></label></div>
  <div class="switch-row"><div><b>Downloads enabled</b><div class="muted">Master switch.</div></div><label class="switch"><input type="checkbox" data-setting="downloads_enabled" ${s.downloads_enabled==='true'?'checked':''}><span></span></label></div>
  <div class="field" style="margin-top:18px"><label>Maintenance message</label><textarea id="maintenance_message" rows="4">${esc(s.maintenance_message)}</textarea></div></div>
  <div class="card"><div class="section-title"><h2>Announcement</h2></div><div class="switch-row"><div><b>Show announcement</b><div class="muted">Public notice.</div></div><label class="switch"><input type="checkbox" data-setting="announcement_enabled" ${s.announcement_enabled==='true'?'checked':''}><span></span></label></div><div class="field" style="margin-top:18px"><label>Announcement text</label><textarea id="announcement" rows="4">${esc(s.announcement)}</textarea></div></div></div>
  <div class="card section"><div class="section-title"><h2>Downloader limits</h2></div><div class="settings-grid grid"><div class="field"><label>Max file size (MB)</label><input id="max_file_mb" value="${esc(s.max_file_mb)}"></div><div class="field"><label>Keep completed files (hours)</label><input id="keep_file_hours" value="${esc(s.keep_file_hours)}"></div><div class="field"><label>Worker poll seconds</label><input id="worker_poll_seconds" value="${esc(s.worker_poll_seconds||'0.7')}"></div></div><div class="actions" style="margin-top:18px"><button class="action-btn primary" id="saveSettings">Save all settings</button><button class="action-btn" data-go="platforms">Manage platforms</button></div></div>`;$('#saveSettings').onclick=saveSettings;bind();return;
 }
 if(page==='security'){
  content.innerHTML=`<div class="grid two"><div class="card"><h2>Admin authentication</h2><p class="muted">Use ADMIN_PASSWORD and ADMIN_SESSION_SECRET environment variables. Never commit them to GitHub.</p><div class="notice">Admin sessions are HTTP-only, SameSite=Strict and expire after 12 hours.</div></div><div class="card"><h2>Emergency controls</h2><p class="muted">Stop or restore new downloads.</p><div class="actions"><button class="action-btn danger" data-emergency="disable">Disable downloads</button><button class="action-btn" data-emergency="enable">Enable downloads</button><button class="action-btn danger" data-action="clear_all">Delete all records/files</button></div></div></div>
  <div class="card section"><h2>Data tools</h2><p class="muted">Export metadata/settings as JSON or clean old job records.</p><div class="actions"><button class="action-btn" id="exportData">Export JSON</button><button class="action-btn danger" data-action="clear_failed">Clear failed jobs</button><button class="action-btn danger" data-action="clear_completed">Clear completed jobs</button></div></div>`;bind();return;
 }
 if(page==='logs'){
  const d=await api('/api/admin/audit');
  content.innerHTML=`<div class="card"><div class="section-title"><h2>Audit log</h2><span class="muted">Latest 300 actions</span></div>`+
  table(['Time','Action','Detail'],d.items.map(x=>`<tr><td>${fmt(x.created_at)}</td><td><span class="pill">${esc(x.action)}</span></td><td>${esc(x.detail)}</td></tr>`).join('')||'<tr><td colspan="3">No audit events.</td></tr>')+'</div>';return;
 }
 }catch(e){toast(e.message);content.innerHTML=`<div class="card"><h2>Could not load ${esc(page)}</h2><p class="bad">${esc(e.message)}</p><button class="action-btn" data-go="dashboard">Return to dashboard</button></div>`;bind()}
}
async function saveSettings(){
 const settings={
  maintenance:$('[data-setting="maintenance"]').checked?'true':'false',
  downloads_enabled:$('[data-setting="downloads_enabled"]').checked?'true':'false',
  announcement_enabled:$('[data-setting="announcement_enabled"]').checked?'true':'false',
  maintenance_message:$('#maintenance_message').value,
  announcement:$('#announcement').value,
  max_file_mb:$('#max_file_mb').value,
  keep_file_hours:$('#keep_file_hours').value,
  worker_poll_seconds:$('#worker_poll_seconds').value
 };
 try{await api('/api/admin/settings',{method:'POST',body:JSON.stringify({settings})});toast('Settings saved')}catch(e){toast(e.message)}
}
async function saveSwitches(){
 const settings={};$$('[data-setting]').forEach(x=>settings[x.dataset.setting]=x.checked?'true':'false');
 try{await api('/api/admin/settings',{method:'POST',body:JSON.stringify({settings})});toast('Platform switches saved');render('platforms')}catch(e){toast(e.message)}
}
function bind(){
 $$('[data-go]').forEach(b=>b.onclick=()=>render(b.dataset.go));
 $$('[data-action]').forEach(b=>b.onclick=async()=>{
  if(!confirm('Are you sure? This action cannot be undone.'))return;
  try{const d=await api('/api/admin/action',{method:'POST',body:JSON.stringify({action:b.dataset.action})});toast(`Removed ${d.removed||0} records`);render('dashboard')}catch(e){toast(e.message)}
 });
 $$('[data-retry]').forEach(b=>b.onclick=async()=>{
  try{await api('/api/admin/action',{method:'POST',body:JSON.stringify({action:'retry_job',value:b.dataset.retry})});toast('Job requeued');render('queue')}catch(e){toast(e.message)}
 });
 $$('[data-emergency]').forEach(b=>b.onclick=async()=>{
  try{await api('/api/admin/settings',{method:'POST',body:JSON.stringify({settings:{downloads_enabled:b.dataset.emergency==='enable'?'true':'false'}})});toast(b.dataset.emergency==='enable'?'Downloads enabled':'Downloads disabled');render('security')}catch(e){toast(e.message)}
 });
 if($('#queueRefresh'))$('#queueRefresh').onclick=()=>render('queue');
 if($('#systemRefresh'))$('#systemRefresh').onclick=()=>render('system');
 if($('#exportData'))$('#exportData').onclick=async()=>{
  try{const d=await api('/api/admin/export');const blob=new Blob([JSON.stringify(d,null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='quickdl-admin-export.json';a.click();URL.revokeObjectURL(a.href);toast('Export created')}catch(e){toast(e.message)}
 };
}
$$('.nav').forEach(b=>b.onclick=()=>render(b.dataset.page));
if($('#refresh'))$('#refresh').onclick=()=>render($('.nav.active')?.dataset.page||'dashboard');
if($('#logout'))$('#logout').onclick=async()=>{await api('/api/admin/logout',{method:'POST'});location.href='/admin18'};
render('dashboard');
setInterval(()=>{const p=$('.nav.active')?.dataset.page;if(p==='dashboard'||p==='analytics'||p==='queue')render(p)},30000);
})();
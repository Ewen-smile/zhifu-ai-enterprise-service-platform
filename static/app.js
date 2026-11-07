'use strict';
// 智服 AI · Figma 还原版。继续使用原有 API 和数据库，未引入外部依赖。
const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));
const esc = t => String(t ?? '').replace(/[&<>"']/g,s=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]));
const icon = (n, cls='') => `<svg class="ico ${cls}" aria-hidden="true"><use href="#i-${n}"/></svg>`;
const request = async (path,method='GET',data=null) => {
  const r = await fetch(path,{method,headers:{'Content-Type':'application/json'},body:data===null?null:JSON.stringify(data)});
  let body;
  try {body=await r.json();}catch{throw new Error('服务器返回内容格式不正确');}
  if(!r.ok)throw new Error(body.error || `请求失败（HTTP ${r.status}）`);
  return body;
};
const pageNames={home:'员工首页',chat:'AI 智能问答',tickets:'我的工单',help:'自助知识中心',dashboard:'管理总览',workbench:'工单工作台',knowledge:'知识库管理','ticket-new':'提交工单','knowledge-new':'新增知识条目'};
const itPages=new Set(['dashboard','workbench','knowledge','knowledge-new']);
const statusKinds={'待处理':'warn','处理中':'blue','已解决':'good','已提交':'good','未同步':'warn','提交失败':'danger'};
const categoryIcons={'办公网络':'wifi','账号权限':'user','办公软件':'monitor','软件应用':'monitor','办公设备':'clipboard','安全规范':'shield','其他问题':'book'};
const allCategories=['办公网络','账号权限','办公软件','办公设备','其他问题'];
let currentPage='home',tickets=[],knowledge=[],summary={total:0,open:0,progress:0,done:0,knowledge:0},health={dify_connected:false,knowledge_sync_configured:false};
let lastQuestion='',lastAnswer='',lastAiCategory=null,conversationId='',toastTimeout=null,helpCategory='',chatRequestInFlight=false;
function toast(t){const e=$('#toast');e.textContent=t;e.classList.add('show');clearTimeout(toastTimeout);toastTimeout=setTimeout(()=>e.classList.remove('show'),3800);}
function badge(t,kind){return `<span class="pill ${kind||statusKinds[t]||'blue'}">${esc(t)}</span>`;}
function normCat(cat){return cat==='软件应用'?'办公软件':cat==='账户权限'?'账号权限':cat;}
function categoryFromQuestion(q){const s=(q||'').toLowerCase();if(/密码|账号|账户|权限|登录|认证/.test(s))return '账号权限';if(/wi-?fi|无线|网络|vpn|上网|断网/.test(s))return '办公网络';if(/打印|设备|电脑|投影仪|投屏|卡顿|屏幕/.test(s))return '办公设备';if(/word|excel|office|ppt|闪退|软件|安装/.test(s))return '办公软件';return '其他问题';}
function ticketCode(t){return 'IT-'+(t.created_at||'2026-11-07').slice(0,10).replaceAll('-','')+'-'+String(t.id).padStart(3,'0');}
function shortDate(t){return String(t||'').slice(0,10);}
function progressColor(k){return k==='已解决'?'good':k==='处理中'?'blue':'warn';}
function scrollTop(){document.querySelector('.workspace').scrollTop=0;window.scrollTo({top:0,behavior:'instant'});}
function navigate(name){
  if(!pageNames[name])return;
  currentPage=name;
  $$('.view').forEach(v=>v.classList.toggle('is-active',v.id==='view-'+name));
  $$('.nav-link').forEach(btn=>{const selected=(btn.dataset.page===name)||(name==='ticket-new'&&btn.dataset.page==='tickets')||(name==='knowledge-new'&&btn.dataset.page==='knowledge');btn.classList.toggle('active',selected);btn.setAttribute('aria-current',selected?'page':'false');});
  $('#roleLabel').textContent=itPages.has(name)?'IT 管理员':'员工自助服务中心';
  const scope=itPages.has(name)?'IT 部门工作空间':'员工工作空间';
  $('#breadcrumb').textContent=scope+' / '+(name==='ticket-new'?'我的工单 / 提交工单':name==='knowledge-new'?'知识库管理 / 新增知识条目':pageNames[name]);
  if(name==='ticket-new')prefillTicket();
  if(name==='home')renderHome();
  if(name==='tickets')renderMyTickets();
  if(name==='help')renderHelp();
  if(name==='dashboard')renderDashboard();
  if(name==='workbench')renderWorkbench();
  if(name==='knowledge')renderKnowledge();
  if(name==='knowledge-new')showSyncFlag();
  scrollTop();
}
async function reloadAll(){await Promise.all([refreshSummary(),refreshTickets(),refreshKnowledge()]);}
async function refreshSummary(){try{summary=await request('/api/summary');renderSummaryViews();}catch(e){toast(e.message);}}
async function refreshTickets(){try{tickets=(await request('/api/tickets')).items||[];renderSummaryViews();renderMyTickets();renderWorkbench();}catch(e){toast(e.message);}}
async function refreshKnowledge(){try{knowledge=(await request('/api/knowledge')).items||[];renderSummaryViews();renderHelp();renderKnowledge();}catch(e){toast(e.message);}}
function renderSummaryViews(){renderHome();renderDashboard();renderMyTickets();renderWorkbench();renderKnowledge();}
function renderHome(){
  const picks=['Wi-Fi','密码','投影'];const use=picks.map(term=>knowledge.find(k=>(k.title+k.keywords).toLowerCase().includes(term.toLowerCase()))).filter((v,i,a)=>v&&!a.some((z,j)=>j<i&&z?.id===v.id));
  const display=use.length?use:knowledge.slice(0,3);
  $('#homeGuides').innerHTML=display.slice(0,3).map(k=>`<div class="home-guide-row"><strong title="${esc(k.title)}">${esc(k.title)}</strong><button data-knowledge-id="${k.id}">查看指南 ↗</button></div>`).join('')||'<p class="hint">暂无知识条目</p>';
  const t=tickets[0];$('#homeTicketProgress').innerHTML=t?`<p>最近工单　${badge(t.status)}</p><strong>${esc(t.title)}</strong><div class="progress-track"><span style="width:${t.status==='已解决'?100:t.status==='处理中'?62:25}%"></span></div><small>${t.status==='已解决'?'工单已解决':t.status==='处理中'?'IT 人员正在处理，请留意后续更新。':'工单已提交，等待 IT 人员处理。'}</small>`:'<p>还没有提交过 IT 工单。</p><button class="text-action" data-page="ticket-new">发起第一张工单 →</button>';
}
function renderMyTickets(){
  const s=$('#myTicketSearch').value.trim().toLowerCase(),status=$('#myTicketStatus').value,cat=$('#myTicketCategory').value;
  const filtered=tickets.filter(t=>(!s||(t.title+' '+ticketCode(t)+' '+t.description).toLowerCase().includes(s))&&(!status||t.status===status)&&(!cat||normCat(t.category)===normCat(cat)));
  const met=[['我的全部工单',tickets.length,'layers'],['待处理',tickets.filter(t=>t.status==='待处理').length,'clock'],['处理中',tickets.filter(t=>t.status==='处理中').length,'refresh'],['已解决',tickets.filter(t=>t.status==='已解决').length,'checkcircle']];
  $('#myTicketMetrics').innerHTML=met.map(([name,num,ic])=>`<div class="metric"> <div class="metric-ic ${name==='已解决'?'green':name==='待处理'?'orange':''}">${icon(ic)}</div><div><span class="metric-label">${name}</span><div class="metric-value">${num}</div></div></div>`).join('');
  $('#myTicketRecordCount').textContent=`共 ${filtered.length} 条记录 · 本地演示数据`;
  $('#myTicketRows').innerHTML=filtered.map(t=>`<tr><td><strong>${esc(t.title)}</strong><small>${esc(ticketCode(t))}</small></td><td>${esc(normCat(t.category))}</td><td>${badge(t.status)}</td><td>${esc(t.priority==='中'?'普通':t.priority+'优先级')}</td><td>${esc(shortDate(t.created_at))}</td><td><button class="link-button" data-ticket-detail="${t.id}">查看详情 ↗</button></td></tr>`).join('')||`<tr><td colspan="6" class="empty-block">没有找到符合条件的工单</td></tr>`;
  const latest=tickets[0];$('#myRecentProgress').innerHTML=latest?`<strong>${esc(latest.title)}　${badge(latest.status)}</strong><small>最后更新：${esc(latest.updated_at)}　·　处理人：${esc(latest.assignee)}</small>`:'暂无处理记录';
}
function renderHelp(){
  const search=$('#helpSearch').value.trim().toLowerCase();
  $$('#helpCategories .category-card').forEach(b=>b.classList.toggle('selected',b.dataset.category===helpCategory));
  const matched=knowledge.filter(k=>{
    const equivalent=normCat(k.category);
    return (!helpCategory||equivalent===helpCategory)&&(!search||(k.title+' '+k.content+' '+k.keywords+' '+k.category).toLowerCase().includes(search));
  });
  $('#helpGuideList').innerHTML=matched.map(k=>`<div class="guide-row"><div><strong>${esc(k.title)}</strong><small>${esc(k.content.slice(0,88))}</small></div><button data-knowledge-id="${k.id}">查看指南　↗</button></div>`).join('')||'<div class="empty-block">没有找到符合条件的指南。可以清空筛选，或向 AI 助手提问。</div>';
}
function withinLastWeek(date){let d=new Date(String(date).replace(' ','T'));return !Number.isNaN(d.valueOf())&&Date.now()-d.getTime()<=7*86400000&&Date.now()-d.getTime()>=0;}
function renderDashboard(){
  const open=tickets.filter(t=>t.status==='待处理'||t.status==='处理中').length;
  const done=tickets.filter(t=>t.status==='已解决').length;
  const metrics=[['待处理工单',open,'clipboard','blue','待处理 + 处理中'],['已解决工单',done,'checkcircle','green','当前本地记录'],['知识条目',knowledge.length,'layers','blue','本地知识库'],['AI 命中率','—','sparkles','orange','尚未接入统计接口']];
  $('#adminMetrics').innerHTML=metrics.map(([lab,val,ic,color,sub])=>`<div class="metric"><div class="metric-ic ${color}">${icon(ic)}</div><div><span class="metric-label">${lab}</span><div class="metric-value">${val}</div><div class="metric-sub">${sub}</div></div></div>`).join('');
  const dates=[];for(let i=6;i>=0;i--){const dt=new Date();dt.setDate(dt.getDate()-i);dates.push([`${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')}`,`${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')}`]);}
  const started=dates.map(([lab,key])=>tickets.filter(t=>String(t.created_at).startsWith(key)).length);
  const resolved=dates.map(([lab,key])=>tickets.filter(t=>t.status==='已解决'&&String(t.updated_at).startsWith(key)).length);
  $('#ticketTrend').innerHTML=makeLineChart(dates.map(x=>x[0]),started,resolved);
  const counts={};tickets.forEach(t=>counts[normCat(t.category)]=(counts[normCat(t.category)]||0)+1);
  $('#categoryBreakdown').innerHTML=barRows(counts,5);
  const submitted=knowledge.filter(k=>k.sync_status==='已提交').length,pending=knowledge.filter(k=>k.sync_status!=='已提交').length;
  $('#syncBreakdown').innerHTML=`<div class="sync-line good"><span>✓ 已提交 Dify</span><b>${submitted}</b></div><div class="sync-line warn"><span>◷ 待同步 / 失败</span><b>${pending}</b></div><div class="sync-line"><span>＋ 本地知识条目</span><b>${knowledge.length}</b></div>`;
  const urgent=tickets.filter(t=>t.priority==='高'&&t.status!=='已解决').slice(0,3);
  $('#urgentTicketList').innerHTML=urgent.map(t=>`<div class="urgent-row"><span class="tile-icon">${icon(categoryIcons[normCat(t.category)]||'clipboard')}</span><div><strong>${esc(t.title)}</strong><small>${esc(ticketCode(t))} · ${esc(t.category)} · ${esc(t.created_at)}</small></div>${badge('高','danger')}</div>`).join('')||'<div class="empty-block">暂无高优先级待处理工单</div>';
  $('#activityList').innerHTML=tickets.slice(0,4).map(t=>`<div class="activity-row"><i class="status-dot"></i><time>${esc(String(t.updated_at).slice(11))}</time><span>${esc(ticketCode(t))}　${esc(t.title)} ${badge(t.status)}</span></div>`).join('')||'<div class="empty-block">暂无服务动态</div>';
  const failures=knowledge.filter(k=>k.sync_status==='提交失败').length,unresolved=tickets.filter(t=>t.status==='待处理').length;
  const notices=[['待接单工单','本地工单',unresolved?badge('需跟进','warn'):badge('正常','good'),`${unresolved} 张工单等待 IT 人员接收`,'workbench'],['知识库同步状态','知识库',failures?badge('需检查','danger'):badge('正常','good'),`${failures} 条知识同步失败，${pending} 条尚未提交成功`,'knowledge'],['服务评测指标','效果评测',badge('未接入','warn'),'满意度、AI 命中率等需真实测量后上线','dashboard']];
  $('#alertList').innerHTML='<div class="alert-row header"><span>提醒项</span><span>来源</span><span>状态</span><span>详情</span><span>操作</span></div>'+notices.map(a=>`<div class="alert-row"><strong>${a[0]}</strong><span>${a[1]}</span><span>${a[2]}</span><span>${a[3]}</span><button data-page="${a[4]}">查看 →</button></div>`).join('');
}
function makeLineChart(labels,a,b){
  const h=150,w=550,max=Math.max(3,...a,...b),x=i=>32+i*(w-54)/6,y=n=>122-(n/max)*98;
  const poly=arr=>arr.map((n,i)=>`${x(i)},${y(n)}`).join(' ');
  const grid=[0,1,2,3,4].map(i=>`<line x1="32" x2="${w-8}" y1="${122-i*24}" y2="${122-i*24}" stroke="#e8eef7" stroke-dasharray="3 3"/>`).join('');
  const dots=(arr,col)=>arr.map((n,i)=>`<circle cx="${x(i)}" cy="${y(n)}" r="3.3" fill="#fff" stroke="${col}" stroke-width="2"/>`).join('');
  return `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="近七天工单新建与解决趋势，数据来自本地工单">${grid}<polyline fill="none" stroke="#5577f5" stroke-width="2.4" points="${poly(a)}"/>${dots(a,'#5577f5')}<polyline fill="none" stroke="#21aa82" stroke-width="2.4" points="${poly(b)}"/>${dots(b,'#21aa82')}${labels.map((t,i)=>`<text x="${x(i)}" y="144" fill="#8393ae" font-size="10" text-anchor="middle">${t}</text>`).join('')}</svg>`;
}
function barRows(counts,limit=5){const entries=Object.entries(counts).sort((a,b)=>b[1]-a[1]).slice(0,limit);const sum=Object.values(counts).reduce((a,b)=>a+b,0);if(!entries.length)return '<div class="empty-block">暂无分类数据</div>';return entries.map(([name,val])=>{const pct=Math.round(val/sum*100);return `<div class="progress-row"><div class="progress-row-label"><span>${esc(name)}</span><b>${pct}% · ${val} 条</b></div><div class="small-track"><span style="width:${pct}%"></span></div></div>`;}).join('');}

// 安全版 Markdown 子集：保留原 v3.1 已验证的 DOM 安全渲染器。
function appendInlineMarkdown(parent, text) {
  const tokens = /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)|`([^`\n]+)`|\*\*([^*\n]+)\*\*|__([^_\n]+)__|\*([^*\n]+)\*|_([^_\n]+)_/g;
  let last = 0, match;
  while ((match = tokens.exec(text)) !== null) {
    if (match.index > last) parent.appendChild(document.createTextNode(text.slice(last, match.index)));
    let el;
    if (match[1] !== undefined) {
      el = document.createElement('a');
      el.textContent = match[1];
      try {
        const url = new URL(match[2]);
        if (url.protocol === 'https:' || url.protocol === 'http:') {
          el.href = url.href;
          el.target = '_blank';
          el.rel = 'noopener noreferrer nofollow';
        }
      } catch (_) { /* 无效链接仅显示文字 */ }
    } else if (match[3] !== undefined) {
      el = document.createElement('code'); el.textContent = match[3];
    } else if (match[4] !== undefined || match[5] !== undefined) {
      el = document.createElement('strong'); el.textContent = match[4] ?? match[5];
    } else {
      el = document.createElement('em'); el.textContent = match[6] ?? match[7];
    }
    parent.appendChild(el);
    last = tokens.lastIndex;
  }
  if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
}

function listMarker(line) {
  const m = line.match(/^\s{0,3}([-+*]|\d+[.)])\s+(.+)$/);
  return m ? {ordered: /^\d/.test(m[1]), body:m[2], number:parseInt(m[1],10)} : null;
}

function renderSafeMarkdown(container, markdown) {
  container.replaceChildren();
  container.classList.remove('is-plain');
  const lines = String(markdown ?? '').replace(/\r\n?/g,'\n').split('\n');
  const startsBlock = line => /^\s{0,3}(?:```|#{1,4}\s|>\s?|[-*_]{3,}\s*$)/.test(line) || !!listMarker(line);
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const fence = line.match(/^\s{0,3}```([^`]*)$/);
    if (fence) {
      i++;
      const codeLines = [];
      while (i < lines.length && !/^\s{0,3}```\s*$/.test(lines[i])) codeLines.push(lines[i++]);
      if (i < lines.length) i++;
      const pre = document.createElement('pre');
      const code = document.createElement('code'); code.textContent = codeLines.join('\n');
      pre.appendChild(code); container.appendChild(pre); continue;
    }
    const heading = line.match(/^\s{0,3}(#{1,4})\s+(.+)$/);
    if (heading) {
      const h = document.createElement('h' + Math.min(heading[1].length + 1, 5));
      appendInlineMarkdown(h, heading[2].replace(/\s+#+\s*$/,''));
      container.appendChild(h); i++; continue;
    }
    if (/^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      container.appendChild(document.createElement('hr')); i++; continue;
    }
    if (/^\s{0,3}>\s?/.test(line)) {
      const quote = document.createElement('blockquote');
      while (i < lines.length && /^\s{0,3}>\s?/.test(lines[i])) {
        const p = document.createElement('p');
        appendInlineMarkdown(p, lines[i].replace(/^\s{0,3}>\s?/,''));
        quote.appendChild(p); i++;
      }
      container.appendChild(quote); continue;
    }
    const marker = listMarker(line);
    if (marker) {
      const list = document.createElement(marker.ordered ? 'ol' : 'ul');
      if (marker.ordered && marker.number > 1) list.start = marker.number;
      while (i < lines.length) {
        const item = listMarker(lines[i]);
        if (!item || item.ordered !== marker.ordered) break;
        const li = document.createElement('li'); appendInlineMarkdown(li,item.body); i++;
        // 续行缩进作为同一条目处理。
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !listMarker(lines[i])) {
          li.appendChild(document.createElement('br'));
          appendInlineMarkdown(li, lines[i].trim()); i++;
        }
        list.appendChild(li);
      }
      container.appendChild(list); continue;
    }
    const paragraph = document.createElement('p');
    while (i < lines.length && lines[i].trim() && (i === 0 || !startsBlock(lines[i]) || !paragraph.hasChildNodes())) {
      if (paragraph.hasChildNodes()) paragraph.appendChild(document.createElement('br'));
      appendInlineMarkdown(paragraph, lines[i].trim()); i++;
      if (i < lines.length && startsBlock(lines[i])) break;
    }
    container.appendChild(paragraph);
  }
}


function renderWorkbench(){
  const search=$('#workSearch').value.trim().toLowerCase(),status=$('#workStatus').value,cat=$('#workCategory').value,priority=$('#workPriority').value;
  const match=tickets.filter(t=>(!search||(t.title+' '+ticketCode(t)+' '+t.requester+' '+t.description).toLowerCase().includes(search))&&(!status||t.status===status)&&(!cat||normCat(t.category)===normCat(cat))&&(!priority||t.priority===priority));
  const items=[['待分派',tickets.filter(t=>t.status==='待处理').length,'layers','blue'],['处理中',tickets.filter(t=>t.status==='处理中').length,'refresh','green'],['已解决',tickets.filter(t=>t.status==='已解决').length,'checkcircle','green']];
  $('#workMetrics').innerHTML=items.map(([lab,val,ic,tint])=>`<div class="metric compact"><div class="metric-ic ${tint}">${icon(ic)}</div><div><span class="metric-label">${lab}</span><div class="metric-value">${val}</div></div></div>`).join('');
  $('#workCount').textContent=`共 ${match.length} 条（当前筛选）`;
  $('#workRows').innerHTML=match.map(t=>`<tr><td><input type="checkbox" class="work-select" value="${t.id}" aria-label="选择工单 ${esc(ticketCode(t))}"></td><td><strong style="color:#4a6ce7;font-size:10px">${esc(ticketCode(t))}</strong></td><td><strong>${esc(t.title)}</strong></td><td>${esc(t.requester)}</td><td>${esc(normCat(t.category))}</td><td>${badge(t.priority,t.priority==='高'?'danger':t.priority==='低'?'good':'warn')}</td><td>${badge(t.status)}</td><td>${esc(String(t.updated_at).slice(5))}</td><td><button class="link-button" data-ticket-detail="${t.id}">详情</button> ${t.status==='待处理'?`<button class="link-button" data-assign-ticket="${t.id}">分派</button>`:''} <button class="link-button" data-update-ticket="${t.id}" data-next-status="${t.status==='待处理'?'处理中':t.status==='处理中'?'已解决':'处理中'}">${t.status==='待处理'?'接单':t.status==='处理中'?'解决':'重开'}</button></td></tr>`).join('')||'<tr><td colspan="9" class="empty-block">暂无符合条件的工单</td></tr>';
  $('#workRecent').innerHTML=[...tickets].sort((a,b)=>String(b.updated_at).localeCompare(String(a.updated_at))).slice(0,3).map(t=>`<div class="recent-row"><time>${esc(String(t.updated_at).slice(5))}</time><strong>${esc(t.title)}</strong>${badge(t.status)}<span>${esc(ticketCode(t))} · ${esc(t.assignee)}</span></div>`).join('')||'<div class="empty-block">暂无处理记录</div>';
  const waiting=tickets.filter(t=>t.priority==='高'&&t.status==='待处理').length;
  const pending=tickets.filter(t=>t.status==='待处理').length;
  $('#workReminders').innerHTML=`<div class="work-reminder">⚠ ${waiting} 张高优先级工单尚未接单</div><div class="work-reminder">◷ ${pending} 张工单等待处理</div><div class="work-reminder">▤ 已解决 ${tickets.filter(t=>t.status==='已解决').length} 张工单</div>`;
}
function renderKnowledge(){
  const search=$('#knowledgeSearch').value.trim().toLowerCase(),cat=$('#knowledgeCategory').value,status=$('#knowledgeStatus').value;
  const results=knowledge.filter(k=>(!search||(k.title+' '+k.content+' '+k.category+' '+k.keywords).toLowerCase().includes(search))&&(!cat||normCat(k.category)===normCat(cat))&&(!status||(k.sync_status||'未同步')===status));
  const sync=knowledge.filter(k=>k.sync_status==='已提交').length;
  const newWeek=knowledge.filter(k=>withinLastWeek(k.created_at)).length;
  const notSync=knowledge.length-sync;
  $('#knowledgeMetrics').innerHTML=[['知识条目',knowledge.length,'file','blue'],['近七日新增',newWeek,'checkcircle','green'],['待同步 / 失败',notSync,'clock','orange'],['Dify 已提交',sync,'layers','blue']].map(([n,v,i,t])=>`<div class="metric"><div class="metric-ic ${t}">${icon(i)}</div><div><span class="metric-label">${n}</span><div class="metric-value">${v}</div></div></div>`).join('');
  $('#knowledgeCount').textContent=`共 ${results.length} 条`;
  $('#knowledgeRows').innerHTML=results.map(k=>`<div class="kb-row"><div class="kb-title"><span class="kb-file-icon">${icon('file')}</span><div style="min-width:0"><strong title="${esc(k.title)}">${esc(k.title)}</strong><small>${esc(k.content.slice(0,72))}</small></div></div><span>${esc(normCat(k.category))}</span><span>${esc(String(k.created_at).slice(0,16))}</span>${badge(k.sync_status||'未同步')}<span><button class="kb-action" data-knowledge-id="${k.id}">查看详情</button>${k.sync_status==='已提交'?'':`<button class="kb-action" data-sync-knowledge-id="${k.id}" ${!health.knowledge_sync_configured?'disabled title="未配置 Dify 知识库密钥"':''}>同步到 Dify</button>`}</span></div>`).join('')||'<div class="empty-block">暂无符合条件的知识条目</div>';
  const counts={};knowledge.forEach(k=>counts[normCat(k.category)]=(counts[normCat(k.category)]||0)+1);
  $('#kbCategoryBars').innerHTML=barRows(counts,5);
  $('#kbConnection').textContent=health.knowledge_sync_configured?'Dify 知识库 API 已配置':'未配置知识库写入 API';
  $('#syncAllKnowledge').disabled=!health.knowledge_sync_configured||notSync===0;
}
function showSyncFlag(){const tag=$('#newKnowledgeSyncTag');tag.textContent=health.knowledge_sync_configured?'● Dify 已配置 · 提交后自动同步':'● Dify 未配置 · 仅本地保存';tag.className='subtle-badge '+(health.knowledge_sync_configured?'good':'');}
function prefillTicket(){
  const q=lastQuestion.trim(),category=lastAiCategory||categoryFromQuestion(q);
  if(q){$('#ticketTitle').value=q.slice(0,120);$('#ticketDescription').value=q.slice(0,3000);$('#ticketCategory').value=category;}
  $('#aiCategoryNote').textContent=lastAiCategory?`✦ AI 已识别类别：${lastAiCategory}`:q?'✦ 根据关键词推荐分类':'✦ 请选择问题分类';
}
function openModal(title,html){$('#modalTitle').textContent=title;$('#modalBody').innerHTML=html;$('#modalBackdrop').hidden=false;$('#closeModal').focus();}
function closeModal(){$('#modalBackdrop').hidden=true;$('#modalBody').innerHTML='';}
function showKnowledge(id){const k=knowledge.find(x=>x.id===Number(id));if(!k)return;
  const extra=itPages.has(currentPage)&&k.sync_error?`<div class="detail-body" style="margin-top:14px;color:#ce5b55"><strong>最近同步错误：</strong> ${esc(k.sync_error)}</div>`:'';
  openModal(k.title,`<div>${badge(normCat(k.category),'blue')}　${badge(k.sync_status||'未同步')} </div><div class="detail-meta"><div><small>创建时间</small><strong>${esc(k.created_at)}</strong></div><div><small>关键词</small><strong>${esc(k.keywords||'未填写')}</strong></div></div><h3>操作指南</h3><div class="detail-body">${esc(k.content)}</div>${extra}<div class="modal-buttons"><button class="btn outline" data-close-modal>关闭</button>${itPages.has(currentPage)&&k.sync_status!=='已提交'?`<button class="btn primary" data-sync-knowledge-id="${k.id}" ${!health.knowledge_sync_configured?'disabled':''}>同步到 Dify</button>`:''}</div>`);
}
function showTicket(id){const t=tickets.find(x=>x.id===Number(id));if(!t)return;
  openModal('工单详情 · '+ticketCode(t),`<h3>${esc(t.title)}</h3><div>${badge(t.status)}　${badge(normCat(t.category),'blue')}</div><div class="detail-meta"><div><small>优先级</small><strong>${esc(t.priority)}</strong></div><div><small>处理人</small><strong>${esc(t.assignee)}</strong></div><div><small>创建时间</small><strong>${esc(t.created_at)}</strong></div><div><small>更新时间</small><strong>${esc(t.updated_at)}</strong></div></div><h3>问题描述</h3><div class="detail-body">${esc(t.description)}</div><div class="modal-buttons"><button class="btn outline" data-close-modal>关闭</button>${itPages.has(currentPage)?`<button class="btn primary" data-update-ticket="${t.id}" data-next-status="${t.status==='待处理'?'处理中':t.status==='处理中'?'已解决':'处理中'}">${t.status==='待处理'?'接单处理':t.status==='处理中'?'标记已解决':'重新打开'}</button>`:''}</div>`);
}
function assignmentModal(ids){
  const valid=ids.filter(id=>tickets.some(t=>t.id===Number(id)));if(!valid.length){toast('请先选择工单');return;}
  openModal('分派 IT 工单',`<p style="font-size:12px;color:#6b7e9b">为 ${valid.length} 张工单选择负责人。分派时将保留当前工单状态。</p><label class="field"><span>指派负责人</span><select id="assignPerson"><option>王宇</option><option>李娜</option><option>周凯</option><option>IT 支持</option></select></label><div class="modal-buttons"><button class="btn outline" data-close-modal>取消</button><button class="btn primary" data-do-assign="${valid.join(',')}">确认分派</button></div>`);
}
async function updateTicket(id,status,assignee){
  const t=tickets.find(x=>x.id===Number(id));if(!t)return;
  try{await request('/api/tickets/'+id,'PATCH',{status,assignee:assignee||t.assignee||'IT 支持'});toast('工单状态已更新：'+status);closeModal();await Promise.all([refreshTickets(),refreshSummary()]);}
  catch(e){toast(e.message);}
}
function messageNode(role, text) {
  const row=document.createElement('div');row.className='chat-message '+role;
  const avatar=document.createElement('span');avatar.className='msg-avatar';avatar.textContent=role==='user'?'我':'✦';
  const bubble=document.createElement('div');bubble.className='chat-bubble'+(role==='ai'?' ai-bubble':'');
  if(role==='ai'){const name=document.createElement('div');name.className='answer-name';name.textContent='智服 AI';bubble.appendChild(name);}
  const content=document.createElement('div');content.className='msg-content';content.textContent=text;bubble.appendChild(content);row.append(avatar,bubble);$('#messages').appendChild(row);$('#messages').scrollTop=$('#messages').scrollHeight;return {content,bubble};
}
function stripTags(text){return String(text??'').replace(/<\s*think[^>]*>[\s\S]*?<\s*\/\s*think\s*>/gi,'').replace(/<\s*think[^>]*>[\s\S]*$/gi,'').replace(/\s*\[\[ZHIFU_CATEGORY:[^\]\r\n]{1,60}\]\]\s*$/gi,'').trim();}
async function sendChat(question){
  const query=String(question??$('#queryInput').value).trim();if(!query){toast('请先输入问题');return;}if(query.length>1000){toast('问题不能超过 1000 字');return;}if(chatRequestInFlight){toast('请先等待上一条回答完成');return;}
  lastQuestion=query;lastAnswer='';lastAiCategory=null;$('#queryInput').value='';navigate('chat');messageNode('user',query);
  const {content,bubble}=messageNode('ai','正在检索知识库并生成回答……');
  $('#sendChat').disabled=true;chatRequestInFlight=true;
  try{
    const r=await request('/api/chat','POST',{query,conversation_id:conversationId});
    lastAnswer=stripTags(r.answer);
    lastAiCategory=r.category_source==='dify_classifier'&&allCategories.includes(r.category)?r.category:null;
    if(r.conversation_id)conversationId=r.conversation_id;
    renderSafeMarkdown(content,lastAnswer||'暂未生成有效回答，请尝试换一种问法。');
    const footer=document.createElement('div');footer.style.cssText='display:flex;flex-wrap:wrap;gap:8px;margin-top:14px';
    const source=document.createElement('span');source.className='subtle-badge good';source.textContent=r.source==='dify'?'↗ Dify 智能回答':'↗ 本地知识检索';footer.appendChild(source);
    if(r.source!=='dify'&&r.matched?.length){r.matched.slice(0,2).forEach(m=>{const b=document.createElement('button');b.className='subtle-badge';b.textContent='▤ '+m.title;b.dataset.knowledgeId=m.id;footer.appendChild(b);});}
    if(lastAiCategory){const b=document.createElement('span');b.className='subtle-badge';b.textContent='已识别：'+lastAiCategory;footer.appendChild(b);}
    const go=document.createElement('button');go.className='subtle-badge';go.textContent='↗ 转人工 / 创建工单';go.dataset.page='ticket-new';footer.appendChild(go);bubble.appendChild(footer);
  }catch(err){content.textContent='本次问答失败：'+err.message+'。你可以稍后重试，或提交 IT 工单。';toast('问答调用失败');}
  finally{$('#sendChat').disabled=false;chatRequestInFlight=false;$('#messages').scrollTop=$('#messages').scrollHeight;}
}
function clearChat(){conversationId='';lastQuestion='';lastAnswer='';lastAiCategory=null;$('#messages').innerHTML='<div class="chat-date">新会话已开始</div>';messageNode('ai','你好！新的会话已开始。你可以直接描述遇到的 IT 问题。');toast('已开启新会话');}
async function submitTicket(form){
  const btn=$('#ticketSubmit');btn.disabled=true;
  const data=Object.fromEntries(new FormData(form).entries());
  // 联系方式仅在界面提示，不会发送至没有此字段的旧版后端。
  const body={title:data.title,description:data.description,category:data.category,priority:data.priority};
  try{const r=await request('/api/tickets','POST',body);toast('工单 #'+String(r.id).padStart(4,'0')+' 提交成功');lastQuestion='';lastAnswer='';lastAiCategory=null;form.reset();await refreshTickets();navigate('tickets');}
  catch(e){toast(e.message);}finally{btn.disabled=false;}
}
async function submitKnowledge(form){
  const btn=$('#knowledgeSubmit');btn.disabled=true;
  const data=Object.fromEntries(new FormData(form).entries());
  let content=data.content.trim();if(data.notes?.trim())content+='\n\n注意事项：\n'+data.notes.trim();
  if(data.audience&&data.audience!=='全员')content+='\n\n适用对象：'+data.audience;
  if(content.length>8000){toast('合并注意事项后超过 8000 字，请缩短内容');btn.disabled=false;return;}
  try{const r=await request('/api/knowledge','POST',{title:data.title,content,category:data.category,keywords:data.keywords||''});const sync=r.sync?.status||'未配置';toast(sync==='已提交'?'知识已保存并提交 Dify，等待异步索引':'本地已保存知识；Dify 状态：'+sync);try{sessionStorage.removeItem('zhifu_knowledge_draft_v4');}catch(_){}form.reset();await Promise.all([refreshKnowledge(),refreshSummary()]);navigate('knowledge');}
  catch(e){toast(e.message);}finally{btn.disabled=false;}
}
function saveDraft(){const f=$('#knowledgeForm');const data=Object.fromEntries(new FormData(f).entries());try{sessionStorage.setItem('zhifu_knowledge_draft_v4',JSON.stringify(data));toast('已保存到当前浏览器会话；不是服务器草稿');}catch(e){toast('浏览器不支持保存会话草稿');}}
function restoreDraft(){try{const raw=sessionStorage.getItem('zhifu_knowledge_draft_v4');if(!raw)return;const data=JSON.parse(raw),f=$('#knowledgeForm');Object.entries(data).forEach(([name,value])=>{const control=f.elements.namedItem(name);if(!control)return;if(typeof control.value==='string')control.value=value;});if(data.audience){const opt=f.querySelector(`input[name="audience"][value="${CSS.escape(data.audience)}"]`);if(opt)opt.checked=true;}}catch(_){}}
async function syncKnowledge(id){if(!health.knowledge_sync_configured){toast('尚未配置 Dify 知识库专用密钥');return;}
  try{const r=await request('/api/knowledge/'+id+'/sync','POST',{});toast(r.already_submitted?'此前已提交 Dify':'已提交 Dify，等待索引');closeModal();await refreshKnowledge();}
  catch(e){toast(e.message);await refreshKnowledge();}
}
async function syncAllKnowledge(){if(!health.knowledge_sync_configured){toast('尚未配置 Dify 知识库同步');return;}
  const pending=knowledge.filter(k=>k.sync_status!=='已提交');if(!pending.length){toast('所有本地知识均已提交 Dify');return;}
  if(!confirm(`将 ${pending.length} 条尚未提交成功的知识依次同步到 Dify。是否继续？`))return;
  const btn=$('#syncAllKnowledge');btn.disabled=true;let ok=0;let fail=0;
  for(const k of pending){try{await request('/api/knowledge/'+k.id+'/sync','POST',{});ok++;}catch(_){fail++;}}
  toast(`同步提交完成：成功 ${ok} 条，失败 ${fail} 条（索引仍由 Dify 异步处理）`);await refreshKnowledge();btn.disabled=false;
}
function handleClick(e){
  const page=e.target.closest('[data-page]');if(page){e.preventDefault();navigate(page.dataset.page);return;}
  const question=e.target.closest('[data-question]');if(question){sendChat(question.dataset.question);return;}
  const guide=e.target.closest('[data-knowledge-id]');if(guide){showKnowledge(guide.dataset.knowledgeId);return;}
  const ticket=e.target.closest('[data-ticket-detail]');if(ticket){showTicket(ticket.dataset.ticketDetail);return;}
  const update=e.target.closest('[data-update-ticket]');if(update){updateTicket(update.dataset.updateTicket,update.dataset.nextStatus);return;}
  const assign=e.target.closest('[data-assign-ticket]');if(assign){assignmentModal([assign.dataset.assignTicket]);return;}
  const doAssign=e.target.closest('[data-do-assign]');if(doAssign){const ids=doAssign.dataset.doAssign.split(',').map(Number),name=$('#assignPerson').value;Promise.all(ids.map(id=>{const t=tickets.find(z=>z.id===id);return request('/api/tickets/'+id,'PATCH',{status:t?.status||'待处理',assignee:name});})).then(async()=>{closeModal();toast(`已将 ${ids.length} 张工单分派给 ${name}`);await refreshTickets();}).catch(err=>toast(err.message));return;}
  const sync=e.target.closest('[data-sync-knowledge-id]');if(sync){sync.disabled=true;syncKnowledge(sync.dataset.syncKnowledgeId).finally(()=>sync.disabled=false);return;}
  const cat=e.target.closest('[data-category]');if(cat){helpCategory=helpCategory===cat.dataset.category?'':cat.dataset.category;renderHelp();return;}
  const pick=e.target.closest('[data-category-pick]');if(pick){$('#knowledgeFormCategory').value=pick.dataset.categoryPick;toast('已选择分类：'+pick.dataset.categoryPick);return;}
  const close=e.target.closest('[data-close-modal],#closeModal');if(close||e.target.id==='modalBackdrop'){closeModal();return;}
  if(e.target.closest('#bulkAssign')){assignmentModal($$('.work-select:checked').map(el=>Number(el.value)));return;}
  if(e.target.closest('#syncAllKnowledge')){syncAllKnowledge();return;}
  if(e.target.closest('#clearChat')){clearChat();return;}
  if(e.target.closest('#sendChat')){sendChat();return;}
  if(e.target.closest('#helpSearchButton')){renderHelp();return;}
  if(e.target.closest('#helpClearFilter')){helpCategory='';$('#helpSearch').value='';renderHelp();return;}
  if(e.target.closest('#resetMyFilter')){$('#myTicketSearch').value='';$('#myTicketStatus').value='';$('#myTicketCategory').value='';renderMyTickets();return;}
  if(e.target.closest('#saveKnowledgeDraft')){saveDraft();return;}
}
async function init(){
  document.addEventListener('click',handleClick);
  document.addEventListener('submit',e=>{if(e.target.id==='ticketForm'){e.preventDefault();submitTicket(e.target);}if(e.target.id==='knowledgeForm'){e.preventDefault();submitKnowledge(e.target);}});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('#modalBackdrop').hidden)closeModal();});
  $('#queryInput').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendChat();}});
  $$('#myTicketSearch,#myTicketStatus,#myTicketCategory').forEach(el=>el.addEventListener(el.tagName==='INPUT'?'input':'change',renderMyTickets));
  $$('#workSearch,#workStatus,#workCategory,#workPriority').forEach(el=>el.addEventListener(el.tagName==='INPUT'?'input':'change',renderWorkbench));
  $$('#knowledgeSearch,#knowledgeCategory,#knowledgeStatus').forEach(el=>el.addEventListener(el.tagName==='INPUT'?'input':'change',renderKnowledge));
  $('#helpSearch').addEventListener('input',renderHelp);
  $('#workSelectAll').addEventListener('change',e=>{$$('.work-select').forEach(input=>input.checked=e.target.checked);});
  restoreDraft();
  try{health=await request('/api/health');
    $('#sidebarMode').textContent=health.dify_connected?'演示环境 · DeepSeek / Dify RAG':'演示环境 · 本地知识检索';
    $('#serviceStatus').textContent=health.dify_connected?'AI 服务已配置':'本地检索模式';
    $('#chatHealth').textContent=health.dify_connected?'● Dify 问答已配置':'● 本地知识检索';
    $('#ragStatusText').textContent=health.dify_connected?'Dify 智能问答已配置':'本地知识检索已就绪';
    $('#ragMethod').textContent=health.dify_connected?'Dify RAG':'本地关键词检索';
    $('#chatModel').textContent=health.dify_connected?'Dify 大模型':'本地规则回答';
    showSyncFlag();
  }catch(e){$('#serviceStatus').textContent='连接异常';toast(e.message);}
  await reloadAll();
  const requested=location.hash.replace('#','');navigate(pageNames[requested]?requested:'home');
}
init();

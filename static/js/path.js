/* Document path enhancement (presentation only). Reads the existing .steps markup,
   adds icons, staged reveal and a click-for-details note. No data is created or
   changed; no network calls. Also fades the inbox detail pane when its content changes. */
(function(){
  var I={
    1:'<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
    2:'<circle cx="6" cy="6" r="2"/><circle cx="18" cy="18" r="2"/><path d="M8 6h5a4 4 0 0 1 0 8h-2a4 4 0 0 0 0 8"/>',
    3:'<circle cx="9" cy="8" r="3"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M16 5a3 3 0 0 1 0 6M18 14c2 .6 3 2.4 3 6"/>',
    4:'<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13 7l4 4"/>',
    5:'<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v10h14V9M10 13h4"/>'};
  var CHECK='<path d="M5 12l5 5 9-10"/>';
  function svg(p){return '<svg class="pico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+p+'</svg>';}
  function state(s){return s.classList.contains('done')?'مكتملة':(s.classList.contains('now')?'جارية حاليًا':'لم تبدأ بعد');}
  function enhance(root){
    var steps=root.querySelectorAll('.steps .step');
    if(!steps.length)return;
    var box=steps[0].parentNode;
    if(box.dataset.pathReady)return;
    box.dataset.pathReady='1';
    box.classList.add('steps-anim');
    var info=document.createElement('div');info.className='step-info';info.hidden=true;info.setAttribute('aria-live','polite');
    box.parentNode.insertBefore(info,box.nextSibling);
    steps.forEach(function(s,i){
      var ic=s.querySelector('i');
      if(ic&&!ic.dataset.done){var n=i+1;ic.insertAdjacentHTML('beforeend',svg(s.classList.contains('done')?CHECK:(I[n]||I[1])));var t=ic.firstChild;if(t&&t.nodeType===3)ic.removeChild(t);}
      s.style.setProperty('--d',(i*80)+'ms');
      s.setAttribute('role','button');s.setAttribute('tabindex','0');
      function open(){
        var name=(s.querySelector('span')||{}).textContent||'';
        var same=info.dataset.i==String(i)&&!info.hidden;
        steps.forEach(function(x){x.classList.remove('sel');});
        if(same){info.hidden=true;info.dataset.i='';return;}
        s.classList.add('sel');info.dataset.i=i;info.hidden=false;
        info.innerHTML='<b></b><span class="st-state"></span><em></em>';
        info.children[0].textContent='المرحلة '+(i+1)+': '+name.trim();
        info.children[1].textContent=state(s)+(s.classList.contains('now')?' (هي المرحلة الحالية للموضوع)':' (للاطلاع فقط، ليست المرحلة الحالية)');
        info.children[2].textContent='للعرض فقط: المسار يتحدد من حالة الموضوع ولا يتغير من هنا.';
        info.classList.remove('in');void info.offsetWidth;info.classList.add('in');
      }
      s.addEventListener('click',open);
      s.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();open();}});
    });
  }
  function init(){enhance(document);
    var d=document.getElementById('detail-box');
    if(d&&window.MutationObserver){
      new MutationObserver(function(){d.classList.remove('ux-fade');void d.offsetWidth;d.classList.add('ux-fade');enhance(d);}).observe(d,{childList:true});
    }
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();

/* ---- v3: timeline entry icons and quick-action icons (presentation only; text, order, links and filters unchanged) ---- */
(function(){
  var P={"refresh":"<path d=\"M23 4v6h-6\"/><path d=\"M1 20v-6h6\"/><path d=\"M3.5 9a9 9 0 0 1 14.9-3.4L23 10M1 14l4.6 4.4A9 9 0 0 0 20.5 15\"/>","upload": "<path d=\"M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4\"/><path d=\"M17 8l-5-5-5 5\"/><path d=\"M12 3v12\"/>", "note": "<path d=\"M4 4h16v12l-4 4H4z\"/><path d=\"M16 20v-4h4\"/>", "task": "<path d=\"M9 11l3 3L22 4\"/><path d=\"M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11\"/>", "edit": "<path d=\"M12 20h9\"/><path d=\"M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z\"/>", "share": "<path d=\"M17 1l4 4-4 4\"/><path d=\"M3 11V9a4 4 0 0 1 4-4h14\"/><path d=\"M7 23l-4-4 4-4\"/><path d=\"M21 13v2a4 4 0 0 1-4 4H3\"/>", "gavel": "<path d=\"M14 13l-8.5 8.5a2.1 2.1 0 0 1-3-3L11 10\"/><path d=\"M16 16l6-6\"/><path d=\"M8 8l6-6\"/><path d=\"M9 7l8 8\"/>", "plus": "<path d=\"M12 5v14M5 12h14\"/>", "file": "<path d=\"M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z\"/><path d=\"M14 2v6h6\"/><path d=\"M8 13h8M8 17h5\"/>", "alert": "<path d=\"M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z\"/><path d=\"M12 9v4M12 17h.01\"/>", "clock": "<circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"M12 6v6l4 2\"/>", "check": "<path d=\"M20 6L9 17l-5-5\"/>", "lock": "<rect x=\"3\" y=\"11\" width=\"18\" height=\"11\" rx=\"2\"/><path d=\"M7 11V7a5 5 0 0 1 10 0v4\"/>", "send": "<path d=\"M22 2L11 13\"/><path d=\"M22 2l-7 20-4-9-9-4z\"/>", "inbox": "<path d=\"M22 12h-6l-2 3h-4l-2-3H2\"/><path d=\"M5.5 5h13L22 12v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6z\"/>", "archive": "<rect x=\"3\" y=\"3\" width=\"18\" height=\"5\" rx=\"1\"/><path d=\"M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8\"/><path d=\"M10 12h4\"/>", "eye": "<path d=\"M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z\"/><circle cx=\"12\" cy=\"12\" r=\"3\"/>", "shield": "<path d=\"M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z\"/><path d=\"M9 12l2 2 4-4\"/>", "user": "<circle cx=\"12\" cy=\"8\" r=\"4\"/><path d=\"M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1\"/>", "flow": "<circle cx=\"6\" cy=\"6\" r=\"3\"/><circle cx=\"18\" cy=\"18\" r=\"3\"/><path d=\"M6 9v3a3 3 0 0 0 3 3h6\"/>", "info": "<circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"M12 16v-4M12 8h.01\"/>", "chat": "<path d=\"M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z\"/>", "clip": "<path d=\"M21.4 11l-9.2 9.2a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5\"/>", "calendar": "<rect x=\"3\" y=\"4\" width=\"18\" height=\"18\" rx=\"2\"/><path d=\"M16 2v4M8 2v4M3 10h18\"/>"};
  function ico(n,c){return '<svg class="'+(c||'pico')+'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+(P[n]||P.info)+'</svg>';}
  function tlIcon(t){
    t=(t||'').toUpperCase();
    if(/^SUBJECT_CREATED/.test(t))return['plus',''];
    if(/SUSPEND/.test(t))return['alert','warn'];
    if(/FULFILL/.test(t))return['check','ok'];
    if(/STATUS|REOPEN|UPDATED_STATUS/.test(t))return['refresh',''];
    if(/CLOSED/.test(t))return['archive',''];
    if(/REFERRAL/.test(t))return['share',''];
    if(/DOCUMENT/.test(t))return['file','ok'];
    if(/MEMO/.test(t))return['note',''];
    if(/DECISION|RESOLUTION/.test(t))return['gavel',''];
    if(/TASK/.test(t))return['task',''];
    if(/ANNOTATION/.test(t))return['edit',''];
    if(/SLA/.test(t))return['clock','warn'];
    if(/VIEWED/.test(t))return['eye',''];
    if(/WORKFLOW/.test(t))return['flow',''];
    return['info',''];
  }
  function tl(){
    document.querySelectorAll('.chronology-log[data-action-type]').forEach(function(a){
      if(a.dataset.ico)return;a.dataset.ico='1';
      var r=tlIcon(a.getAttribute('data-action-type')),h=a.querySelector('.activity-type');if(!h)return;
      h.insertAdjacentHTML('afterbegin','<span class="tl-ico '+r[1]+'">'+ico(r[0])+'</span>');
    });
  }
  function qa(){
    document.querySelectorAll('.case-actions .btn').forEach(function(b){
      if(b.dataset.ico)return;b.dataset.ico='1';
      var t=b.textContent,n=/إرفاق/.test(t)?'upload':/مذكرة/.test(t)?'note':/تكليف/.test(t)?'task':/تأشيرة/.test(t)?'edit':/إحالة/.test(t)?'share':/قرار/.test(t)?'gavel':null;
      if(n)b.insertAdjacentHTML('afterbegin',ico(n));
    });
  }
  function go(){tl();qa();}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',go);else go();
})();

/* ---- v4: subject sections as tabs (stream is the default). Only shows/hides existing sections;
   without JS every section stays visible. No data, forms or links change. ---- */
(function(){
  var nav=document.querySelector('[data-subject-nav]');var lay=document.querySelector('.gh-layout');
  if(!nav||!lay)return;
  var ids=['sec-timeline','sec-documents','sec-memos','sec-referrals','sec-tasks','sec-closure'];
  var panels=ids.map(function(i){return document.getElementById(i);}).filter(Boolean);
  document.body.classList.add('gh-tabs');
  function owner(el){for(var i=0;i<panels.length;i++){if(panels[i]===el||panels[i].contains(el))return panels[i];}return null;}
  function show(p){
    panels.forEach(function(x){x.classList.toggle('gh-on',x===p);});
    var id=p.id==='sec-timeline'?'sec-activity':p.id;
    nav.querySelectorAll('a').forEach(function(a){a.classList.toggle('gh-cur',a.dataset.jump===id);});
  }
  function reveal(id){var el=id&&document.getElementById(id);if(!el)return false;var p=owner(el);if(p){show(p);return true;}return false;}
  show(panels[0]);
  document.addEventListener('click',function(e){
    var a=e.target.closest('a[href^="#"],[data-jump]');if(!a)return;
    var id=a.dataset.jump||(a.getAttribute('href')||'').slice(1);reveal(id);
  },true);
  window.addEventListener('hashchange',function(){reveal(location.hash.slice(1));});
  if(location.hash)reveal(location.hash.slice(1));
  // a form error or an open form after a POST must never stay hidden
  panels.forEach(function(p){if(p.querySelector('.errorlist,.note.bad,[role=alert]')&&p!==panels[0])return;});
})();

/* ---- v5: readable event labels in the stream (presentation only). The raw code stays in the title
   attribute and data-action-type (filters unchanged). No record enrichment: events show only their own log text. ---- */
(function(){
  var L={SUBJECT_CREATED:'تسجيل الموضوع',SUBJECT_STATUS_CHANGED:'تغيير الحالة',SUBJECT_SUSPENDED:'تعليق الموضوع',SUBJECT_RESUMED:'استئناف العمل',SUBJECT_CLOSED:'إغلاق الموضوع',SUBJECT_REOPENED:'إعادة فتح الموضوع',DOCUMENT_LINKED:'إرفاق مستند',REFERRAL_CREATED:'إحالة',REFERRAL_COMPLETED:'إتمام إحالة',REFERRAL_WITHDRAWN:'سحب إحالة',REFERRAL_REJECTED:'إرجاع إحالة',ANNOTATION_ADDED:'تأشيرة',MEMO_CREATED:'مذكرة',TASK_CREATED:'مهمة',DECISION_CREATED:'قرار',OUTGOING_RECORDED:'مراسلة صادرة',OUTGOING_SENT_CONFIRMED:'تأكيد إرسال مراسلة',OUTGOING_REPLY_RECORDED:'ورود رد على مراسلة',NOTICE_RECORDED:'تسجيل إخطار',COMMITTEE_RESOLUTION:'قرار لجنة',DECISION_DISTRIBUTED:'توزيع القرار',DECISION_DRAFTED:'إعداد قرار',DECISION_EXECUTION_RECORDED:'تسجيل تنفيذ القرار',DECISION_ISSUED:'صدور القرار',DOCUMENT_VERSION_APPROVED:'اعتماد نسخة مستند',DOCUMENT_VERSION_CREATED:'نسخة مستند جديدة',MEMO_APPROVED:'اعتماد مذكرة',REFERRAL_FOR_INFO:'إحالة للاطلاع',REFERRAL_REASSIGNED:'إعادة تكليف إحالة',REFERRAL_RECEIVED:'استلام إحالة',REFERRAL_RESPONDED:'رد على إحالة',REFERRAL_RETURNED:'إرجاع إحالة',SLA_ESCALATED:'تصعيد تأخر',SUBJECT_UPDATED:'تعديل بيانات الموضوع',SUSPENSION_FULFILLED:'استيفاء التعليق',TASK_UPDATED:'تحديث مهمة',VIEWED_FOR_INFO:'اطلاع',WORKFLOW_TEMPLATE_APPLIED:'تطبيق قالب مسار'};
  function txt(e){return (e&&e.textContent||'').replace(/\s+/g,' ').trim();}
  function go(){
    var logs=document.querySelectorAll('.chronology-log[data-action-type]');if(!logs.length)return;
    logs.forEach(function(a){
      var code=a.getAttribute('data-action-type'),t=a.querySelector('.activity-type');
      if(t&&L[code]){var ic=t.querySelector('.tl-ico');t.title=code;Array.prototype.slice.call(t.childNodes).forEach(function(n){if(n.nodeType===3)t.removeChild(n);});t.appendChild(document.createTextNode(L[code]));}
    });
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',go);else go();
})();

/* ---- v8: subject stream fidelity (presentation only). Chips group the existing event codes; the original
   type/period filters stay under "تصفية متقدمة". Order toggle only reverses the rendered list. Creation card shows
   the subject's own creation fields. People = actors seen in the rendered log lines. ---- */
(function(){
  var root=document.querySelector('.sd-stream[data-activity-root]');if(!root)return;
  var list=root.querySelector('[data-activity-list]'),chips=root.querySelector('[data-sd-chips]');if(!list||!chips)return;
  var items=[].slice.call(list.querySelectorAll('[data-activity-item]'));
  var G=[['all','الكل',function(){return true;}],
    ['doc','المستندات',function(c){return /DOCUMENT|ATTACH/i.test(c);}],
    ['ref','الإحالات',function(c){return /REFERRAL/i.test(c);}],
    ['st','الحالة',function(c){return /STATUS|CLOSED|REOPEN|CREATED/i.test(c);}],
    ['sus','التعليق',function(c){return /SUSPEND|FULFILL|RESUME/i.test(c);}]];
  var cur='all';
  function code(i){return i.getAttribute('data-action-type')||'';}
  function apply(){var g=G.filter(function(x){return x[0]===cur;})[0];items.forEach(function(i){if(g[2](code(i)))i.removeAttribute('data-sd-hide');else i.setAttribute('data-sd-hide','1');});
    chips.querySelectorAll('button').forEach(function(b){b.classList.toggle('on',b.dataset.k===cur);b.setAttribute('aria-pressed',b.dataset.k===cur);});}
  G.forEach(function(g){var n=items.filter(function(i){return g[2](code(i));}).length;if(g[0]!=='all'&&!n)return;
    var b=document.createElement('button');b.type='button';b.dataset.k=g[0];b.className='sd-chip';b.innerHTML=g[1]+' <span class="num">'+n+'</span>';
    b.addEventListener('click',function(){cur=g[0];apply();});chips.appendChild(b);});
  var clr=root.querySelector('[data-activity-clear]');if(clr)clr.addEventListener('click',function(){cur='all';apply();});
  apply();
  // order: oldest first (as in the reference); toggle returns to newest first
  var asc=false;
  function flip(){[].slice.call(list.children).reverse().forEach(function(c){list.appendChild(c);});asc=!asc;btn.textContent=asc?'الأقدم أولاً':'الأحدث أولاً';btn.setAttribute('aria-pressed',asc);var tr=root.querySelector('[data-sd-trunc]');if(tr)tr.hidden=!asc;}
  var btn=document.createElement('button');btn.type='button';btn.className='sd-sort';btn.setAttribute('aria-label','ترتيب الخط الزمني');btn.textContent='الأحدث أولاً';btn.addEventListener('click',flip);
  var tools=root.querySelector('.activity-tools');
  flip();
  // milestones (stage items) sit with the current state: after the events when oldest-first
  function stages(){var st=[].slice.call(list.querySelectorAll('.chronology-stage'));st.forEach(function(x){if(asc)list.appendChild(x);else list.insertBefore(x,list.firstChild);});}
  var sep=document.createElement('div');sep.className='sd-sep';sep.textContent='محطات سير المعاملة';
  function place(){var st=list.querySelectorAll('.chronology-stage');if(!st.length)return;if(sep.parentNode)sep.parentNode.removeChild(sep);list.insertBefore(sep,asc?st[0]:st[0]);}
  stages();place();btn.addEventListener('click',function(){stages();place();});
  // creation card: header band (actor, label, time), the log's own text, then the subject's creation fields
  var tpl=document.getElementById('sd-creation-fields');
  var cr=items.filter(function(i){return /^SUBJECT_CREATED/.test(code(i));})[0];
  if(tpl&&cr){var body=cr.querySelector('.fi-b');
    if(body){var head=document.createElement('div');head.className='sd-ch';
      var actor=body.querySelector(':scope>small'),lab=body.querySelector('.activity-type'),tm=body.querySelector('time');
      [actor,lab,tm].forEach(function(n){if(n)head.appendChild(n);});
      var ph=body.querySelector('.activity-heading');if(ph&&!ph.children.length)ph.remove();
      body.insertBefore(head,body.firstChild);body.appendChild(tpl.content.cloneNode(true));cr.classList.add('sd-has-card');}}
  // actor lines: keep the full identity in the title, show it quietly
  items.forEach(function(i){var a=i.querySelector('.fi-b small');if(a)a.title=a.textContent.replace(/\s+/g,' ').trim();});
  // foot: count, advanced filters and order live under the stream, not above it
  var foot=document.createElement('div');foot.className='sd-foot';
  var cnt=root.querySelector('[data-activity-count]'),more=root.querySelector('.sd-more');
  [cnt,btn,more].forEach(function(n){if(n)foot.appendChild(n);});
  var note=root.querySelector('[data-sd-foot-note]');
  if(note)note.parentNode.insertBefore(foot,note);else list.parentNode.appendChild(foot);
  // people
  var seen={},ppl=[];items.forEach(function(i){var a=i.getAttribute('data-actor');if(a&&!seen[a]){seen[a]=1;ppl.push(a);}});
  var host=document.querySelector('[data-sd-people]');
  if(host&&ppl.length){var box=host.querySelector('.sd-people');ppl.forEach(function(n){var s=document.createElement('span');s.className='avatar sm';s.title=n;s.textContent=n.replace(/^(أ\.|د\.|م\.|أ\.د\.)\s*/,'').trim().slice(0,1);box.appendChild(s);});host.hidden=false;}
})();

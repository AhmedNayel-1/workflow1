/* odoo-version: HTML owns the subject layout; this script handles existing interactions only. */
(function(){
  var lay=document.querySelector('.gh-layout'),nav=document.querySelector('[data-subject-nav]');
  if(!lay||!nav)return;
  var main=lay.querySelector(':scope>.col'),box=document.getElementById('od-chatter'),det=document.getElementById('sec-stages');
  if(!main||!box||!det)return;
  var hd=document.querySelector('.od-sheet .case-h');
  /* the creation-field copy inside the first activity entry duplicates the sheet's own full-data block */
  function dedupe(){document.querySelectorAll('.sd-has-card .sd-caption,.sd-has-card .sd-fields').forEach(function(n){n.remove()});}
  var fd=document.querySelector('#sec-stages .sd-full details');if(fd)fd.open=true;
  dedupe();setTimeout(dedupe,0);setTimeout(dedupe,600);window.addEventListener('load',dedupe);if(hd)hd.classList.add('od-on');
  // The sheet, detail panel, and activity column are authored in HTML; JS only controls their behavior.
  var panels=[].slice.call(main.querySelectorAll(':scope>section.panel:not(.case-h)'));
  function show(p){panels.forEach(function(x){x.classList.toggle('od-on',x===p)});nav.querySelectorAll('a').forEach(function(a){a.classList.toggle('gh-cur',a.dataset.jump===p.id)});}
  function owner(el){for(var i=0;i<panels.length;i++)if(panels[i]===el||panels[i].contains(el))return panels[i];return null;}
  function reveal(id){
    if(id==='sec-activity'||id==='sec-timeline'){box.scrollTo({top:0,behavior:'smooth'});return true;}
    var el=id&&document.getElementById(id),p=el&&owner(el);if(p){show(p);return true;}return false;}
  show(det||panels[0]);
  document.addEventListener('click',function(e){var a=e.target.closest('a[href^="#"],[data-jump]');if(!a)return;var id=a.dataset.jump||(a.getAttribute('href')||'').slice(1);if(reveal(id))e.preventDefault();},false);
  if(location.hash)reveal(location.hash.slice(1));
  /* keep the user's place: a submitted action returns to the same tab and scroll position instead of resetting to the details tab */
  var KEEP='od-keep:'+location.pathname;
  try{var kept=JSON.parse(sessionStorage.getItem(KEEP)||'null');sessionStorage.removeItem(KEEP);
    if(kept&&Date.now()-kept.t<60000&&!location.hash){if(kept.p&&reveal(kept.p)){}
      var back=function(){window.scrollTo({top:kept.y||0,behavior:'instant'});if(box)box.scrollTop=kept.c||0;};back();setTimeout(back,120);}
  }catch(_e){}
  document.addEventListener('submit',function(e){
    var f=e.target;if(!f||f.method.toLowerCase()!=='post')return;
    var cur=panels.filter(function(x){return x.classList.contains('od-on')})[0];
    try{sessionStorage.setItem(KEEP,JSON.stringify({t:Date.now(),p:cur&&cur.id,y:Math.round(window.scrollY),c:box?box.scrollTop:0}));}catch(_e){}
  },true);
  /* add-actions open the existing form in a dialog (same <form>, moved, not rebuilt) */
  var dlg=null,lastFocus=null;
  function close(){
    if(!dlg)return;var d=dlg;dlg=null;
    d.home.appendChild(d.form);d.root.remove();document.removeEventListener('keydown',d.key,true);
    if(d.details)d.details.open=false;
    var lf=lastFocus;setTimeout(function(){if(lf&&!lf.offsetParent){var pop=lf.closest&&lf.closest('.od-pop,.ox-dropdown');var tb=pop&&document.querySelector('[data-pop="'+pop.id+'"]');if(tb)lf=tb;}if(lf&&lf.focus)lf.focus();},0);
  }
  function open(details,trigger){
    close();lastFocus=trigger;var _ap=document.getElementById('od-add-pop');if(_ap)_ap.hidden=true;
    var form=details.querySelector(':scope>.dd-b');if(!form)return false;
    var title=(details.querySelector('summary')||{}).textContent||'';title=title.replace(/\s+/g,' ').trim();
    var root=document.createElement('div');root.className='od-modal';root.setAttribute('role','dialog');root.setAttribute('aria-modal','true');root.setAttribute('aria-label',title);
    root.innerHTML='<div class="od-modal-box"><div class="od-modal-h"><b></b><button type="button" class="iconbtn" data-od-close aria-label="إغلاق">×</button></div><div class="od-modal-b"></div></div>';
    root.querySelector('b').textContent=title;
    root.querySelector('.od-modal-b').appendChild(form);
    document.body.appendChild(root);
    var sel=form.querySelector('select[name=assigned_to_id]');
    if(sel&&!sel.querySelector('option[value=""]')){var o=document.createElement('option');o.value='';o.textContent='— اختر المكلَّف —';o.setAttribute('data-od-placeholder','');sel.insertBefore(o,sel.firstChild);sel.value='';}
    var key=function(e){
      if(e.key==='Escape'){e.preventDefault();close();return;}
      if(e.key!=='Tab')return;
      var f=[].slice.call(root.querySelectorAll('a[href],button,input,select,textarea,[tabindex]')).filter(function(x){return !x.disabled&&x.offsetParent!==null&&x.tabIndex>=0;});
      if(!f.length)return;var a=f[0],z=f[f.length-1];
      if(e.shiftKey&&document.activeElement===a){e.preventDefault();z.focus();}else if(!e.shiftKey&&document.activeElement===z){e.preventDefault();a.focus();}
    };
    document.addEventListener('keydown',key,true);
    root.addEventListener('mousedown',function(e){if(e.target===root||e.target.closest('[data-od-close]'))close();});
    root.addEventListener('click',function(e){if(dlg&&e.target.closest('[data-od-close]'))close();});
    dlg={root:root,form:form,home:details,details:details,key:key};
    var first=form.querySelector('input:not([type=hidden]),textarea,select');if(first)first.focus({preventScroll:true});root.querySelector('.od-modal-b').scrollTop=0;
    return true;
  }
  document.addEventListener('click',function(e){
    var a=e.target.closest('[data-open-details]');if(!a)return;
    var id=(a.getAttribute('href')||'').slice(1),d=id&&document.getElementById(id);
    if(!d||d.tagName!=='DETAILS')return;
    e.preventDefault();e.stopImmediatePropagation();open(d,a);
  },true);
  /* Specialist actions reuse the existing action forms and modal host. */
  document.addEventListener('change',function(e){
    var select=e.target.closest&&e.target.closest('[data-specialist-action-select]');
    if(!select)return;
    var action=select.value;select.value='';
    if(!action)return;
    var launcher=document.querySelector('[data-specialist-launch="'+action+'"]');
    if(!launcher)return;
    var targetId=(launcher.getAttribute('href')||'').slice(1);
    var target=targetId&&document.getElementById(targetId);
    if(target&&target.tagName==='DETAILS')open(target,select);
  });
  // after a POST that re-renders with errors nothing is hidden: forms live inside their normal sections

  /* viewer docking: existing #pv overlay content is shown inside the activity column while it is open */
  var pv=document.getElementById('pv');
  if(pv){
    var docked=false;
    function wide(){return window.matchMedia('(min-width:1300px)').matches;}
    function dock(){var m=pv.querySelector('.modal');if(!m||docked||!wide())return;box.appendChild(m);document.body.classList.add('od-viewing');pv.classList.add('od-docked');docked=true;}
    function undock(){if(!docked)return;var m=box.querySelector(':scope>.modal');if(m)pv.appendChild(m);document.body.classList.remove('od-viewing');pv.classList.remove('od-docked');docked=false;}
    new MutationObserver(function(){pv.classList.contains('open')?dock():undock();}).observe(pv,{attributes:true,attributeFilter:['class']});
    box.addEventListener('click',function(e){var c=e.target.closest('.modal [data-close]');if(c&&docked){e.preventDefault();pv.classList.remove('open');}});
    window.addEventListener('resize',function(){if(docked&&!wide()){undock();}});
  }
})();
/* close the add-menu once an entry is chosen (dialog or link opens next) */
document.addEventListener('click',function(e){var a=e.target.closest&&e.target.closest('#od-add-pop a');if(a){var p=document.getElementById('od-add-pop');if(p)setTimeout(function(){p.hidden=true;p.classList.remove('open','on','show');},0);}},true);

/* task creation: a permission refusal (403) is shown inside the form with the entered values kept; the server rules are untouched.
   Any other outcome is sent exactly as before (the POST is the normal one; only the result display differs). */
document.addEventListener('submit',function(e){
  var f=e.target;
  if(e.defaultPrevented||!f||!f.getAttribute||(f.getAttribute('action')||'').indexOf('/workflow/tasks/create/')<0||!window.fetch||!window.FormData)return;
  e.preventDefault();
  var btn=f.querySelector('button[type=submit]'),old=btn?btn.disabled:false;if(btn)btn.disabled=true;
  var box=f.querySelector('[data-od-err]');if(box)box.remove();
  function show(msg){
    box=document.createElement('div');box.setAttribute('data-od-err','');box.setAttribute('role','alert');box.tabIndex=-1;box.className='od-err';box.textContent=msg;
    f.insertBefore(box,f.firstChild);if(btn)btn.disabled=old;box.focus();
  }
  fetch(f.action,{method:'POST',body:new FormData(f),credentials:'same-origin',redirect:'manual'}).then(function(r){
    if(r.type==='opaqueredirect'||r.status===0||(r.status>=200&&r.status<300&&r.redirected)){window.location.assign(window.location.pathname+window.location.search);return;}
    if(r.status===403){
      return r.text().then(function(t){
        var d=new DOMParser().parseFromString(t,'text/html'),ps=[].slice.call(d.querySelectorAll('section[role=alert] p')).map(function(p){return p.textContent.trim()});
        var detail=ps[1]&&ps[1].indexOf('إن كنت')<0?ps[1]:'';
        show('غير مصرح: '+(detail||ps[0]||'لا تملك صلاحية تنفيذ هذا الإجراء.')+' لم يتم حفظ المهمة، وبياناتك ما زالت في النموذج.');
      });
    }
    show('تعذر حفظ المهمة (رمز '+r.status+'). بياناتك ما زالت في النموذج، حاول مرة أخرى.');
  }).catch(function(){show('تعذر الاتصال بالخادم. بياناتك ما زالت في النموذج.');});
},false);

/* file inputs: Arabic button and label instead of the browser's English text; the real input and its name stay */
(function(){
  function enhance(i){
    if(i.dataset.odFile)return;i.dataset.odFile='1';
    var w=document.createElement('span');w.className='od-file';
    var b=document.createElement('button');b.type='button';b.className='btn sm';b.textContent='اختيار ملف';
    var n=document.createElement('span');n.className='od-file-name muted';n.textContent='لم يتم اختيار ملف';
    i.parentNode.insertBefore(w,i);w.appendChild(b);w.appendChild(n);w.appendChild(i);i.classList.add('od-file-in');
    b.addEventListener('click',function(){i.click();});
    i.addEventListener('change',function(){n.textContent=i.files&&i.files.length?[].slice.call(i.files).map(function(x){return x.name}).join('، '):'لم يتم اختيار ملف';});
  }
  function run(){[].forEach.call(document.querySelectorAll('.gh-layout input[type=file],.od-modal input[type=file]'),enhance);}
  run();new MutationObserver(run).observe(document.body,{childList:true,subtree:true});
})();

/* narrow screens: bring the current stage and the active tab into view inside their scroll boxes */
(function(){
  function reveal(box,item){if(!box||!item||box.scrollWidth<=box.clientWidth+1)return;
    var b=box.getBoundingClientRect(),i=item.getBoundingClientRect();
    if(i.left<b.left||i.right>b.right){box.scrollLeft+=(i.left+i.width/2)-(b.left+b.width/2);}}
  function run(){[].forEach.call(document.querySelectorAll('.od-statusbar,.ox-statusbar'),function(sb){reveal(sb,sb.querySelector('li.now'));});
    [].forEach.call(document.querySelectorAll('.od-sheet .subnav'),function(n){reveal(n,n.querySelector('a.gh-cur'));});}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',run);else run();
  window.addEventListener('load',run);window.addEventListener('resize',run);
  document.addEventListener('click',function(e){var a=e.target.closest&&e.target.closest('.od-sheet .subnav a');if(a)setTimeout(function(){reveal(a.parentElement,a);},60);});
})();

/* sticky notebook tabs: when the real tab row scrolls under the header, a docked copy keeps the same tabs reachable */
(function(){
  var nav=document.querySelector('.od-sheet .subnav'),hdr=document.querySelector('header.top'),sheet=document.querySelector('.od-sheet');
  if(!nav||!hdr||!sheet)return;
  var dock=document.createElement('div');dock.className='od-tabdock';dock.hidden=true;dock.setAttribute('aria-label','أقسام الموضوع');
  document.body.appendChild(dock);
  function build(){dock.innerHTML='';[].forEach.call(nav.querySelectorAll('a'),function(a){var c=a.cloneNode(true);c.removeAttribute('id');dock.appendChild(c);});}
  function sync(){var src=nav.querySelectorAll('a'),dst=dock.querySelectorAll('a');
    [].forEach.call(dst,function(d,i){if(src[i])d.className=src[i].className;});}
  function place(){
    var h=hdr.getBoundingClientRect().bottom,n=nav.getBoundingClientRect(),s=sheet.getBoundingClientRect();
    var page=document.querySelector('.od-sheet~section.panel.od-on');var end=page?page.getBoundingClientRect().bottom:s.bottom;
    var show=n.bottom<h+2&&end>h+60;
    dock.hidden=!show;if(!show)return;
    dock.style.top=h+'px';dock.style.left=s.left+'px';dock.style.width=s.width+'px';
    sync();
    var cur=dock.querySelector('a.gh-cur');if(cur&&dock.scrollWidth>dock.clientWidth+1){var b=dock.getBoundingClientRect(),i=cur.getBoundingClientRect();if(i.left<b.left||i.right>b.right)dock.scrollLeft+=(i.left+i.width/2)-(b.left+b.width/2);}
  }
  build();place();
  window.addEventListener('scroll',place,{passive:true});window.addEventListener('resize',place);
  document.addEventListener('click',function(){setTimeout(place,80);},true);
})();

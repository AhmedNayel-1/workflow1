/* Date fields: underlined text input you can type in (yyyy-mm-dd) plus an anchored calendar popup with Apply.
   The submitted value stays an ISO date, so server code is unchanged. Without JS the native date input remains. */
(function(){
  "use strict";
  var pad=function(n){return (n<10?"0":"")+n};
  var iso=function(d){return d.getFullYear()+"-"+pad(d.getMonth()+1)+"-"+pad(d.getDate())};
  var fromIso=function(s){var m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(s||"");if(!m)return null;var d=new Date(+m[1],+m[2]-1,+m[3]);return d.getMonth()===+m[2]-1?d:null};
  var AR="٠١٢٣٤٥٦٧٨٩";
  var normalize=function(s){return (s||"").replace(/[٠-٩]/g,function(c){return AR.indexOf(c)}).replace(/[\/.\s]+/g,"-").trim()};
  var mFmt=new Intl.DateTimeFormat("ar-u-nu-latn",{month:"long",year:"numeric"});
  var wFmt=new Intl.DateTimeFormat("ar-u-nu-latn",{weekday:"short"});
  var pop=null,cur=null,view=null,pending=null;
  function close(){if(pop){pop.remove();pop=null}if(cur){cur.input.setAttribute("aria-expanded","false")}cur=null}
  function bounds(i){return {min:fromIso(i.dataset.min),max:fromIso(i.dataset.max)}}
  function build(){
    var i=cur.input,b=bounds(i),first=new Date(view.getFullYear(),view.getMonth(),1);
    var lead=(first.getDay()+1)%7; /* week starts Saturday */
    var html='<div class="dp-h"><button type="button" class="dp-nav" data-dp="next" aria-label="الشهر التالي">&lsaquo;</button><b class="dp-t" aria-live="polite">'+mFmt.format(first)+'</b><button type="button" class="dp-nav" data-dp="prev" aria-label="الشهر السابق">&rsaquo;</button></div><div class="dp-g" role="grid">';
    for(var w=0;w<7;w++){var wd=new Date(2024,0,6+w);html+='<span class="dp-w">'+wFmt.format(wd)+'</span>'}
    var n=new Date(view.getFullYear(),view.getMonth()+1,0).getDate(),today=iso(new Date());
    for(var k=0;k<lead;k++)html+='<span></span>';
    for(var d=1;d<=n;d++){
      var dt=new Date(view.getFullYear(),view.getMonth(),d),s=iso(dt),off=(b.min&&dt<b.min)||(b.max&&dt>b.max);
      html+='<button type="button" class="dp-d'+(s===pending?" sel":"")+(s===today?" today":"")+'" data-d="'+s+'"'+(off?" disabled":"")+' tabindex="'+(s===(pending||today)?0:-1)+'" aria-label="'+s+'"'+(s===pending?' aria-selected="true"':"")+'>'+d+'</button>';
    }
    html+='</div><div class="dp-f"><button type="button" class="btn sm" data-dp="today">اليوم</button>'+(i.required?"":'<button type="button" class="btn sm" data-dp="clear">مسح</button>')+'<button type="button" class="btn sm primary dp-apply" data-dp="apply">تطبيق</button></div>';
    pop.innerHTML=html;
  }
  function place(){
    var r=cur.input.getBoundingClientRect(),pw=pop.offsetWidth,ph=pop.offsetHeight;
    var left=Math.min(Math.max(8,r.right-pw),innerWidth-pw-8),top=r.bottom+4;
    if(top+ph>innerHeight-8&&r.top-ph-4>8)top=r.top-ph-4;
    pop.style.left=(left+scrollX)+"px";pop.style.top=(top+scrollY)+"px";
  }
  function open(input){
    if(cur&&cur.input===input)return;close();
    cur={input:input};input.setAttribute("aria-expanded","true");
    pending=fromIso(normalize(input.value))?iso(fromIso(normalize(input.value))):null;
    view=fromIso(pending)||new Date();view=new Date(view.getFullYear(),view.getMonth(),1);
    pop=document.createElement("div");pop.className="dp-pop";pop.setAttribute("role","dialog");pop.setAttribute("aria-label","اختيار التاريخ");
    document.body.appendChild(pop);build();place();
  }
  function commit(v){
    var i=cur.input;i.value=v||"";i.setCustomValidity("");
    i.dispatchEvent(new Event("input",{bubbles:true}));i.dispatchEvent(new Event("change",{bubbles:true}));
    var inp=i;close();inp.dataset.dpSkip="1";inp.focus();
  }
  function check(i){
    var v=normalize(i.value);if(!v){i.setCustomValidity("");return}
    var d=fromIso(v);
    if(!d){i.setCustomValidity("اكتب التاريخ بصيغة سنة-شهر-يوم، مثل 2026-12-31");return}
    var b=bounds(i);
    if((b.min&&d<b.min)||(b.max&&d>b.max)){i.setCustomValidity("التاريخ خارج المدى المسموح");return}
    i.setCustomValidity("");i.value=iso(d);
  }
  function enhance(i){
    if(i.dataset.dp||i.dataset.native!==undefined)return;
    i.dataset.dp="1";i.dataset.min=i.getAttribute("min")||"";i.dataset.max=i.getAttribute("max")||"";
    var v=i.value;i.removeAttribute("min");i.removeAttribute("max");
    i.type="text";i.value=v;i.setAttribute("inputmode","numeric");i.setAttribute("placeholder","yyyy-mm-dd");i.setAttribute("dir","ltr");i.setAttribute("autocomplete","off");
    i.setAttribute("aria-haspopup","dialog");i.setAttribute("aria-expanded","false");i.classList.add("dp-in");
    i.addEventListener("focus",function(){if(i.dataset.dpSkip){delete i.dataset.dpSkip;return}open(i)});
    i.addEventListener("click",function(){open(i)});
    i.addEventListener("input",function(){check(i);if(cur&&cur.input===i){var d=fromIso(normalize(i.value));if(d){pending=iso(d);view=new Date(d.getFullYear(),d.getMonth(),1);build();place()}}});
    i.addEventListener("blur",function(){check(i)});
    i.addEventListener("keydown",function(e){
      if(e.key==="ArrowDown"&&cur&&cur.input===i){e.preventDefault();var t=pop.querySelector(".dp-d[tabindex='0']")||pop.querySelector(".dp-d:not([disabled])");if(t)t.focus()}
      else if(e.key==="ArrowDown"){open(i)}
      else if(e.key==="Escape"&&pop){e.preventDefault();close()}
      else if(e.key==="Enter"&&pop){var d=fromIso(normalize(i.value));if(d){e.preventDefault();commit(iso(d))}}
    });
  }
  /* one click handler: month arrows (RTL: right arrow = previous month), day pick, today, clear, apply, click outside */
  document.addEventListener("click",function(e){
    if(!pop)return;
    var inside=pop.contains(e.target),t=inside?e.target.closest("[data-dp],[data-d]"):null;
    if(t&&t.dataset.d){pending=t.dataset.d;build();place();var s=pop.querySelector(".dp-d.sel");if(s)s.focus();return}
    if(t){
      var a=t.dataset.dp;
      if(a==="prev"||a==="next"){view=new Date(view.getFullYear(),view.getMonth()+(a==="next"?1:-1),1);build();place();var f=pop.querySelector('[data-dp="'+a+'"]');if(f)f.focus();return}
      if(a==="today"){commit(iso(new Date()));return}
      if(a==="clear"){commit("");return}
      if(a==="apply"){if(pending)commit(pending);else close();return}
    }
    if(!inside&&!(cur&&e.target===cur.input))close();
  });
  document.addEventListener("keydown",function(e){
    if(!pop)return;
    if(e.key==="Escape"){var i=cur.input;close();i.dataset.dpSkip="1";i.focus();return}
    var d=document.activeElement;
    if(d&&d.classList&&d.classList.contains("dp-d")){
      var step={ArrowLeft:1,ArrowRight:-1,ArrowUp:-7,ArrowDown:7}[e.key];
      if(step){e.preventDefault();var dt=fromIso(d.dataset.d);dt.setDate(dt.getDate()+step);pending=iso(dt);view=new Date(dt.getFullYear(),dt.getMonth(),1);build();place();var n=pop.querySelector('.dp-d[data-d="'+pending+'"]');if(n)n.focus()}
      else if(e.key==="Enter"){e.preventDefault();pending=d.dataset.d;commit(pending)}
    }
  });
  addEventListener("scroll",function(){if(pop)place()},true);addEventListener("resize",function(){if(pop)place()});
  function init(){document.querySelectorAll('input[type="date"]').forEach(enhance)}
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();

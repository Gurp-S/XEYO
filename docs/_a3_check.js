(function(){
'use strict';
var D=window.__A3__||{generated_at:'',days:[]};
var DAYS=(D.days||[]).slice();
var NS='http://www.w3.org/2000/svg';
var state={day:null,models:[]}; // models = selected model names (empty = all)
var root=null;

/* palette: porcelain-ish blue ramp for up to 6 series.
   用 CSS 变量（var(--mN)）以便黑夜模式一键换肤。 */
var PAL=['var(--m0)','var(--m1)','var(--m2)','var(--m3)','var(--m4)','var(--m5)'];
var HIT='var(--hit)', MISS='var(--miss)';

function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function fmt(n){n=Number(n)||0;if(n>=1e9)return(n/1e9).toFixed(1)+'b';if(n>=1e6)return(n/1e6).toFixed(1)+'m';if(n>=1e3)return(n/1e3).toFixed(1)+'k';return n.toLocaleString('en-US')}
function pct(x,d){d=d==null?1:d;return (Number(x)*100).toFixed(d)+'%'}
function cost(n){n=Number(n)||0;return n.toLocaleString('en-US',{maximumFractionDigits:6})}
function mk(sel){return document.createElement(sel)}
function shortModel(m){var s=String(m||'').split('/').pop();return s}
function hourOf(ts){var d=new Date(Number(ts)*1000);return isNaN(d)?-1:d.getHours()}
function modelColor(m,i){var idx=PAL.indexOf(m._c);if(idx<0){var n=(i==null?0:i)%PAL.length;return PAL[n]}return m._c}

/* ── 环形图（SVG stroke-dasharray）── */
/* segments: [{v, color, name}]  name 用于底下明细列表 */
function donut(segments,opts){
  opts=opts||{};
  var size=opts.size||150, sw=opts.sw||22, cx=size/2, cy=size/2, r=(size-sw)/2-2;
  var C=2*Math.PI*r;
  var total=segments.reduce(function(s,x){return s+Number(x.v||0)},0)||1;
  var svg=document.createElementNS(NS,'svg');
  svg.setAttribute('viewBox','0 0 '+size+' '+size);
  svg.setAttribute('class','svg-wrap');
  svg.setAttribute('preserveAspectRatio','xMidYMid meet');
  // track（stroke 用 CSS 变量，随黑夜模式自动换肤）
  var tr=document.createElementNS(NS,'circle');
  tr.setAttribute('cx',cx);tr.setAttribute('cy',cy);tr.setAttribute('r',r);
  tr.setAttribute('fill','none');tr.setAttribute('stroke-width',sw);
  tr.style.stroke='var(--track)';
  svg.appendChild(tr);
  // segments（加 data-i 供点击高亮）
  var start=0;
  segments.forEach(function(seg,i){
    var frac=Number(seg.v||0)/total;
    if(frac<=0)return;
    var len=frac*C;
    var c=document.createElementNS(NS,'circle');
    c.setAttribute('cx',cx);c.setAttribute('cy',cy);c.setAttribute('r',r);
    c.setAttribute('fill','none');c.setAttribute('class','seg');
    c.setAttribute('data-i',i);
    c.style.stroke=seg.color;             // 变量解析走 CSS 样式
    c.setAttribute('stroke-width',sw);
    c.setAttribute('stroke-dasharray',len+' '+(C-len));
    c.setAttribute('stroke-dashoffset',-start*C+C/4);
    c.setAttribute('transform','rotate(-90 '+cx+' '+cy+')');
    // 动画
    var anim=document.createElementNS(NS,'animate');
    anim.setAttribute('attributeName','stroke-dashoffset');
    anim.setAttribute('from',-start*C+C/4);
    anim.setAttribute('to',-start*C+C/4);
    anim.setAttribute('dur','1s');
    anim.setAttribute('begin','0.5s');
    anim.setAttribute('fill','freeze');
    c.appendChild(anim);
    svg.appendChild(c);
    start+=frac;
  });
  return svg;
}

/* center stats (HTML overlay) */
function centerWrap(val,label){
  var d=mk('div');d.className='dcenter';
  d.innerHTML='<div class="v">'+val+'</div><div class="l">'+esc(label)+'</div>';
  return d;
}

/* 环形卡：环形 + 中心数值 + 底下具体数据明细列表。
   fmt 为数值格式化函数；点击环形段或明细条目互相高亮。 */
function donutCard(title,sub,segments,val,label,fmt){
  fmt=fmt||fmtNum;
  var total=segments.reduce(function(s,x){return s+Number(x.v||0)},0)||1;
  var c=mk('div');c.className='card';
  var h=mk('header');h.innerHTML='<h2>'+esc(title)+'</h2><div class="sub">'+esc(sub)+'</div>';
  var b=mk('div');b.className='body';
  var dc=mk('div');dc.className='donut-c';
  var svg=donut(segments,{size:132,sw:22});
  dc.appendChild(svg);dc.appendChild(centerWrap(val,label));
  b.appendChild(dc);
  c.appendChild(h);c.appendChild(b);

  // 明细列表
  var dl=mk('div');dl.className='dlist';
  segments.forEach(function(seg,i){
    var row=mk('div');row.className='drow';row.setAttribute('data-i',i);
    var p=(Number(seg.v||0)/total)*100;
    var vv=fmt(seg.v);
    if(seg.miss!=null)vv=fmt(seg.miss)+'/'+fmt(seg.v);
    var pp=p.toFixed(1)+'%';
    if(seg.rate!=null)pp=seg.rate+'%';
    row.innerHTML='<span class="sw" style="background:'+seg.color+'"></span>'+
      '<span class="nm">'+esc(seg.name)+'</span>'+
      '<span class="vv">'+vv+'</span>'+
      '<span class="pp">'+pp+'</span>';
    dl.appendChild(row);
  });
  c.appendChild(dl);

  // 高亮联动
  function setSel(i){
    var segs=svg.querySelectorAll('.seg');
    var rows=dl.querySelectorAll('.drow');
    segs.forEach(function(s){s.classList.toggle('sel',Number(s.getAttribute('data-i'))===i)});
    rows.forEach(function(r){r.classList.toggle('sel',Number(r.getAttribute('data-i'))===i)});
    svg.classList.add('dim');dl.classList.add('dim');
  }
  function clearSel(){
    svg.classList.remove('dim');dl.classList.remove('dim');
    svg.querySelectorAll('.seg.sel').forEach(function(s){s.classList.remove('sel')});
    dl.querySelectorAll('.drow.sel').forEach(function(r){r.classList.remove('sel')});
  }
  function bind(el){
    el.style.cursor='pointer';
    el.addEventListener('click',function(){
      var i=Number(el.getAttribute('data-i'));
      var already=enabled&&el.classList.contains('sel');
      if(already){clearSel();return}
      setSel(i);
    });
  }
  var enabled=true;
  svg.querySelectorAll('.seg').forEach(bind);
  dl.querySelectorAll('.drow').forEach(bind);
  return c;
}
function fmtNum(n){return fmt(n)}

/* ── 新功能面板：请求按小时分布（SVG 迷你柱）── */
function hourChart(tot){
  var byTurn=tot.by_turn||[];
  var hours=new Array(24).fill(0);
  byTurn.forEach(function(t){var h=hourOf(t.first_ts);if(h>=0&&h<24)hours[h]++});
  var maxH=Math.max.apply(null,hours)||1;
  var W=560,H=120,pad=24,bw=(W-pad)/24;
  var svg=document.createElementNS(NS,'svg');
  svg.setAttribute('viewBox','0 0 '+W+' '+H);svg.setAttribute('class','svg-wrap hsvg');
  svg.setAttribute('preserveAspectRatio','xMidYMax meet');
  var base=H-24;
  var line=document.createElementNS(NS,'line');
  line.setAttribute('x1',pad);line.setAttribute('y1',base);line.setAttribute('x2',W);line.setAttribute('y2',base);
  line.setAttribute('stroke','var(--line)');line.setAttribute('stroke-width',1);svg.appendChild(line);
  var peak=0,peakH=-1;
  for(var i=0;i<24;i++){
    var x=pad+i*bw,hh=(H-24)*hours[i]/maxH;
    if(hours[i]>peakH){peakH=hours[i];peak=i}
    var r=document.createElementNS(NS,'rect');
    r.setAttribute('x',x+1.5);r.setAttribute('y',base-Math.max(1,hh));r.setAttribute('width',bw-3);r.setAttribute('height',Math.max(1,hh));
    r.setAttribute('fill',i===peak?'var(--data)':'var(--m2)');r.setAttribute('rx',1.5);
    r.setAttribute('data-hour',i);r.setAttribute('data-count',hours[i]);
    r.style.cursor='pointer';
    r.addEventListener('mouseenter',function(ev){
      var h=this.getAttribute('data-hour');
      var cnt=this.getAttribute('data-count');
      var rect=this.getBoundingClientRect();
      var tooltip=document.querySelector('.hour-tooltip');
      if(!tooltip){
        tooltip=mk('div');tooltip.className='hour-tooltip';
        document.body.appendChild(tooltip);
      }
      tooltip.innerHTML='<b>'+esc(h+':00')+'</b> · '+cnt+' 请求';
      tooltip.style.display='block';
      tooltip.style.left=rect.left+'px';
      tooltip.style.top=(rect.top-32)+'px';
    });
    r.addEventListener('mouseleave',function(){
      var tooltip=document.querySelector('.hour-tooltip');
      if(tooltip)tooltip.style.display='none';
    });
    svg.appendChild(r);
    if(i%3===0){var t=document.createElementNS(NS,'text');t.textContent=(i<10?'0':'')+i;
      t.setAttribute('x',x+bw/2);t.setAttribute('y',H-6);t.setAttribute('text-anchor','middle');
      t.setAttribute('font-size',7.5);t.setAttribute('font-weight',600);t.setAttribute('fill','var(--mut)');svg.appendChild(t);}
  }
  var mt=document.createElementNS(NS,'text');mt.textContent='peak '+peakH+' @ '+peak+':00';
  mt.setAttribute('x',W-pad);mt.setAttribute('y',14);mt.setAttribute('text-anchor','end');
  mt.setAttribute('font-size',8);mt.setAttribute('font-weight',700);mt.setAttribute('fill','var(--data)');svg.appendChild(mt);
  return svg;
}

/* ── 新功能面板：分模型对比（紧凑表 + 命中率条）── */
function modelCompare(models){
  var wrap=mk('div');
  var T=mk('table');T.className='tbl';
  T.innerHTML='<thead><tr><th>模型</th><th class="num">命中率</th><th class="num">请求</th>'+
    '<th class="num">输出</th><th class="num">成本</th></tr></thead><tbody></tbody>';
  var tb=T.querySelector('tbody');
  var maxReq=Math.max.apply(null,(models||[]).map(function(m){return Number(m.requests)||0}).concat([1]));
  models.forEach(function(m){
    var tr=mk('tr');
    var ti=Number(m.cache_hit)+Number(m.cache_miss);
    var reqBar=Math.max(6,Math.round((Number(m.requests)/maxReq)*100));
    tr.innerHTML='<td><span class="model-chip"><i style="background:'+m._c+'"></i>'+esc(shortModel(m.model))+'</span></td>'+
      '<td class="num"><span class="hbar"><span class="track"><span class="fill" style="width:'+(Number(m.hit_rate)*100).toFixed(0)+'%;background:'+m._c+'"></span></span><span class="pct">'+pct(m.hit_rate)+'</span></span></td>'+
      '<td class="num"><span class="reqcaps"><span class="bar" style="width:'+reqBar+'%;background:'+m._c+'"></span><span class="rn">'+fmt(m.requests)+'</span></span></td>'+
      '<td class="num">'+fmt(m.output)+'</td>'+
      '<td class="num">'+cost(m.cost_cny)+'</td>';
    tb.appendChild(tr);
  });
  wrap.appendChild(T);
  return wrap;
}

function kpiCard(k,s,v,cls){
  var c=mk('div');c.className='kpi'+(cls?' '+cls:'');
  c.innerHTML='<div class="k">'+esc(k)+'</div><div class="v">'+v+'</div><div class="s">'+esc(s)+'</div>';
  return c;
}

/* 选中模型集合的辅助：空 = 全部 */
function filterByModel(list,key){
  if(!state.models.length)return list;
  return list.filter(function(m){return state.models.indexOf(m[key])>=0});
}

/* ── 模型构建（用于侧栏/环形/明细统一配色）── */
function buildModels(day){
  var bm=(day.total.by_model||[]).slice();
  bm.forEach(function(m,i){m._c=PAL[i%PAL.length]});
  return bm;
}

function renderSidebar(day){
  var models=buildModels(day);
  var side=mk('aside');side.className='side';
  var brand=mk('div');brand.className='brand';brand.textContent='XEYO · QUALITY MONITOR';
  var h1=mk('h1');h1.textContent='A3 日常监控';
  var sub=mk('div');sub.className='sub';sub.textContent='缓存命中率 · 成本 · 用量快照';
  side.appendChild(brand);side.appendChild(h1);side.appendChild(sub);
  var rule=mk('hr');rule.className='rule';side.appendChild(rule);

  side.appendChild(sideHead('日期'));
  var dl=mk('div');dl.className='daylist';
  DAYS.forEach(function(d){
    var b=mk('button');b.className='daybtn'+(state.day===d.day?' act':'');
    b.innerHTML='<span class="d">'+esc(d.day)+'</span><span class="s">'+(d.accepted?'已验收':'待验收')+'</span>';
    b.addEventListener('click',function(){state.day=d.day;renderAll()});
    dl.appendChild(b);
  });
  side.appendChild(dl);
  var rule2=mk('hr');rule2.className='rule';side.appendChild(rule2);

  side.appendChild(sideHead('模型'));
  var mg=mk('div');mg.className='modelgroup';
  models.forEach(function(m){
    var on=!state.models.length||state.models.indexOf(m.model)>=0;
    var row=mk('label');row.className='mcheck'+(on?' on':'');
    row.innerHTML='<i style="background:'+(on?m._c:'transparent')+';border-color:'+(on?m._c:'var(--faint)')+'"></i>'+
      '<span class="nm">'+esc(shortModel(m.model))+'</span><span class="pc">'+pct(m.hit_rate)+'</span>';
    row.addEventListener('click',function(ev){ev.preventDefault();
      var i=state.models.indexOf(m.model);
      if(i<0)state.models.push(m.model);else state.models.splice(i,1);
      state.models.sort();renderAll();});
    mg.appendChild(row);
  });
  side.appendChild(mg);

  var rule3=mk('hr');rule3.className='rule';side.appendChild(rule3);
  var lg=mk('div');lg.className='legend';
  lg.appendChild(sideHead('图例'));
  var hc=mk('div');hc.className='lgitem';hc.innerHTML='<span class="sw" style="background:'+HIT+'"></span>缓存命中';
  var mc=mk('div');mc.className='lgitem';mc.innerHTML='<span class="sw" style="background:'+MISS+'"></span>缓存未命中';
  lg.appendChild(hc);lg.appendChild(mc);
  side.appendChild(lg);

  var tools=mk('div');tools.className='tools';
  var eb=mk('button');eb.className='btn';eb.textContent='导出 JSON';
  eb.addEventListener('click',exportJson);
  tools.appendChild(eb);
  side.appendChild(tools);

  var tr=mk('div');tr.className='themerow';
  var tb=mk('button');tb.className='themetoggle';
  var isDark=document.documentElement.getAttribute('data-theme')==='dark';
  tb.innerHTML=(isDark?'☀ 切换白天':'☾ 切换黑夜')+'<span class="lbl"></span>';
  tb.addEventListener('click',toggleTheme);
  tr.appendChild(tb);
  side.appendChild(tr);

  var src=mk('div');src.className='src';src.textContent='数据源 quality_validation.json';
  side.appendChild(src);
  return side;
}
function sideHead(t){var h=mk('h3');h.textContent=t;return h}

function renderMain(day){
  var main=mk('div');main.className='main';
  var tot=day.total||{};
  var hr=Number(tot.hit_rate)||0;
  var accepted=day.accepted;

  // hero
  var hero=mk('div');hero.className='hero';
  var ttl=mk('div');ttl.className='ttl';
  ttl.innerHTML='<h2>'+esc(day.day)+' · 快照</h2><div class="dek">命中率 / 成本 / 用量，一屏总览</div>';
  var meta=mk('div');meta.className='meta';
  meta.innerHTML='<span class="st">'+esc((accepted?'已验收':'待验收'))+'</span> · 生成于 '+esc(D.generated_at||'—')+
    '<br><button class="btn ghost" id="detailBtn">查看会话明细</button>';
  hero.appendChild(ttl);hero.appendChild(meta);
  main.appendChild(hero);

  // KPIs
  var kpi=mk('div');kpi.className='kpis';
  var kcls=hr>=0.9?'good':(hr>=0.7?'':'bad');
  kpi.appendChild(kpiCard('命中率','CACHE HIT RATE',pct(hr),'accent'));
  kpi.appendChild(kpiCard('请求','ALL REQUESTS',fmt(tot.requests)));
  kpi.appendChild(kpiCard('输出 token','OUTPUT',fmt(tot.output)));
  kpi.appendChild(kpiCard('输入 token','PROMPT INPUT',fmt(tot.prompt_tokens)));
  kpi.appendChild(kpiCard('成本','COST · CNY',cost(tot.cost_cny)));
  kpi.appendChild(kpiCard('C2','COMPACTIONS',fmt(tot.c2_count),accepted?'good':''));
  kpi.appendChild(kpiCard('会话数','SESSIONS',fmt(tot.sessions||0)));
  kpi.appendChild(kpiCard('单位成本','COST/REQ',cost(tot.cost_cny/(tot.requests||1))));
  main.appendChild(kpi);

  // donut cards
  var models=filterByModel(buildModels(day),'model');
  var cards=mk('div');cards.className='cards';

  // 1. 整体命中率（按模型细分）
  var hit=Number(tot.cache_hit)||0, miss=Number(tot.cache_miss)||0;
  var hitSegs=models.map(function(m){
    var h=Number(m.cache_hit)||0, ms=Number(m.cache_miss)||0;
    var p=(h+ms)>0?(h/(h+ms)*100).toFixed(1):'0.0';
    return {v:h,color:m._c,name:shortModel(m.model),miss:ms,rate:p};
  });
  cards.appendChild(donutCard('整体命中率','HIT RATE',
    hitSegs,
    pct(hr),'命中 / 总输入',fmt));

  // 2. 输入 token 构成 (per model hit)
  var toks=filterByModel(buildModels(day),'model').map(function(m){
    return {v:m.prompt_tokens,color:m._c,name:shortModel(m.model)}});
  var maxTok=toks.reduce(function(s,x){return s+Number(x.v||0)},0)||1;
  cards.appendChild(donutCard('输入 token · 构成','INPUT BY MODEL',
    toks,fmt(maxTok),'总输入 token',fmt));

  // 3. 成本分模型（老行可能缺 cost_cny：此时按该模型输入 token 占比分摊日总成本兜底）
  var dayCost=Number(tot.cost_cny)||0, dayTok=buildModels(day).reduce(function(s,m){return s+Number(m.prompt_tokens||0)},0)||1;
  var costs=models.map(function(m){
    var c=Number(m.cost_cny);
    if(!c){c=dayCost*(Number(m.prompt_tokens||0)/dayTok);}
    return {v:c,color:m._c,name:shortModel(m.model)}});
  var totCost=costs.reduce(function(s,x){return s+Number(x.v||0)},0);
  cards.appendChild(donutCard('成本 · 模型','COST BY MODEL',
    costs,cost(totCost),'总成本 CNY',cost));

  // 4. 请求分模型
  var reqs=models.map(function(m){return {v:m.requests,color:m._c,name:shortModel(m.model)}});
  var totReq=reqs.reduce(function(s,x){return s+Number(x.v||0)},0);
  cards.appendChild(donutCard('请求 · 模型','REQUESTS BY MODEL',
    reqs,fmt(totReq),'总请求数',fmt));

  main.appendChild(cards);

  // ── 下方功能面板：请求小时分布 + 分模型对比 ──
  var extra=mk('div');extra.className='extra';

  // 面板1：请求按小时分布
  var p1=mk('div');p1.className='panel';
  var p1h=mk('header');p1h.innerHTML='<h2>请求 · 小时分布</h2><div class="sub">REQUESTS BY HOUR</div>';
  p1.appendChild(p1h);
  var p1b=mk('div');p1b.className='pbody';p1b.appendChild(hourChart(tot));
  p1.appendChild(p1b);extra.appendChild(p1);

  // 面板2：分模型对比（命中率/请求/输出/成本）
  var p2=mk('div');p2.className='panel';
  var p2h=mk('header');p2h.innerHTML='<h2>分模型对比</h2><div class="sub">MODEL COMPARE</div>';
  p2.appendChild(p2h);
  var p2b=mk('div');p2b.className='pbody';
  var mm=filterByModel(buildModels(day),'model');
  p2b.appendChild(modelCompare(mm));
  var ax=mk('div');ax.className='applex';
  ax.innerHTML='<span class="apple"><i style="background:'+HIT+'"></i>命中</span>'+
    '<span class="apple"><i style="background:'+MISS+'"></i>未命中</span>';
  p2b.appendChild(ax);p2.appendChild(p2b);extra.appendChild(p2);

  main.appendChild(extra);
  main.querySelector('#detailBtn').addEventListener('click',function(){openModal(day)});
  return main;
}

/* ── 明细弹窗：分模型表 + 分对话 ── */
function openModal(day){
  var m=mk('div');m.className='modal on';
  var sheet=mk('div');sheet.className='sheet';
  var head=mk('div');head.className='mhead';
  var close=mk('div');close.className='close';close.textContent='×';
  close.addEventListener('click',function(){m.parentNode&&m.parentNode.removeChild(m)});
  head.innerHTML='<h2>'+esc(day.day)+' · 会话明细</h2><div class="x">'+esc(day.total.by_turn.length)+' 轮 · 点击列头排序</div>';
  head.appendChild(close);
  sheet.appendChild(head);

  // 分模型（固定）
  var mh=mk('h3');mh.textContent='分模型';mh.style.cssText='margin:16px 0 6px;font-size:14px';sheet.appendChild(mh);
  var modelFixed=mk('div');modelFixed.className='model-fixed';sheet.appendChild(modelFixed);
  var bm=filterByModel(buildModels(day).slice(),'model');
  var T=mk('table');T.className='tbl';
  T.innerHTML='<thead><tr><th>模型</th><th>Provider</th><th class="num">命中率</th><th class="num">命中/输入</th>'+
    '<th class="num">请求</th><th class="num">输出</th><th class="num">成本</th></tr></thead><tbody></tbody>';
  var tb=T.querySelector('tbody');
  function paint(list){
    tb.innerHTML='';
    list.forEach(function(m){
      var ti=Number(m.cache_hit)+Number(m.cache_miss);
      var tr=mk('tr');
      tr.innerHTML='<td><span class="model-chip"><i style="background:'+m._c+'"></i>'+esc(m.model)+'</span></td>'+
        '<td><span class="tag">'+esc(m.provider)+'</span></td>'+
        '<td class="num" style="font-weight:800">'+pct(m.hit_rate)+'</td>'+
        '<td class="num"><span class="tag">'+fmt(m.cache_hit)+'/'+fmt(ti)+'</span></td>'+
        '<td class="num">'+fmt(m.requests)+'</td><td class="num">'+fmt(m.output)+'</td>'+
        '<td class="num">'+cost(m.cost_cny)+'</td>';
      tb.appendChild(tr);
    });
  }
  paint(bm);
  modelFixed.appendChild(T);

  // 分对话（滚动区域）
  var ch=mk('h3');ch.textContent='分对话';ch.style.cssText='margin:16px 0 6px;font-size:14px';sheet.appendChild(ch);
  var scrollable=mk('div');scrollable.className='scrollable';sheet.appendChild(scrollable);
  var sr=mk('div');sr.className='searchrow';
  sr.innerHTML='<input type="text" placeholder="搜索用户消息…" /><div class="filters"></div>';
  var input=sr.querySelector('input');
  var fl=sr.querySelector('.filters');
  var models=buildModels(day);
  fl.innerHTML='<button class="chip on" data-m="">全部</button>'+models.map(function(m){
    return '<button class="chip" data-m="'+esc(m.model)+'">'+esc(shortModel(m.model))+'</button>'}).join('');
  scrollable.appendChild(sr);

  var list=mk('div');scrollable.appendChild(list);
  var byTurn=(day.total.by_turn||[]).slice();
  var q='',model='';
  function visible(t){
    var lab=String(t.label||'').toLowerCase();
    if(q&&lab.indexOf(q)<0)return false;
    if(model&&t.model!==model)return false;
    return true;
  }

  function render(){
    list.innerHTML='';
    var shown=byTurn.filter(visible);
    if(!shown.length){var e=mk('div');e.className='empty';e.textContent='无匹配对话';list.appendChild(e);return}
    shown.sort(function(a,b){return (Number(b.first_ts)||0)-(Number(a.first_ts)||0)});
    shown.forEach(function(t){
      var st=Number(t.cache_hit)||0,sm=Number(t.cache_miss)||0,ti=st+sm;
      var det=mk('details');det.className='turn';
      var sum=mk('summary');
      sum.innerHTML='<span class="t">'+esc(t.label||'未命名消息')+'</span>'+
        '<span class="r"><span class="m">'+esc(shortModel(t.model))+'</span><span>'+pct(t.hit_rate)+'</span>'+
        '<span>'+esc(t.requests)+' req</span><span>'+cost(t.cost_cny)+'</span></span>';
      det.appendChild(sum);
      var inner=mk('div');inner.className='inner';
      var TT=mk('table');TT.className='tbl';
      TT.innerHTML='<thead><tr><th>时间</th><th>模型</th><th>命中率</th><th>命中/输入</th><th class="num">请求</th>'+
        '<th class="num">输出</th><th class="num">成本</th><th class="num">Prompt</th></tr></thead><tbody></tbody>';
      var tbb=TT.querySelector('tbody');
      function row(ts,model2,hitc,misc,req,out,co,pr,faint){
        var tr=mk('tr');if(faint)tr.setAttribute('style','opacity:.72');
        var hv=hitc+misc;
        tr.innerHTML='<td>'+esc(ts)+'</td><td>'+esc(model2)+'</td><td>'+pct(hv?hitc/hv:0,1)+'</td>'+
          '<td><span class="tag">'+fmt(hitc)+'/'+fmt(hv)+'</span></td>'+
          '<td class="num">'+req+'</td><td class="num">'+fmt(out)+'</td><td class="num">'+cost(co)+'</td>'+
          '<td class="num">'+fmt(pr)+'</td>';
        return tr;
      }
      var ts0=new Date(Number(t.first_ts)*1000).toTimeString().slice(0,8);
      tbb.appendChild(row(ts0,t.model,st,sm,t.requests,t.output,t.cost_cny,(t.prompt!=null?t.prompt:ti),false));
      (t.events||[]).forEach(function(e){
        var eh=Number(e.cache_hit)||0,em=Number(e.cache_miss)||0;
        tbb.appendChild(row(new Date(Number(e.ts)*1000).toTimeString().slice(0,8),e.model,eh,em,1,e.output,e.cost_cny,e.prompt_tokens,true));
      });
      inner.appendChild(TT);
      det.appendChild(inner);
      list.appendChild(det);
    });
  }
  input.addEventListener('input',function(){q=input.value.trim().toLowerCase();render()});
  fl.querySelectorAll('.chip').forEach(function(ch){
    ch.addEventListener('click',function(){
      model=ch.getAttribute('data-m')||'';
      fl.querySelectorAll('.chip').forEach(function(c){c.className=c===ch?'chip on':'chip'});
      render();});
  });
  render();
  m.appendChild(sheet);
  document.body.appendChild(m);
}

function toggleTheme(){
  var cur=document.documentElement.getAttribute('data-theme');
  var next=cur==='dark'?'light':'dark';
  document.documentElement.setAttribute('data-theme',next);
  try{localStorage.setItem('a3-theme',next)}catch(e){}
  renderAll();
}

function renderAll(){
  root.innerHTML='';
  var day=null;
  DAYS.forEach(function(d){if(d.day===state.day)day=d});
  if(!day)day=DAYS[DAYS.length-1];
  if(!day){var d=mk('div');d.textContent='暂无数据';root.appendChild(d);return}
  if(!state.day)state.day=day.day;
  root.appendChild(renderSidebar(day));
  root.appendChild(renderMain(day));
}

document.addEventListener('DOMContentLoaded',function(){
  root=document.getElementById('app');
  if(!root)return;
  // 初始主题：优先 localStorage，其次跟随系统偏好，默认浅色
  var saved=null;
  try{saved=localStorage.getItem('a3-theme')}catch(e){}
  var pref=window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';
  document.documentElement.setAttribute('data-theme',saved||pref);
  state.day=null;state.models=[];
  renderAll();
});
})();


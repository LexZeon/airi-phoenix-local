'use strict';
const $=selector=>document.querySelector(selector);
const escapeHtml=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const modules=[{id:'chat',name:'聊天',icon:'◔',note:'想聊什么，由她来回应。'},{id:'vision',name:'看屏幕',icon:'◉',note:'让她理解屏幕上的画面。'},{id:'asr',name:'听你说话',icon:'≋',note:'把你说的话变成文字。'},{id:'tts',name:'角色声音',icon:'♫',note:'选一个喜欢的声音和语气。'}];
const presets={gentle:{chat:'qwen9',vision:'vision9',asr:'sensevoice',tts:'qwen-soft'},quick:{chat:'qwen9',vision:'vision9',asr:'sensevoice',tts:'melo'},focus:{chat:'qwen27',vision:'vision9',asr:'sensevoice',tts:'qwen-focused'}};
let catalog={items:[]},draft,applied,preferences,status={services:[]},csrf='',busy=false,toastTimer,audio;
const clone=value=>JSON.parse(JSON.stringify(value));
const service=id=>status.services.find(item=>item.id===id);
const selected=module=>catalog.items.find(item=>item.id===draft?.selections[module]);
const friendly=module=>selected(module)?.name||(draft?.selections[module]==='ollama'?'本机 Ollama':draft?.custom?.[module]?.model||'其他本机服务');
const giB=value=>(value/1024**3).toFixed(1);
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,5500);}
async function api(path,body){const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Control-CSRF':csrf},body:JSON.stringify(body)}:{});const result=await response.json();if(!response.ok)throw Error(result.error||'操作没有完成。');return result;}
function signature(profile){return JSON.stringify({selections:profile.selections,custom:Object.fromEntries(Object.entries(profile.custom||{}).filter(([key])=>['custom','ollama'].includes(profile.selections[key])).map(([key,item])=>[key,{baseUrl:item.baseUrl,model:item.model,voice:item.voice||''}]))});}
function selectionChanged(){renderProfileHighlight();renderSummary();renderResources();}
function renderProfileHighlight(){for(const button of document.querySelectorAll('[data-preset]'))button.classList.toggle('active',JSON.stringify(draft.selections)===JSON.stringify(presets[button.dataset.preset]));}
function renderSummary(){
 const changed=signature(draft)!==signature(applied);
 $('#selection-state').textContent=changed?'选择好了？应用到 AIRI 吧。':'当前选择已写入 AIRI 设置';
 $('#selection-summary').textContent=modules.map(module=>friendly(module.id)).join(' · ');
 const runtime=service('airi'),pending=runtime?.online&&runtime.revision!==status.configuredRevision;
 const state=$('#runtime-state');state.classList.toggle('pending',Boolean(pending));
 if(!status.checkedAt){state.textContent='正在检查 AIRI 运行状态…';return;}
 state.textContent=runtime?.online?(pending?'AIRI 正在运行 · 新设置等待重新启动':'AIRI 已运行 · 当前设置已加载'):'AIRI 尚未运行 · 可应用并启动';
 $('#apply-start').textContent=runtime?.online?'应用并重启 AIRI ↗':'应用并启动 AIRI ↗';
}
function stateFor(module){
 const choice=draft.selections[module];
 if(choice==='custom')return {online:false,text:'自填本机服务 · 应用前可检测连接'};
 if(choice==='ollama'){const running=service('ollama');return {online:Boolean(running?.online),text:running?.online?'Ollama 在线 · 能力取决于所选模型':'Ollama 尚未启动'};}
 const id=module==='chat'?(choice==='qwen27'?'workbench':'chat'):module==='vision'?'vision':choice.startsWith('qwen-')?'qwen-tts':'speech';
 const running=service(id);
 if(module==='chat'&&running?.online&&running.loadedChoice!==choice)return {online:false,text:'应用并启动时切换到 '+(choice==='qwen27'?'27B':'9B')};
 return {online:Boolean(running?.online),text:running?.online?'本机服务已就绪':selected(module)?.installed?'已安装 · 应用并启动时加载':'文件尚未就绪'};
}
function updateModuleStates(){for(const module of modules){const node=$('#'+module.id+' .module-state');if(node){const state=stateFor(module.id);node.textContent=state.text;node.classList.toggle('off',!state.online);}}}
function renderModules(){
 $('#module-grid').innerHTML=modules.map(module=>{
  const items=catalog.items.filter(item=>item.module===module.id);
  const choice=draft.selections[module.id];
  const options=items.map(item=>'<option value="'+item.id+'" '+(choice===item.id?'selected':'')+'>'+escapeHtml(item.name)+'</option>').join('');
  const extra=(module.id==='chat'||module.id==='vision'?'<option value="ollama" '+(choice==='ollama'?'selected':'')+'>本机 Ollama…</option>':'')+'<option value="custom" '+(choice==='custom'?'selected':'')+'>其他本机兼容服务…</option>';
  const item=selected(module.id);
  return '<article class="module-card" id="'+module.id+'"><div class="module-header"><h3>'+module.name+'</h3><span class="module-icon">'+module.icon+'</span></div><p>'+module.note+'</p><select aria-label="'+module.name+'方案" data-module="'+module.id+'">'+options+extra+'</select><div class="module-state"></div><div class="module-extra">'+(item?.sample?'<button class="sample-button" data-sample="'+escapeHtml(item.sample)+'">▷ 试听这个声音</button>':'')+(choice==='custom'||choice==='ollama'?'<button class="text-button" data-edit="'+module.id+'">编辑连接</button>':'')+'</div>'+(module.id==='tts'?'<div id="audio-slot"></div>':'')+'</article>';
 }).join('');
 for(const element of document.querySelectorAll('[data-module]'))element.addEventListener('change',()=>{
  const module=element.dataset.module,choice=element.value,previous=draft.selections[module];
  if(choice==='custom'||choice==='ollama'){element.value=previous;openAdvanced(module,choice);return;}
  draft.selections[module]=choice;renderModules();selectionChanged();
 });
 for(const element of document.querySelectorAll('[data-edit]'))element.addEventListener('click',()=>openAdvanced(element.dataset.edit,draft.selections[element.dataset.edit]));
 for(const button of document.querySelectorAll('[data-sample]'))button.addEventListener('click',async()=>{
  if(audio)audio.pause();
  audio=document.createElement('audio');audio.controls=true;audio.src=button.dataset.sample;audio.preload='auto';$('#audio-slot').replaceChildren(audio);
  try{await audio.play();toast('正在播放已在本机生成的声音样例。');}catch(error){toast('可点击播放器播放。'+error.message);}
 });
 updateModuleStates();
}
function renderResources(){
 const rows=modules.map(module=>{const item=selected(module.id);return '<tr><td>'+module.name+'<code>'+escapeHtml(friendly(module.id))+'</code></td><td>'+ (item?item.memory.ramGiB.join('–')+' GiB':'依服务而定')+'</td><td>'+(item?item.memory.gpuGiB[1]?item.memory.gpuGiB.join('–')+' GiB':'CPU，无需 GPU':'依服务而定')+'</td><td>'+(item?giB(item.asset.bytes)+' GiB':'原位接入')+'</td></tr>';}).join('');
 const evidence=selected('tts')?.evidence||[];
 $('#resources').innerHTML='<table class="resource-table"><thead><tr><th>当前方案</th><th>主机余量建议</th><th>GPU / 统一内存建议</th><th>主文件大小</th></tr></thead><tbody>'+rows+'</tbody></table><p class="detail-note">资源区间是加载余量建议，不是最低配置。推荐的9B聊天与看屏幕共用一个服务，表中资源不能重复相加；27B使用独立文字服务。Serena三种语气共用一份权重。UMA内存不可把RAM和GPU数字相加。</p>'+evidence.map(item=>'<div class="evidence"><strong>Serena 本机历史单样例</strong>音频 '+item.audioSeconds.toFixed(2)+' 秒 · 合成 '+item.generationSeconds.toFixed(2)+' 秒 · 耗时 / 音频时长 '+item.rtf.toFixed(2)+'<small>'+escapeHtml(item.testedAt)+' · '+escapeHtml(item.source)+'</small><small>'+escapeHtml(item.note)+'</small></div>').join('')+'<p class="detail-note">聊天、看屏幕与识别尚无可比的同题性能记录。这里不填虚构分数，也不把历史样例当作每次响应保证。</p>';
}
function renderStatus(){
 $('#services').innerHTML=status.services.filter(item=>!['ollama','workbench'].includes(item.id)).map(item=>'<div class="service"><i class="'+(item.online?'on':'')+'"></i><span>'+escapeHtml(item.label)+'</span><small>'+(item.online?'就绪':'未启动')+'</small></div>').join('');
 const h=status.hardware||{},total=h.gpuTotalMiB?h.gpuTotalMiB/1024:0,free=h.gpuFreeMiB?h.gpuFreeMiB/1024:0,used=h.gpuUsedMiB?h.gpuUsedMiB/1024:0;
 $('#hardware').innerHTML='<div class="hardware-heading"><span>✳</span><strong>'+escapeHtml(h.gpuName||catalog.hardware?.name||'本机硬件')+'</strong><small>'+(total?'当前实测':'等待实时计数')+'</small></div><div class="hardware-numbers"><div><span>物理内存</span><b>'+(h.physicalBytes?(h.physicalBytes/1024**3).toFixed(0):'—')+'<small> GiB</small></b></div><div><span>GPU 可分配总量</span><b>'+(total?total.toFixed(1):'—')+'<small> GiB</small></b></div><div><span>当前 GPU 空闲</span><b>'+(total?free.toFixed(1):'—')+'<small> GiB</small></b></div><div><span>GPU 负载</span><b>'+(h.gpuUtilization??'—')+'<small> %</small></b></div></div><progress max="100" value="'+(total?used/total*100:0)+'" aria-label="GPU内存使用比例"></progress><p>如使用 UMA，RAM 与 GPU 可能共享物理内存池，数字不能直接相加。Windows 可见 '+(h.windowsVisibleBytes?giB(h.windowsVisibleBytes)+' GiB':'读取中')+'。<small>'+escapeHtml(h.gpuSource||'GPU计数读取中')+' · '+escapeHtml(h.source||'')+'</small></p>';
 $('#last-check').textContent=status.checkedAt?'最近检查 '+new Date(status.checkedAt).toLocaleTimeString('zh-CN',{hour12:false}):'正在检查本机服务';
 if(draft){updateModuleStates();renderSummary();}
}
function openAdvanced(module='chat',adapter){
 $('#advanced-module').value=module;$('#advanced-adapter').value=adapter||(draft.selections[module]==='ollama'?'ollama':'custom');populateAdvanced();$('#advanced-dialog').showModal();
}
function populateAdvanced(){
 const module=$('#advanced-module').value,adapter=$('#advanced-adapter').value,item=draft.custom[module]||{};
 $('#voice-label').hidden=module!=='tts';$('#advanced-adapter').querySelector('option[value="ollama"]').disabled=!['chat','vision'].includes(module);
 if(!['chat','vision'].includes(module)&&adapter==='ollama')$('#advanced-adapter').value='custom';
 const ollama=$('#advanced-adapter').value==='ollama';
 $('#endpoint').value=ollama?'http://127.0.0.1:11434/v1/':item.baseUrl||'http://127.0.0.1:9931/v1/';$('#endpoint').disabled=ollama;
 $('#custom-model').value=item.model||'';$('#custom-voice').value=item.voice||'';$('#api-key').value='';
 const models=service('ollama')?.models||[];$('#local-models').innerHTML=(ollama?models:[]).map(model=>'<option value="'+escapeHtml(model)+'"></option>').join('');
 $('#endpoint-state').textContent=ollama?(service('ollama')?.online?'Ollama 已在线，可选已安装模型。':'Ollama 当前未启动；这里只接入已有模型。'):'仅允许回环地址。模型必须支持你选择的功能。';
}
function advancedConfig(){return {baseUrl:$('#endpoint').value.trim(),model:$('#custom-model').value.trim(),voice:$('#custom-voice').value.trim(),apiKey:$('#api-key').value};}
async function runOperation(kind){
 if(busy)return;busy=true;for(const id of ['remember','apply-only','apply-start'])$('#'+id).disabled=true;
 const box=$('#action-status');box.hidden=false;box.classList.remove('failed');box.textContent=kind==='remember'?'正在记住选择…':kind==='apply'?'正在写入 AIRI 设置…':'正在应用并启动 AIRI，窗口会重新打开…';
 try{
  const result=await api(kind==='remember'?'/api/preferences':kind==='apply'?'/api/apply':'/api/action',kind==='start'?{action:'apply-and-start',profile:draft}:{profile:draft});
  if(result.job){
   let job=result.job;
   while(job.status==='running'){box.textContent=job.message;await new Promise(resolve=>setTimeout(resolve,1500));job=await api('/api/jobs/'+job.id);}
   box.classList.toggle('failed',job.status!=='success');box.textContent=job.message;
   const log=document.createElement('a');log.href='/api/logs/'+job.id;log.target='_blank';log.rel='noopener';log.textContent='查看操作日志';box.append(log);
   if(job.status!=='success'){toast(job.message);await refreshStatus();return;}
   applied=clone(draft);toast(job.message);
  }else{
   box.textContent=result.message;toast(result.message);
   if(kind==='remember')preferences=result.preferences;
   else {applied=clone(draft);status.configuredRevision=result.revision;}
  }
  selectionChanged();await refreshStatus();
 }catch(error){box.classList.add('failed');box.textContent=error.message;toast(error.message);}
 finally{busy=false;for(const id of ['remember','apply-only','apply-start'])$('#'+id).disabled=false;}
}
async function refreshStatus(){try{status=await api('/api/status');renderStatus();}catch(error){$('#last-check').textContent='控制台连接中断，请重新打开快捷方式。';}}
for(const button of document.querySelectorAll('[data-preset]'))button.addEventListener('click',()=>{draft.selections=clone(presets[button.dataset.preset]);renderModules();selectionChanged();});
$('#remember').addEventListener('click',()=>runOperation('remember'));$('#apply-only').addEventListener('click',()=>runOperation('apply'));$('#apply-start').addEventListener('click',()=>runOperation('start'));
$('#advanced-open').addEventListener('click',()=>openAdvanced());$('#advanced-close').addEventListener('click',()=>$('#advanced-dialog').close());$('#advanced-module').addEventListener('change',populateAdvanced);$('#advanced-adapter').addEventListener('change',populateAdvanced);
$('#use-custom').addEventListener('click',()=>{const module=$('#advanced-module').value,item=advancedConfig();if(!item.model||!item.baseUrl){toast('请填写本机服务地址和模型名称。');return;}draft.custom[module]=item;draft.selections[module]=$('#advanced-adapter').value;$('#advanced-dialog').close();renderModules();selectionChanged();});
$('#check-endpoint').addEventListener('click',async()=>{const button=$('#check-endpoint');button.disabled=true;$('#endpoint-state').textContent='正在检测本机连接…';try{const config=advancedConfig(),result=await api('/api/check-endpoint',{module:$('#advanced-module').value,baseUrl:config.baseUrl,apiKey:config.apiKey});$('#endpoint-state').textContent=result.message+' '+result.models.join('、');$('#local-models').innerHTML=result.models.map(model=>'<option value="'+escapeHtml(model)+'"></option>').join('');if(!config.model&&result.models.length===1)$('#custom-model').value=result.models[0];}catch(error){$('#endpoint-state').textContent=error.message;}finally{button.disabled=false;}});
$('#refresh').addEventListener('click',()=>{refreshStatus();toast('已读取最近一次服务状态。');});
(async()=>{try{const data=await api('/api/bootstrap');csrf=data.csrfToken;catalog=data.catalog;preferences=data.preferences;applied=data.applied;draft=clone(preferences.profile||applied);status=data.status;renderModules();selectionChanged();renderStatus();setInterval(refreshStatus,8000);}catch(error){$('#module-grid').textContent='未能读取本机设置：'+error.message;}})();

'use strict';
(()=>{
 const field=id=>document.getElementById(id);
 let csrf='',account,job,sequence=0,pollTimer,checking=false;
 const running=()=>job&&!['success','failed','stopped'].includes(job.status);
 const normalizedPath=value=>String(value||'').replace(/\\/g,'/').replace(/\/+$/,'').toLocaleLowerCase();
 function writeScope(){
  const roots=account?.relatedWriteRoots||[],entry=account?.relatedWriteRootsApplyTo;
  field('codex-scope-note').textContent=field('codex-mode').value==='read-only'?'当前只读：查看文件和给出建议。':roots.length&&normalizedPath(field('codex-workspace').value)===normalizedPath(entry)?'允许修改此 AIRI 项目及现有安装配置：'+roots.join('、'):'允许修改所选工作目录；其他目录未额外授权。';
 }
 async function request(path,body){
  const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Control-CSRF':csrf},body:JSON.stringify(body)}:{});
  const result=await response.json();if(!response.ok)throw Error(result.error||'Codex 操作没有完成。');return result;
 }
 function controls(){
  const active=Boolean(running());field('codex-run').disabled=active||!csrf||!account?.loggedIn;
  field('codex-stop').disabled=!active||job.status==='stopping';
  for(const id of ['codex-task','codex-workspace','codex-mode','codex-target'])field(id).disabled=active;
  writeScope();
 }
 function renderJob(value){
  job=value;controls();
  field('codex-job-state').textContent=value.message+' · '+Math.round(value.elapsedSeconds||0)+' 秒';
  const fresh=(value.events||[]).filter(event=>event.sequence>sequence);sequence=Math.max(sequence,value.sequence||0);
  const progress=fresh.filter(event=>event.type==='progress').map(event=>event.text);
  if(progress.length)field('codex-progress').textContent=progress.slice(-3).join(' ');
  field('codex-output').textContent=value.output||(['failed','stopped'].includes(value.status)?value.message:'Codex 正在处理，请稍候…');
  field('codex-output').classList.toggle('failed',value.status==='failed');
  if(running())pollTimer=setTimeout(pollJob,1000);
 }
 async function pollJob(){
  if(!job)return;
  try{renderJob(await request('/api/codex/jobs/'+encodeURIComponent(job.id)));}
  catch(error){field('codex-job-state').textContent='读取结果中断：'+error.message;field('codex-stop').disabled=true;}
 }
 async function check(){
  if(checking)return;checking=true;field('codex-refresh').disabled=true;
  try{
   account=await request('/api/codex/status');field('codex-state').textContent=account.message+(account.version?' · Codex '+account.version:'');
   if(!field('codex-workspace').value)field('codex-workspace').value=account.defaultWorkspace||'';
   if(account.targetThreadConfigured&&!field('codex-target').querySelector('[value="existing"]')){
    const option=document.createElement('option');option.value='existing';option.textContent='继续已有聊天'+(account.targetThreadLabel?' · '+account.targetThreadLabel:'');
    field('codex-target').prepend(option);field('codex-target').value='existing';
   }
   if(account.activeJobId&&!running()){sequence=0;job={id:account.activeJobId,status:'running'};await pollJob();}
   controls();
  }catch(error){field('codex-state').textContent='检测未完成：'+error.message;}
  finally{checking=false;field('codex-refresh').disabled=false;}
 }
 field('codex-form').addEventListener('submit',async event=>{
  event.preventDefault();if(running()||!csrf)return;
  field('codex-run').disabled=true;field('codex-job-state').textContent='正在提交你填写的任务…';
  try{
   const result=await request('/api/codex/start',{task:field('codex-task').value,workspace:field('codex-workspace').value,mode:field('codex-mode').value,target:field('codex-target').value});
   clearTimeout(pollTimer);sequence=0;field('codex-progress').textContent='';renderJob(result.job);
  }catch(error){field('codex-job-state').textContent=error.message;controls();}
 });
 field('codex-stop').addEventListener('click',async()=>{
  if(!running())return;field('codex-stop').disabled=true;
  try{const result=await request('/api/codex/stop',{jobId:job.id});clearTimeout(pollTimer);renderJob(result.job);}
  catch(error){field('codex-job-state').textContent=error.message;controls();}
 });
 field('codex-refresh').addEventListener('click',check);
 field('codex-mode').addEventListener('change',writeScope);field('codex-workspace').addEventListener('input',writeScope);
 window.addEventListener('airi-control-ready',event=>{csrf=event.detail.csrfToken;controls();});
 if(window.airiControlSession?.csrfToken)csrf=window.airiControlSession.csrfToken;
 check();
})();

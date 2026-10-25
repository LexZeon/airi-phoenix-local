"""Personal AIRI configuration console. Loopback only; fixed launcher arguments."""
from __future__ import annotations
import concurrent.futures
import csv
import datetime
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from profiles import (BASE, ROOT, DATA_ROOT, CONTROL_PORT, SETTINGS, PREFERENCES, REQUESTS, LOCK, read_json, atomic_json,
                      current_profile, public_profile, merge_input, apply_profile, local_url)
from airi_catalog import catalog, WORKBENCH, QWEN, SPEECH, SAPI

PORT=CONTROL_PORT
APP_ID='airi-local-control-center'
ORIGIN=f'http://127.0.0.1:{PORT}'
TOKEN=secrets.token_urlsafe(32)
STATE=DATA_ROOT; LOGS=DATA_ROOT/'logs'
for directory in (STATE,LOGS,REQUESTS): directory.mkdir(parents=True,exist_ok=True)
PS=Path(os.environ.get('WINDIR','C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
JOBS={}; JOB_LOCK=threading.RLock()
STATUS={'checkedAt':None,'services':[]}
SERVICES=[('chat','聊天',9941,'/v1/models'),('vision','看屏幕',9941,'/v1/models'),
          ('speech','听说服务',9942,'/v1/models'),('qwen-tts','Serena 声音',9945,'/health'),('sapi','系统声音',9947,'/health'),
          ('ollama','Ollama 兼容方案',11434,'/api/tags'),('workbench','独立文字备选',9931,'/v1/models'),('airi','AIRI',9943,'/health')]
SAMPLES={voice:QWEN/'samples'/f'{voice}.wav' for voice in ('phoenix-soft','phoenix-drowsy','phoenix-focused')}
SAMPLES['melo']=SPEECH/'verification/chinese-offline.wav'
SAMPLES['huihui']=SAPI/'samples/huihui-soft.wav'

def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): raise ValueError('本机模型地址返回重定向，已拒绝跟随。')
HTTP=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
def request_json(url,timeout=2,api_key=None):
    headers={'Accept':'application/json'}
    if api_key: headers['Authorization']='Bearer '+api_key
    with HTTP.open(urllib.request.Request(url,headers=headers),timeout=timeout) as response:
        payload=response.read(1024*1024+1)
        if len(payload)>1024*1024: raise ValueError('本机服务响应过大。')
        return json.loads(payload)

def probe(item):
    id_,label,port,route=item
    result={'id':id_,'label':label,'port':port,'url':f'http://127.0.0.1:{port}','online':False}
    try:
        data=request_json(result['url']+route)
        result['online']=bool(isinstance(data,dict) and (isinstance(data.get('data'),list) or isinstance(data.get('models'),list) or data.get('ready') is True))
        if id_ in ('chat','vision','workbench'):
            result['models']=[m.get('id') for m in data.get('data',[]) if isinstance(m,dict)]
            count=next(iter(data.get('data',[])),{}).get('meta',{}).get('n_params',0)
            result['loadedChoice']='qwen27' if count>20_000_000_000 else 'qwen9' if count>5_000_000_000 else None
        if id_=='ollama':result['models']=[m.get('name') for m in data.get('models',[]) if isinstance(m,dict)]
        if id_=='airi': result.update(revision=data.get('revision'),character=data.get('character',{}),profile=data.get('profile',{}))
        if id_=='qwen-tts':result['metrics']=data.get('metrics',{})
    except Exception as error:result['error']=type(error).__name__
    return result

def hardware():
    result={'physicalBytes':137438953472,'source':'已核实本机128GiB安装记录'}
    try:
        command='@{physical=(Get-CimInstance Win32_PhysicalMemory | Measure-Object -Property Capacity -Sum).Sum;visible=(Get-CimInstance Win32_OperatingSystem).TotalVisibleMemorySize;free=(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory} | ConvertTo-Json -Compress'
        data=json.loads(subprocess.check_output([str(PS),'-NoProfile','-Command',command],creationflags=subprocess.CREATE_NO_WINDOW,timeout=8))
        result.update(physicalBytes=int(data['physical']),windowsVisibleBytes=int(data['visible'])*1024,windowsFreeBytes=int(data['free'])*1024,source='CIM当前实测')
    except Exception:pass
    try:
        exe=Path(os.environ.get('WINDIR','C:/Windows'))/'System32/nvidia-smi.exe'
        data=subprocess.check_output([str(exe),'--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu','--format=csv,noheader,nounits'],creationflags=subprocess.CREATE_NO_WINDOW,timeout=3).decode()
        for fields in csv.reader(data.splitlines()):
            if len(fields)==5 and fields[1].strip().isdigit():
                result.update(gpuName=fields[0].strip(),gpuTotalMiB=int(fields[1]),gpuUsedMiB=int(fields[2]),gpuFreeMiB=int(fields[3]),gpuUtilization=int(fields[4]),gpuSource='nvidia-smi 当前实测');break
    except Exception:result['gpuSource']='实时GPU计数暂不可用'
    return result

def refresh_status():
    global STATUS
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as pool:services=list(pool.map(probe,SERVICES))
    new={'checkedAt':now(),'services':services,'hardware':hardware(),'configuredRevision':read_json(SETTINGS,{}).get('revision')}
    with LOCK:STATUS=new
    return new
def status_loop():
    while True:
        try:refresh_status()
        except Exception:pass
        time.sleep(8)

def preferences():
    value=read_json(PREFERENCES,{})
    return {'profile':public_profile(value.get('profile',current_profile())),'updatedAt':value.get('updatedAt')}
def ensure_idle():
    with JOB_LOCK:
        if any(j['status']=='running' for j in JOBS.values()):raise ValueError('已有操作正在进行，请等它完成后再应用。')
def save_preferences(profile):
    with LOCK:
        value=read_json(PREFERENCES,{})
        value.update(profile=profile,updatedAt=now())
        atomic_json(PREFERENCES,value)
    return preferences()

def launch_job(action,profile=None,service_id=None):
    with JOB_LOCK:return _launch_job(action,profile,service_id)

def _launch_job(action,profile=None,service_id=None):
    ensure_idle()
    job_id=secrets.token_hex(8)
    if action=='apply-and-start':
        profile=merge_input(profile)
        file=REQUESTS/('selection-'+secrets.token_hex(16)+'.json')
        atomic_json(file,profile)
        script=ROOT.parent/'launchers/airi-select-profile.ps1';argv=['-ProfileFile',str(file),'-StartAiri'];timeout=600
    elif action=='start-service':
        mapping={
          'chat':(BASE/'launchers/airi-model-start.ps1',['-NoPause']),
          'vision':(BASE/'launchers/airi-model-start.ps1',['-NoPause']),
          'speech':(BASE/'launchers/airi-speech-start.ps1',[]),
          'qwen-tts':(QWEN/'start.ps1',[]),
          'ollama':(WORKBENCH/'Start-Ollama.ps1',[])}
        if service_id not in mapping:raise ValueError('不支持这个启动操作。')
        script,argv=mapping[service_id];timeout=300
    else:raise ValueError('操作无效，没有执行命令。')
    if not script.is_file():raise ValueError('现有启动器未找到，没有下载或安装。')
    job={'id':job_id,'action':action,'service':service_id,'status':'running','startedAt':now(),
         'message':'正在应用设置并启动服务；AIRI 会重新打开。' if action=='apply-and-start' else '正在启动已有本机服务…'}
    with JOB_LOCK:JOBS[job_id]=job
    def run():
        try:
            with (LOGS/f'{job_id}.log').open('wb') as log:
                proc=subprocess.Popen([str(PS),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),*argv],cwd=script.parent,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
                try:code=proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    with JOB_LOCK:job['message']='启动器仍在运行，加载时间较长；正在继续等待，尚未报告成功。'
                    code=proc.wait()
            if code:raise ValueError('已有启动器返回失败，请查看操作日志；设置可能已保存，未报告启动成功。')
            if action=='apply-and-start':
                save_preferences(profile)
                configured=read_json(SETTINGS,{})
                ready=False;deadline=time.monotonic()+90
                while time.monotonic()<deadline:
                    runtime=probe(next(s for s in SERVICES if s[0]=='airi'))
                    ready=bool(runtime['online'] and runtime.get('revision')==configured.get('revision') and runtime.get('profile',{}).get('applied'))
                    if configured.get('character',{}).get('enabled'):ready=ready and runtime.get('character',{}).get('phase')=='active'
                    if ready:break
                    with JOB_LOCK:job['message']='AIRI 已打开，正在等待新设置和角色完成加载…'
                    time.sleep(1)
                if not ready:raise ValueError('设置已保存，但 AIRI 尚未确认新设置和角色加载完成。请查看操作日志。')
                job['revision']=configured['revision']
            elif not probe(next(s for s in SERVICES if s[0]==service_id))['online']:raise ValueError('启动器结束，但健康检查尚未通过。')
            with JOB_LOCK:job.update(status='success',finishedAt=now(),message='AIRI 已使用新设置重新启动。' if action=='apply-and-start' else '本机服务已就绪。')
        except Exception as error:
            with JOB_LOCK:job.update(status='failed',finishedAt=now(),message=str(error))
        refresh_status()
    threading.Thread(target=run,daemon=True).start()
    return job

class Handler(BaseHTTPRequestHandler):
    server_version='AIRIControl/2.0'
    def log_message(self,fmt,*args):
        with (LOGS/'http.log').open('a',encoding='utf-8') as stream:stream.write(f'{now()} {self.client_address[0]} {fmt%args}\n')
    def allowed(self,write=False):
        if self.client_address[0] not in ('127.0.0.1','::1'):return False
        if self.headers.get('Host') not in (f'127.0.0.1:{PORT}',f'localhost:{PORT}'):return False
        origin=self.headers.get('Origin')
        if origin and origin!=ORIGIN:return False
        if self.headers.get('Sec-Fetch-Site')=='cross-site':return False
        if write:return origin==ORIGIN and secrets.compare_digest(self.headers.get('X-Control-CSRF','').encode(),TOKEN.encode())
        return True
    def respond(self,status,value,mime='application/json; charset=utf-8'):
        data=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status)
        headers=[('Content-Type',mime),('Content-Length',str(len(data))),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('Referrer-Policy','no-referrer'),('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")]
        for key,value in headers:self.send_header(key,value)
        self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if not self.allowed():return self.respond(403,{'error':'仅允许本机同源访问。'})
        route=urllib.parse.urlsplit(self.path).path
        if route=='/health':return self.respond(200,{'app':APP_ID,'pid':os.getpid(),'ready':True,'version':2})
        if route=='/api/bootstrap':
            with LOCK:return self.respond(200,{'app':APP_ID,'csrfToken':TOKEN,'catalog':catalog(),'preferences':preferences(),'applied':public_profile(current_profile()),'status':STATUS})
        if route=='/api/status':return self.respond(200,STATUS)
        if route=='/api/catalog':return self.respond(200,catalog())
        if route.startswith('/api/jobs/'):
            id_=route.rsplit('/',1)[-1];job=JOBS.get(id_);return self.respond(200 if job else 404,job or {'error':'未知操作。'})
        if route.startswith('/api/logs/'):
            id_=route.rsplit('/',1)[-1]
            if id_ not in JOBS:return self.respond(404,{'error':'未知日志。'})
            file=LOGS/f'{id_}.log';data=file.read_bytes()[-24000:] if file.exists() else '尚无日志'.encode()
            return self.respond(200,data,'text/plain; charset=utf-8')
        if route.startswith('/api/samples/'):
            file=SAMPLES.get(route.rsplit('/',1)[-1])
            if not file or not file.is_file():return self.respond(404,{'error':'试听文件尚不存在。'})
            return self.respond(200,file.read_bytes(),'audio/wav')
        static={'/':('index.html','text/html'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css'),'/favicon.svg':('favicon.svg','image/svg+xml')}
        if route in static:
            name,mime=static[route];return self.respond(200,(ROOT/'web'/name).read_bytes(),mime+'; charset=utf-8')
        return self.respond(404,{'error':'Not found'})
    def do_POST(self):
        if not self.allowed(True):return self.respond(403,{'error':'Origin 或 CSRF 校验失败，没有执行操作。'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length<2 or length>16384 or self.headers.get_content_type()!='application/json':raise ValueError('需要小于16KB的JSON请求。')
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict):raise ValueError('请求无效。')
            route=urllib.parse.urlsplit(self.path).path
            if route=='/api/preferences':
                profile=merge_input(data.get('profile'));saved=save_preferences(profile)
                return self.respond(200,{'ok':True,'preferences':saved,'message':'选择已记住。尚未改动 AIRI 设置。'})
            if route=='/api/apply':
                with JOB_LOCK:
                    ensure_idle();profile=merge_input(data.get('profile'))
                    result=apply_profile(profile);save_preferences(profile)
                    with LOCK:STATUS['configuredRevision']=result['revision']
                atomic_json(STATE/'last-apply.json',result)
                return self.respond(200,result)
            if route=='/api/check-endpoint':
                module=data.get('module')
                if module not in ('chat','vision','asr','tts'):raise ValueError('模块无效。')
                url=local_url(data.get('baseUrl'))
                key=data.get('apiKey') or None
                if key is not None and (not isinstance(key,str) or len(key)>512 or any(ord(c)<32 for c in key)):raise ValueError('密钥格式无效。')
                response=request_json(url+'models',timeout=4,api_key=key)
                if not isinstance(response,dict):raise ValueError('这个地址未返回兼容的模型列表。')
                models=[m.get('id') for m in response.get('data',[]) if isinstance(m,dict)]
                return self.respond(200,{'ok':True,'models':models,'message':'已连接模型列表。具体聊天/图像/音频能力仍取决于这个服务。'})
            if route=='/api/action':
                job=launch_job(data.get('action'),data.get('profile'),data.get('service'))
                return self.respond(202,{'ok':True,'job':job})
            if route=='/api/shutdown':
                self.respond(200,{'ok':True});threading.Thread(target=self.server.shutdown,daemon=True).start();return
            return self.respond(404,{'error':'未知操作。'})
        except (ValueError,TypeError,KeyError,OSError,urllib.error.URLError) as error:return self.respond(400,{'error':str(error)})

if __name__=='__main__':
    httpd=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    atomic_json(STATE/'server.json',{'app':APP_ID,'pid':os.getpid(),'script':str(Path(__file__).resolve()),'startedAt':now(),'port':PORT})
    threading.Thread(target=status_loop,daemon=True).start()
    try:httpd.serve_forever(poll_interval=.25)
    finally:httpd.server_close()

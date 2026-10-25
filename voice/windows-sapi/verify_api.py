# SPDX-License-Identifier: MIT
"""Explicit fixed-synthetic test of this optional adapter. Never plays audio."""
import argparse
import concurrent.futures
import hashlib
import http.client
import io
import json
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request
import wave
from token_store import ensure_token

ROOT = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:9947"
SAMPLE = "先休息一下吧。我在这里，慢慢来就好。"
PS = str(Path(__import__('os').environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true',required=True)
    parser.add_argument('--lifecycle',action='store_true')
    args=parser.parse_args()
    token=ensure_token()
    checks=[]; timings=[]
    report={'syntheticOnly':True,'audioPlayed':False,'otherServicesChanged':False,'checks':checks,'sampleRuns':timings}

    def check(name,value,**details):
        checks.append({'name':name,'pass':bool(value),**details})
        if not value: raise AssertionError(name)

    def request(path='/health',data=None,headers=None,auth=True,method=None):
        body=None if data is None else json.dumps(data,ensure_ascii=False).encode('utf-8')
        hdr={'Content-Type':'application/json'}
        if auth: hdr['Authorization']='Bearer '+token
        hdr.update(headers or {})
        began=time.perf_counter()
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE+path,data=body,headers=hdr,method=method),timeout=40) as res:
                return res.status,res.read(),dict(res.headers),time.perf_counter()-began
        except urllib.error.HTTPError as exc:
            return exc.code,exc.read(),dict(exc.headers),time.perf_counter()-began

    def health():return json.loads(request()[1])
    def wait_for(predicate,seconds=10):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            result=health()
            if predicate(result):return result
            time.sleep(.03)
        raise AssertionError('health condition timeout')
    def valid(data=None):return {'model':'windows-sapi-local','voice':'huihui','input':SAMPLE,'response_format':'wav',**(data or {})}
    def wave_info(raw):
        with wave.open(io.BytesIO(raw),'rb') as reader:
            n=reader.getnframes();frames=reader.readframes(n)
            return {'sampleRate':reader.getframerate(),'channels':reader.getnchannels(),'bits':reader.getsampwidth()*8,
                    'frames':n,'audioSeconds':n/reader.getframerate(),'dataBytes':len(frames),
                    'sha256':hashlib.sha256(raw).hexdigest()}
    def ps(script):
        # PowerShell Start-Process can pass an inherited pipe handle to its
        # detached child. DEVNULL avoids waiting for that child's EOF.
        completed=subprocess.run([PS,'-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/script)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=45)
        return completed.returncode

    initial=health();check('ready-and-exact-service',initial['ready'] and initial['service']=='airi-windows-sapi')
    report['initialPid']=initial['pid']
    for route,key,expected in [('/v1/models','data','windows-sapi-local'),('/v1/audio/voices','voices','huihui')]:
        status,raw,_,_=request(route,auth=False)
        check(route+'-catalog',status==200 and json.loads(raw)[key][0]['id']==expected)
    for number in range(3):
        status,raw,headers,elapsed=request('/v1/audio/speech',valid())
        meta=wave_info(raw) if status==200 else {}
        check('sample-'+str(number+1)+'-valid-WAV',status==200 and meta['sampleRate']==24000 and meta['channels']==1 and meta['bits']==16 and meta['dataBytes']==meta['frames']*2)
        timings.append({'wallSeconds':elapsed,**meta,'generationSeconds':float(headers['X-AIRI-Generation-Seconds']),
                        'queueSeconds':float(headers['X-AIRI-Queue-Seconds']),'totalSeconds':float(headers['X-AIRI-Total-Seconds'])})
        if number==0:
            samples=ROOT/'samples';samples.mkdir(exist_ok=True)
            (samples/'huihui-soft.wav').write_bytes(raw)  # Only this fixed, declared synthetic sample is saved.
    check('repeat-audio-is-deterministic',len({item['sha256'] for item in timings})==1)
    cases=[('missing-auth',valid(),{},False,401,'AUTH_REQUIRED'),
           ('host-denied',valid(),{'Host':'evil.invalid:9947'},True,403,'HOST_DENIED'),
           ('origin-denied',valid(),{'Origin':'https://evil.invalid'},True,403,'ORIGIN_DENIED'),
           ('model-denied',valid({'model':'other'}),{},True,400,'UNKNOWN_MODEL'),
           ('voice-denied',valid({'voice':'Serena'}),{},True,400,'UNKNOWN_VOICE'),
           ('format-denied',valid({'response_format':'mp3'}),{},True,400,'WAV_ONLY'),
           ('style-not-pretended',valid({'instructions':'soft'}),{},True,400,'UNSUPPORTED_OPTION'),
           ('empty-text',valid({'input':''}),{},True,400,'INVALID_INPUT'),
           ('oversized-text',valid({'input':'本'*2001}),{},True,400,'INVALID_INPUT'),
           ('bad-speed',valid({'speed':True}),{},True,400,'INVALID_SPEED')]
    for name,data,headers,auth,expected_status,code in cases:
        status,raw,_,_=request('/v1/audio/speech',data,headers,auth)
        check(name,status==expected_status and json.loads(raw)['error']['code']==code)
    status,_,headers,_=request('/v1/audio/speech',headers={'Origin':'null','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'authorization,content-type'},method='OPTIONS',auth=False)
    check('file-origin-preflight',status==204 and headers.get('Access-Control-Allow-Origin')=='null')
    status,_,headers,_=request(headers={'Origin':'https://evil.invalid'},auth=False)
    check('bad-origin-no-CORS',status==403 and 'Access-Control-Allow-Origin' not in headers)
    # A duplicate Host must not bypass the exact loopback check.
    connection=http.client.HTTPConnection('127.0.0.1',9947,timeout=3)
    connection.putrequest('GET','/health',skip_host=True);connection.putheader('Host','127.0.0.1:9947');connection.putheader('Host','evil.invalid');connection.endheaders()
    response=connection.getresponse();check('duplicate-host-denied',response.status==403);response.read();connection.close()

    # Keep one real long synthetic synthesis busy while seven requests queue.
    sockets=[]
    def raw_request(data):
        body=json.dumps(data,ensure_ascii=False).encode('utf-8')
        sock=socket.create_connection(('127.0.0.1',9947),timeout=5)
        head=('POST /v1/audio/speech HTTP/1.0\r\nHost: 127.0.0.1:9947\r\nContent-Type: application/json\r\nAuthorization: Bearer '+token+'\r\nContent-Length: '+str(len(body))+'\r\n\r\n').encode('ascii')
        sock.sendall(head+body);sockets.append(sock)
    before=health();old_worker=before['worker_pid']
    try:
        raw_request(valid({'input':SAMPLE*80,'speed':.25}))
        wait_for(lambda h:h['requests_active']==1)
        for _ in range(7):raw_request(valid())
        queued=wait_for(lambda h:h['requests_queued']==7,seconds=3)
        status,raw,_,_=request('/v1/audio/speech',valid())
        check('bounded-queue-rejects-ninth',status==429 and json.loads(raw)['error']['code']=='VOICE_BUSY',queued=queued['requests_queued'],active=queued['requests_active'])
    finally:
        for sock in sockets:
            try:sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            sock.close()
    after=wait_for(lambda h:h['ready'] and h['requests_active']==0 and h['requests_queued']==0 and h['metrics']['tts_cancelled']>=before['metrics']['tts_cancelled']+8)
    check('disconnect-cancels-active-and-queued',after['metrics']['tts_cancelled']>=before['metrics']['tts_cancelled']+8)
    check('active-cancellation-replaces-owned-worker',after['worker_pid']!=old_worker)
    status,raw,_,_=request('/v1/audio/speech',valid());check('service-recovers-after-cancellation',status==200 and wave_info(raw)['audioSeconds']>0)

    # Exercise a verified worker crash; every stop target is validated by the production identity checker.
    script=". '"+str(ROOT/'common.ps1').replace("'","''")+"'; $s=Get-SapiSpec; $r=Read-SapiState $s; $w=Read-SapiWorkerIdentity $s $r; if(-not $w){exit 2}; Stop-Process -Id $w.pid -Force"
    result=subprocess.run([PS,'-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-Command',script],capture_output=True,timeout=10)
    check('owned-worker-crash-injected',result.returncode==0)
    status,raw,_,_=request('/v1/audio/speech',valid())
    check('worker-crash-fixed-error',status==500 and json.loads(raw)['error']['code'] in {'WORKER_IO_FAILED','SYNTHESIS_FAILED'})
    wait_for(lambda h:h['ready'] and h['worker_pid']!=after['worker_pid'])
    status,raw,_,_=request('/v1/audio/speech',valid());check('worker-crash-recovery',status==200 and wave_info(raw)['audioSeconds']>0)

    if args.lifecycle:
        before=health();check('repeat-start-is-idempotent',ps('start.ps1')==0 and health()['pid']==before['pid'])
        state_path=ROOT/'state.json';original=state_path.read_bytes()
        try:
            state=json.loads(original);state['identity']['creationTimeUtcTicks']='0'
            temporary=state_path.with_suffix('.verify.tmp');temporary.write_text(json.dumps(state),encoding='utf-8');temporary.replace(state_path)
            check('stop-refuses-tampered-creation',ps('stop.ps1')!=0 and health()['pid']==before['pid'])
        finally:
            temporary=state_path.with_suffix('.verify.tmp');temporary.write_bytes(original);temporary.replace(state_path)
        check('owned-stop',ps('stop.ps1')==0)
        check('repeat-stop-safe',ps('stop.ps1')==0)
        listener=socket.socket();listener.bind(('127.0.0.1',9947));listener.listen(1)
        try:
            check('start-refuses-unowned-listener',ps('start.ps1')!=0)
            check('stop-refuses-unowned-listener',ps('stop.ps1')!=0)
            check('unowned-listener-preserved',listener.fileno()>=0)
        finally:listener.close()
        check('owned-restart',ps('start.ps1')==0)
        check('restart-ready-and-new-identity',health()['ready'] and health()['instance_id']!=before['instance_id'])
    final=health();report.update(status='PASS',finalPid=final['pid'],finalWorkerPid=final['worker_pid'],finalReady=final['ready'],
                                metrics=final['metrics'],sampleFile='samples/huihui-soft.wav',testCount=len(checks))
    (ROOT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))


if __name__=='__main__':main()

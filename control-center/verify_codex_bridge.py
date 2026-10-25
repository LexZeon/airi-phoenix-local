"""Offline subprocess/API regression checks. The fake CLI never connects to OpenAI."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from codex_bridge import CodexTaskBridge, local_directory, clean_codex_environment

FAKE = r'''
import json,sys,time,os
from pathlib import Path
a=sys.argv[1:]
if a==['--version']:print('codex-cli 0.164.0-test');raise SystemExit()
if a==['login','status']:print('Logged in using ChatGPT');raise SystemExit()
assert a[0]=='exec' and '--json' in a and '--sandbox' in a
assert not any('bypass' in x or x in ('--yolo','--approve-for-me','--model') for x in a)
task=sys.stdin.read()
print(json.dumps({'type':'turn.started'}),flush=True)
if task=='SLOW':time.sleep(60)
if task=='FAIL':
 print(json.dumps({'type':'turn.failed','error':{'message':'quota limit reached; synthetic-secret-marker'}}),flush=True);raise SystemExit(3)
print(json.dumps({'type':'item.started','item':{'type':'command_execution','command':'synthetic-secret-command'}}),flush=True)
if task.startswith('ARGS'):
 text=json.dumps({'sandbox':a[a.index('--sandbox')+1],'ephemeral':'--ephemeral' in a,'resume':'resume' in a,'cwdMatches':str(Path(a[a.index('-C')+1]).resolve())==str(Path.cwd().resolve())})
 if task=='ARGS_ROOTS':
  value=json.loads(text);value['addDirs']=[a[n+1] for n in range(len(a)-1) if a[n]=='--add-dir'];text=json.dumps(value)
else:text=task
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':text}}),flush=True)
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}),flush=True)
'''

def finished(bridge, job_id, timeout=8):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        job=bridge.snapshot(job_id)
        if job['status'] in ('success','failed','stopped') and job['finishedAt']:
            return job
        time.sleep(.03)
    raise AssertionError('Synthetic child did not finish')


class BridgeChecks(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='airi-codex-test-')
        self.root=Path(self.temporary.name)
        self.script=self.root/'fake_cli.py';self.script.write_text(FAKE,encoding='utf-8')
        self.bridge=CodexTaskBridge(self.root,command_prefix=[sys.executable,str(self.script)])
        self.cwd=self.root/'work';self.cwd.mkdir()
    def tearDown(self):
        self.bridge.close();time.sleep(.05);self.temporary.cleanup()
    def test_status_is_whitelisted(self):
        status=self.bridge.status()
        self.assertTrue(status['installed']);self.assertTrue(status['loggedIn']);self.assertEqual(status['authMethod'],'chatgpt')
        self.assertNotIn('token',json.dumps(status).lower());self.assertNotIn('stderr',status)
        self.assertFalse(any(key.startswith('CODEX_') and key != 'CODEX_HOME' for key in clean_codex_environment()))
    def test_paths_and_modes(self):
        self.assertEqual(local_directory(str(self.cwd)),self.cwd.resolve())
        for bad in ['',r'\\server\share',str(Path(self.cwd.anchor)),str(self.cwd/'missing')]:
            with self.subTest(pathKind='invalid'),self.assertRaises((ValueError,OSError)):
                local_directory(bad)
        for mode in ['danger-full-access','--yolo','workspace-write --foo']:
            with self.assertRaises(ValueError):self.bridge.start('OK',str(self.cwd),mode)
        for task in ['', 'x'*4001, 'bad\x00task']:
            with self.assertRaises(ValueError):self.bridge.start(task,str(self.cwd))
    def test_new_and_existing_arguments(self):
        job=self.bridge.start('ARGS',str(self.cwd));done=finished(self.bridge,job['id']);args=json.loads(done['output'])
        self.assertEqual(done['status'],'success');self.assertEqual(args,{'sandbox':'read-only','ephemeral':True,'resume':False,'cwdMatches':True})
        self.assertNotIn('task',done);self.assertNotIn('_started',done);self.assertNotIn('_stop',done)
        elapsed=done['elapsedSeconds'];time.sleep(.06);self.assertEqual(self.bridge.snapshot(job['id'])['elapsedSeconds'],elapsed)
        self.bridge.target_thread='00000000-1111-2222-3333-444444444444'
        job=self.bridge.start('ARGS',str(self.cwd),'workspace-write','existing');done=finished(self.bridge,job['id']);args=json.loads(done['output'])
        self.assertEqual(args,{'sandbox':'workspace-write','ephemeral':False,'resume':True,'cwdMatches':True})
        self.assertFalse(any((self.root/'state').glob('*')))
    def test_task_is_stdin_not_shell(self):
        literal='$(Get-Content private.txt); & echo no-shell'
        done=finished(self.bridge,self.bridge.start(literal,str(self.cwd))['id'])
        self.assertEqual(done['output'],literal);self.assertFalse(list(self.cwd.iterdir()))
        self.assertNotIn('synthetic-secret-command',json.dumps(done))
    def test_related_roots_only_in_explicit_entry_write_mode(self):
        self.bridge.default_workspace=self.cwd
        related=self.root/'existing-installation';related.mkdir();self.bridge.related_write_roots=[related.resolve()]
        for directory,mode,expected in [(self.cwd,'read-only',[]),(self.cwd,'workspace-write',[str(related.resolve())]),(self.root,'workspace-write',[])]:
            done=finished(self.bridge,self.bridge.start('ARGS_ROOTS',str(directory),mode)['id'])
            self.assertEqual(json.loads(done['output'])['addDirs'],expected)
            self.assertEqual(done['additionalWriteRoots'],expected)
    def test_failure_is_classified_not_dumped(self):
        done=finished(self.bridge,self.bridge.start('FAIL',str(self.cwd))['id'])
        self.assertEqual(done['status'],'failed');self.assertIn('额度',done['message'])
        self.assertNotIn('synthetic-secret-marker',json.dumps(done))
    def test_stop_and_single_active_job(self):
        job=self.bridge.start('SLOW',str(self.cwd))
        with self.assertRaises(ValueError):self.bridge.start('OK',str(self.cwd))
        self.bridge.stop(job['id']);done=finished(self.bridge,job['id'])
        self.assertEqual(done['status'],'stopped');self.assertFalse(self.bridge.processes)
    def test_output_retention_is_bounded(self):
        self.bridge.jobs['synthetic']={'id':'synthetic','sequence':0,'events':[]}
        for _ in range(150):self.bridge._event(self.bridge.jobs['synthetic'],'progress','x'*20000)
        self.assertEqual(len(self.bridge.jobs['synthetic']['events']),120)
        self.assertEqual(len(self.bridge.jobs['synthetic']['events'][0]['text']),16000)
        self.bridge.jobs.pop('synthetic')


class ApiChecks(unittest.TestCase):
    setUp=BridgeChecks.setUp
    tearDown=BridgeChecks.tearDown
    def test_http_origin_csrf_and_routes(self):
        import server
        from http.server import ThreadingHTTPServer
        original=(server.PORT,server.ORIGIN,server.LOGS,server.CODEX)
        httpd=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        server.PORT=httpd.server_address[1];server.ORIGIN=f'http://127.0.0.1:{server.PORT}'
        server.LOGS=self.root/'logs';server.LOGS.mkdir();server.CODEX=self.bridge
        threading.Thread(target=httpd.serve_forever,daemon=True).start()
        def request(route,body=None,extra=None):
            headers={'Origin':server.ORIGIN,'X-Control-CSRF':server.TOKEN,'Content-Type':'application/json'}
            if extra:headers.update(extra)
            req=urllib.request.Request(server.ORIGIN+route,data=json.dumps(body).encode() if body is not None else None,headers=headers)
            try:
                with urllib.request.urlopen(req,timeout=5) as response:return response.status,json.load(response)
            except urllib.error.HTTPError as error:return error.code,json.load(error)
        try:
            self.assertEqual(request('/api/codex/status')[0],200)
            payload={'task':'OK','workspace':str(self.cwd),'mode':'read-only','target':'new'}
            for headers in [{'X-Control-CSRF':''},{'Origin':'https://example.org'},{'Sec-Fetch-Site':'cross-site'},{'Host':'example.org'}]:
                self.assertEqual(request('/api/codex/start',payload,headers)[0],403)
            self.assertFalse(self.bridge.jobs)
            self.assertEqual(request('/api/codex/start',{**payload,'mode':'danger-full-access'})[0],400)
            code,data=request('/api/codex/start',payload);self.assertEqual(code,202)
            done=finished(self.bridge,data['job']['id']);self.assertEqual(done['output'],'OK')
            self.assertEqual(request('/api/codex/jobs/'+data['job']['id'])[0],200)
            self.assertEqual(request('/api/codex/jobs/unknown')[0],404)
            self.assertEqual(request('/api/codex/stop',{'jobId':data['job']['id']})[0],200)
            for asset in ['/codex-tasks.js','/codex-tasks.css']:
                with urllib.request.urlopen(server.ORIGIN+asset,timeout=5) as response:self.assertEqual(response.status,200)
        finally:
            httpd.shutdown();httpd.server_close()
            server.PORT,server.ORIGIN,server.LOGS,server.CODEX=original


if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    report={'test':'codex-task-bridge-offline-subprocess-and-loopback-api','passed':result.testsRun-len(result.failures)-len(result.errors),'total':result.testsRun,'success':result.wasSuccessful(),'realCodexTasksSubmitted':False,'productionServerRestarted':False,'credentialsRead':False}
    (Path(__file__).parent/'verification-codex-bridge.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    raise SystemExit(0 if result.wasSuccessful() else 1)

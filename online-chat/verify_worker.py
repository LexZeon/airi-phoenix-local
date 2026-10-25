"""Offline worker permission/transport tests with synthetic CLI subprocesses only."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from chat_worker import ChatWorker, DISABLED_FEATURES

FAKE = r'''
import json,sys,time
a=sys.argv[1:]
assert '--ignore-user-config' in a and '--ephemeral' in a and a[a.index('--sandbox')+1]=='read-only'
assert not any('bypass' in x or x=='resume' for x in a)
for f in ['shell_tool','apps','plugins','multi_agent','computer_use','code_mode_host']:
 assert any(a[n:n+2]==['--disable',f] for n in range(len(a)-1))
p=json.loads(sys.stdin.read());scenario=p['messages'][-1]['content']
def emit(v):print(json.dumps(v),flush=True)
if scenario=='BEFORE_GUARD':emit({'type':'item.completed','item':{'type':'agent_message','text':'must not escape'}})
if scenario!='NO_GUARD':emit({'type':'item.completed','item':{'type':'error','message':'Code Mode is unavailable because code-mode host is disabled. Code mode will fail closed.'}})
if scenario=='WARNING':emit({'type':'item.completed','item':{'type':'error','message':'unrecognized configuration setting'}})
emit({'type':'turn.started'})
if scenario=='CANCEL':time.sleep(60)
if scenario=='INVALID_JSON':print('not-json',flush=True)
if scenario=='UNKNOWN_EVENT':emit({'type':'unknown.future.event'})
if scenario=='TOOL':emit({'type':'item.started','item':{'type':'command_execution','command':'must not execute'}})
if scenario in ('ROUTER','LATE_ROUTER'):
 if scenario=='LATE_ROUTER':
  for _ in range(12):print('synthetic-warning'*400,file=sys.stderr,flush=True)
 print('ERROR codex_core::tools::router: error=code-mode host is disabled',file=sys.stderr,flush=True)
emit({'type':'item.completed','item':{'type':'agent_message','text':'intermediate commentary'}})
emit({'type':'item.completed','item':{'type':'agent_message','text':'OK'}})
emit({'type':'turn.completed'})
'''

class WorkerChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='airi-chat-worker-')
        self.base=Path(self.temp.name)
        (self.base/'control-center').mkdir()
        original=Path(__file__).resolve().parents[1]/'control-center/codex_bridge.py'
        shutil.copyfile(original,self.base/'control-center/codex_bridge.py')
        self.root=self.base/'runtime/airi-codex-chat';self.root.mkdir(parents=True)
        self.cli=self.base/'fake_cli.py';self.cli.write_text(FAKE,encoding='utf-8')
        self.previous=os.environ.pop('AIRI_COMPANIONS_ROOT',None)
        self.worker=ChatWorker(self.root,command_prefix=[sys.executable,str(self.cli)])
    def tearDown(self):
        if self.previous is not None:os.environ['AIRI_COMPANIONS_ROOT']=self.previous
        self.temp.cleanup()
    def run_reply(self,text):return list(self.worker.stream([{'role':'user','content':text}],threading.Event()))
    def test_only_final_real_message_event(self):
        self.assertEqual(self.run_reply('GOOD'),['OK']);self.assertEqual(list(self.worker.scratch.iterdir()),[])
        self.assertEqual(self.worker.metrics['completed'],1)
    def test_guard_required_before_text(self):
        for scenario in ('NO_GUARD','BEFORE_GUARD','WARNING','INVALID_JSON','UNKNOWN_EVENT'):
            with self.subTest(scenario=scenario),self.assertRaises(RuntimeError):self.run_reply(scenario)
    def test_tool_events_and_router_rejections_fail(self):
        for scenario in ('TOOL','ROUTER','LATE_ROUTER'):
            with self.subTest(scenario=scenario),self.assertRaises(RuntimeError):self.run_reply(scenario)
        self.assertEqual(self.worker.metrics['toolAttemptsRejected'],3)
    def test_images_tools_and_external_inputs_rejected(self):
        for messages in [[{'role':'tool','content':'x'}],[{'role':'user','content':[{'type':'image_url','image_url':{'url':'file:///private.png'}}]}],[{'role':'assistant','content':'x','tool_calls':[{}]}]]:
            with self.assertRaises(RuntimeError):list(self.worker.stream(messages,threading.Event()))
        (self.worker.scratch/'unexpected.txt').write_text('synthetic',encoding='utf-8')
        with self.assertRaises(RuntimeError):self.run_reply('GOOD')
    def test_cancel_stops_owned_child(self):
        cancelled=threading.Event();errors=[]
        def run():
            try:list(self.worker.stream([{'role':'user','content':'CANCEL'}],cancelled))
            except RuntimeError as error:errors.append(str(error))
        thread=threading.Thread(target=run);thread.start();time.sleep(.2);cancelled.set();thread.join(timeout=8)
        self.assertFalse(thread.is_alive());self.assertTrue(errors)
    def test_args_and_environment_are_closed(self):
        args=self.worker.arguments()
        self.assertIn('--ignore-user-config',args);self.assertIn('--ephemeral',args)
        self.assertNotIn('resume',args);self.assertNotIn('--dangerously-bypass-approvals-and-sandbox',args)
        self.assertEqual(args[args.index('--sandbox')+1],'read-only')
        self.assertEqual(len(DISABLED_FEATURES),23)
        self.assertFalse(any(k.startswith('CODEX_') and k!='CODEX_HOME' for k in self.worker.helpers.clean_codex_environment()))

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(WorkerChecks))
    report={'test':'text-only-closed-worker-offline-subprocess','passed':result.testsRun-len(result.failures)-len(result.errors),'total':result.testsRun,'success':result.wasSuccessful(),'cloudCalls':False,'privateDataRead':False}
    (Path(__file__).parent/'verification-worker.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report));raise SystemExit(0 if result.wasSuccessful() else 1)

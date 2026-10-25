"""AIRI-only installed choices and evidence. Does not crawl creative model libraries."""
from pathlib import Path
import os
import statistics
from profiles import BASE, read_json, CHOICES
from codex_bridge import discover_codex
from aliyun_bridge import AliyunTtsBridge

MODELS=Path(os.environ.get('AIRI_MODELS_ROOT', str(BASE/'models'))).expanduser().resolve()
WORKBENCH=Path(os.environ.get('AIRI_WORKBENCH', str(BASE/'workbench'))).expanduser().resolve()
SPEECH=Path(os.environ.get('AIRI_SPEECH_ROOT', str(BASE/'runtime/airi-speech'))).expanduser().resolve()
QWEN=Path(os.environ.get('AIRI_TTS_ROOT', str(BASE/'runtime/airi-qwen-tts'))).expanduser().resolve()
SAPI=Path(os.environ.get('AIRI_SAPI_ROOT', str(BASE/'runtime/airi-sapi'))).expanduser().resolve()
CODEX_CHAT=Path(os.environ.get('AIRI_CODEX_CHAT_ROOT', str(BASE/'runtime/airi-codex-chat'))).expanduser().resolve()

ALIYUN_TTS=Path(os.environ.get('AIRI_ALIYUN_TTS_ROOT', str(BASE/'runtime/airi-aliyun-tts'))).expanduser().resolve()

def installed(path):
    try: return {'file':str(path),'bytes':path.stat().st_size,'exists':True}
    except OSError: return {'file':str(path),'bytes':0,'exists':False}

def catalog():
    aliyun=AliyunTtsBridge(BASE/'control-center').status()
    cfg=read_json(SPEECH/'config.json',{})
    asr=Path(cfg.get('asr_directory',BASE/'open-llm-vtuber/models'))/'model.int8.onnx'
    qwen=MODELS/'TTS/Qwen3-TTS-12Hz-1.7B-CustomVoice/model.safetensors'
    assets={
      'qwen9':installed(MODELS/'GGUF/Qwen3.5-9B-Q4_K_M.gguf'),
      'qwen27':installed(MODELS/'GGUF/Qwen3.8-27B-UD-Q4_K_M.gguf'),
      'vision9':installed(BASE/'runtime/airi-vision/mmproj-F16.gguf'),
      'sensevoice':installed(asr),'melo':installed(SPEECH/'models/melo-zh-en/model.int8.onnx'),
      'qwen-tts':installed(qwen),
      'sapi':{'file':'Windows system voice','bytes':0,'kind':'system-voice','exists':(SAPI/'samples/huihui-soft.wav').is_file()},
      'codex-chat':{'file':'Official Codex account connection','bytes':0,'kind':'online-account','exists':bool(discover_codex() and (CODEX_CHAT/'server.py').is_file() and (CODEX_CHAT/'verification-live-persona.json').is_file())},
      'aliyun-tts':{'file':'Aliyun cloud speech connection','bytes':0,'kind':'online-speech','exists':(ALIYUN_TTS/'aliyun_config.py').is_file()},
    }
    verified=read_json(QWEN/'verification.json',read_json(QWEN/'tests/verification.json',{}))
    samples=read_json(QWEN/'samples/sample-report.json',{})
    tokenizer=installed(qwen.parent/'speech_tokenizer/model.safetensors')
    ready_tts=bool(verified.get('ok') and assets['qwen-tts']['bytes']==3833402552 and tokenizer['bytes']==682293092)
    specs=[
      ('qwen9','聊天','响应快','9B 日常聊天','与看屏幕共用已就绪的9B服务和32768上下文，不重复加载。',[8,16],[8,14],'chat','qwen9'),
      ('qwen27','聊天','占用较多','27B 更多容量','复杂任务可以尝试；未做同题对比，不保证每次更快或更准确。',[16,32],[20,30],'chat','qwen27'),
      ('codex-chatgpt','聊天','在线可选','ChatGPT 账号 · 在线聊天','使用 ChatGPT/Codex 账号额度，只支持文字；完整回答后交付，与桌面 ChatGPT 独立会话。',[0.2,1],[0,0],'chat','codex-chat'),
      ('vision9','看屏幕','推荐','9B 看屏幕','已有配套视觉文件，用于屏幕画面和图片理解。',[8,16],[8,14],'vision','qwen9'),
      ('sensevoice','听你说话','响应快','SenseVoice 本地识别','本机语音识别服务，支持中文等语言；不上传录音。',[1,3],[0,0],'asr','sensevoice'),
      ('melo','角色声音','响应快','Melo 通用声音','中英双语的轻量备用声音，适合想尽快听到回复时使用。',[1,3],[0,0],'tts','melo'),
      ('qwen-soft','角色声音','推荐','Serena · 温柔','自然温柔的公开预设音色；整段生成后播放，有等待时间。',[8,16],[6,12],'tts','qwen-tts'),
      ('qwen-efficient','角色声音','同音色备选','Serena · 温柔优化版','保留同一声音与风格；本机短句对照更快，收益会随后台负载波动。',[8,16],[6,12],'tts','qwen-tts'),
      ('sapi-huihui','角色声音','系统轻量','慧慧 · 系统声音','无需新增模型，出声快；声音较机械，不能保留 Serena 的自然风格。',[0.2,1],[0,0],'tts','sapi'),
      ('aliyun-tts','角色声音','在线可选','阿里云 · 在线语音','配置百炼密钥后试听测速，再决定是否使用；合成时会在线处理回复文字。',[0.2,1],[0,0],'tts','aliyun-tts'),
      ('qwen-drowsy','角色声音','微倦','Serena · 困倦','更松弛、带微倦语气的风格，复用同一份已安装权重。',[8,16],[6,12],'tts','qwen-tts'),
      ('qwen-focused','角色声音','认真','Serena · 专注','清楚、认真的风格，复用同一份已安装权重。',[8,16],[6,12],'tts','qwen-tts'),
    ]
    items=[]
    for id_, label, tag, name, description, ram, gpu, module, asset in specs:
        item={'id':id_,'module':module,'category':label,'tag':tag,'name':name,'description':description,
              'installed':ready_tts if asset=='qwen-tts' else assets[asset]['exists'],
              'memory':{'ramGiB':ram,'gpuGiB':gpu,'basis':'按已安装量化权重与加载余量估算，非最低配置；UMA共享同一物理内存池。'},
              'asset':assets[asset], 'endpoint':CHOICES[id_][1], 'model':CHOICES[id_][2], 'voice':CHOICES[id_][3],
              'evidence':[]}
        if module=='vision': item['installed']=item['installed'] and assets['qwen9']['exists'];item['sharedWeight']=assets['qwen9']
        if id_=='codex-chatgpt':
            report=read_json(CODEX_CHAT/'verification-live-persona.json',{})
            item['online']=True
            item['capabilities']={'text':True,'images':False,'tools':False,'tokenStreaming':False}
            item['memory']['basis']='本机仅运行连接程序，主要计算在云端；不是本机模型最低配置。'
            item['latency']={'firstContentSeconds':report.get('firstContentSeconds'),'samples':1,'scope':'合成角色问候，首个完整回答事件；不是逐token流式或实际AIRI长历史表现。'}
        if id_=='aliyun-tts':
            item['online']=True
            item['voice']=aliyun.get('voice','Serena')
            item['configured']=aliyun.get('configured',False)
            item['keyConfigured']=aliyun.get('keyConfigured',False)
            item['cloudTested']=aliyun.get('cloudTested',False)
            item['capabilities']={'speech':True,'streamingPlayback':False,'styleInstructions':aliyun.get('styleSupported',False)}
            item['memory']['basis']='本机仅运行音频连接程序，语音合成在云端；不用新增语音模型权重。'
            measured=aliyun.get('lastTest',{})
            timings=measured.get('timings',{})
            if measured.get('status')=='success' and timings.get('audioDurationSeconds',0)>0:
                seconds=timings['completeWavMs']/1000
                duration=timings['audioDurationSeconds']
                item['evidence']=[{'title':'阿里云固定短句测速','source':'本机保存的阿里云试听结果','testedAt':measured.get('checkedAt',measured.get('testedAt','')),
                    'audioSeconds':duration,'generationSeconds':seconds,'rtf':seconds/duration,
                    'note':'云端首音频块约 '+str(round(timings['firstAudioMs']/1000,3))+' 秒；当前 AIRI 收齐完整小句后播放，不等于实际开口等待。'}]
        if asset=='qwen-tts':
            sample=next((s for s in samples.get('samples',[]) if s.get('voice')==CHOICES[id_][3]),None)
            if sample: item['evidence']=[{'source':'runtime/airi-qwen-tts/samples/sample-report.json','testedAt':samples.get('testedAt'),
               'audioSeconds':sample['audio_seconds'],'generationSeconds':sample['generation_seconds'],'rtf':sample['rtf'],
               'note':'本机历史单样例，含加载/缓存差异；整段合成，不是流式首包延迟。'}]
            item['sample']='/api/samples/'+('phoenix-soft' if id_=='qwen-efficient' else CHOICES[id_][3])
        if id_=='sapi-huihui': item['sample']='/api/samples/huihui'
        if id_=='melo': item['sample']='/api/samples/melo'
        if id_ in ('qwen-soft','qwen-efficient'):
            report=read_json(BASE/'publication/airi-phoenix-local/voice/tests/efficient-http-verification.json',{})
            runs=[run for run in report.get('runs',[]) if run.get('voice')==CHOICES[id_][3]]
            if runs:
                seconds=statistics.median(run['first_complete_wav_seconds'] for run in runs)
                audio=statistics.median(run['audio_seconds'] for run in runs)
                item['evidence']=[{'title':'Serena 同句接口对照','source':'voice/tests/efficient-http-verification.json','testedAt':'本机固定短句，后台看屏幕保持开启',
                  'audioSeconds':audio,'generationSeconds':seconds,'rtf':seconds/audio,
                  'note':'每模式2次；本句两模式声音文件完全相同。小样本和后台负载会影响收益；不是麦克风到扬声器的总等待。'}]
        if id_=='melo':
            report=read_json(BASE/'runtime/airi-offline/performance/melo-2rep.json',{})
            sample=report.get('summaries',{}).get('tts',{})
            if sample:
                item['evidence']=[{'title':'Melo 同句接口对照','source':'performance/melo-2rep.json','testedAt':report.get('testedAt',''),
                  'audioSeconds':sample['wav_audio_seconds']['median'],'generationSeconds':sample['total_ms']['median']/1000,'rtf':sample['real_time_factor']['median'],
                  'note':'2次固定短句；声音与Serena不同。不包含识别、聊天或扬声器等待。'}]
        if id_=='sapi-huihui':
            report=read_json(SAPI/'verification.json',{})
            runs=report.get('sampleRuns',[])
            if runs:
                seconds=statistics.median(run['wallSeconds'] for run in runs)
                audio=statistics.median(run['audioSeconds'] for run in runs)
                item['evidence']=[{'title':'系统语音同句接口对照','source':'runtime/airi-sapi/verification.json','testedAt':'本机服务就绪后的固定短句',
                  'audioSeconds':audio,'generationSeconds':seconds,'rtf':seconds/audio,
                  'note':'不含程序启动时间；系统声音较机械，不能保留Serena音色和风格控制。未自动切换。'}]
        items.append(item)
    return {'items':items,'hardware':{'name':os.environ.get('AIRI_HARDWARE_LABEL','本机硬件'),
      'note':'使用UMA时，Windows和GPU可能报告同一物理内存池的不同口径，不能相加。实际计数以当前CIM/nvidia-smi为准。'},
      'scope':'本地优先，在线可选；展示可接入 AIRI 的聊天、视觉、识别、语音方案，不下载新模型。',
      'scoreNote':'没有可比实测的项目不填分数；资源区间为建议，不代表性能排名。'}

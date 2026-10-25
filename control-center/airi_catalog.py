"""AIRI-only installed choices and evidence. Does not crawl creative model libraries."""
from pathlib import Path
import os
from profiles import BASE, read_json, CHOICES

MODELS=Path(os.environ.get('AIRI_MODELS_ROOT', str(BASE/'models'))).expanduser().resolve()
WORKBENCH=Path(os.environ.get('AIRI_WORKBENCH', str(BASE/'workbench'))).expanduser().resolve()
SPEECH=Path(os.environ.get('AIRI_SPEECH_ROOT', str(BASE/'runtime/airi-speech'))).expanduser().resolve()
QWEN=Path(os.environ.get('AIRI_TTS_ROOT', str(BASE/'runtime/airi-qwen-tts'))).expanduser().resolve()

def installed(path):
    try: return {'file':str(path),'bytes':path.stat().st_size,'exists':True}
    except OSError: return {'file':str(path),'bytes':0,'exists':False}

def catalog():
    cfg=read_json(SPEECH/'config.json',{})
    asr=Path(cfg.get('asr_directory',BASE/'open-llm-vtuber/models'))/'model.int8.onnx'
    qwen=MODELS/'TTS/Qwen3-TTS-12Hz-1.7B-CustomVoice/model.safetensors'
    assets={
      'qwen9':installed(MODELS/'GGUF/Qwen3.5-9B-Q4_K_M.gguf'),
      'qwen27':installed(MODELS/'GGUF/Qwen3.8-27B-UD-Q4_K_M.gguf'),
      'vision9':installed(BASE/'runtime/airi-vision/mmproj-F16.gguf'),
      'sensevoice':installed(asr),'melo':installed(SPEECH/'models/melo-zh-en/model.int8.onnx'),
      'qwen-tts':installed(qwen),
    }
    verified=read_json(QWEN/'verification.json',read_json(QWEN/'tests/verification.json',{}))
    samples=read_json(QWEN/'samples/sample-report.json',{})
    tokenizer=installed(qwen.parent/'speech_tokenizer/model.safetensors')
    ready_tts=bool(verified.get('ok') and assets['qwen-tts']['bytes']==3833402552 and tokenizer['bytes']==682293092)
    specs=[
      ('qwen9','聊天','响应快','9B 日常聊天','与看屏幕共用已就绪的9B服务和32768上下文，不重复加载。',[8,16],[8,14],'chat','qwen9'),
      ('qwen27','聊天','占用较多','27B 更多容量','复杂任务可以尝试；未做同题对比，不保证每次更快或更准确。',[16,32],[20,30],'chat','qwen27'),
      ('vision9','看屏幕','推荐','9B 看屏幕','已有配套视觉文件，用于屏幕画面和图片理解。',[8,16],[8,14],'vision','qwen9'),
      ('sensevoice','听你说话','响应快','SenseVoice 本地识别','本机语音识别服务，支持中文等语言；不上传录音。',[1,3],[0,0],'asr','sensevoice'),
      ('melo','角色声音','响应快','Melo 通用声音','中英双语的轻量备用声音，适合想尽快听到回复时使用。',[1,3],[0,0],'tts','melo'),
      ('qwen-soft','角色声音','推荐','Serena · 温柔','自然温柔的公开预设音色；整段生成后播放，有等待时间。',[8,16],[6,12],'tts','qwen-tts'),
      ('qwen-drowsy','角色声音','微倦','Serena · 困倦','更松弛、带微倦语气的风格，复用同一份已安装权重。',[8,16],[6,12],'tts','qwen-tts'),
      ('qwen-focused','角色声音','认真','Serena · 专注','清楚、认真的风格，复用同一份已安装权重。',[8,16],[6,12],'tts','qwen-tts'),
    ]
    items=[]
    for id_, label, tag, name, description, ram, gpu, module, asset in specs:
        item={'id':id_,'module':module,'category':label,'tag':tag,'name':name,'description':description,
              'installed':ready_tts if asset=='qwen-tts' else assets[asset]['exists'],
              'memory':{'ramGiB':ram,'gpuGiB':gpu,'basis':'按已安装量化权重与加载余量估算，非最低配置；使用UMA时共享同一物理内存池。'},
              'asset':assets[asset], 'endpoint':CHOICES[id_][1], 'model':CHOICES[id_][2], 'voice':CHOICES[id_][3],
              'evidence':[]}
        if module=='vision': item['installed']=item['installed'] and assets['qwen9']['exists'];item['sharedWeight']=assets['qwen9']
        if asset=='qwen-tts':
            sample=next((s for s in samples.get('samples',[]) if s.get('voice')==CHOICES[id_][3]),None)
            if sample: item['evidence']=[{'source':'runtime/airi-qwen-tts/samples/sample-report.json','testedAt':samples.get('testedAt'),
               'audioSeconds':sample['audio_seconds'],'generationSeconds':sample['generation_seconds'],'rtf':sample['rtf'],
               'note':'本机历史单样例，含加载/缓存差异；整段合成，不是流式首包延迟。'}]
            item['sample']='/api/samples/'+CHOICES[id_][3]
        if id_=='melo': item['sample']='/api/samples/melo'
        items.append(item)
    return {'items':items,'hardware':{'name':os.environ.get('AIRI_HARDWARE_LABEL','本机硬件'),
      'note':'使用UMA时，Windows和GPU可能报告同一物理内存池的不同口径，不能相加。实际计数以当前CIM/nvidia-smi为准。'},
      'scope':'仅展示可接入 AIRI 的本机聊天、视觉、识别、语音方案；不下载新模型。',
      'scoreNote':'没有可比实测的项目不填分数；资源区间为建议，不代表性能排名。'}

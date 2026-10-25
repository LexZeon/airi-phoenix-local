#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Generate an original looping VMD from an explicitly supplied bone map."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct

ALIASES={
 'left_arm':['左腕','arm_L','UpperArm_L','LeftArm'], 'right_arm':['右腕','arm_R','UpperArm_R','RightArm'],
 'left_elbow':['左ひじ','左肘','elbow_L','LeftForeArm'], 'right_elbow':['右ひじ','右肘','elbow_R','RightForeArm'],
 'left_wrist':['左手首','wrist_L','LeftHand'], 'right_wrist':['右手首','wrist_R','RightHand'],
 'upper':['上半身','spine','Spine'], 'chest':['上半身2','chest','Chest'],
 'center':['センター','Center','center'], 'lower':['下半身','Hips','hips'],
}

def quaternion(x,y,z):
    # Desired Three.js XYZ Euler -> VMD's MMD-coordinate quaternion.
    x,y,z=[math.radians(v)/2 for v in (x,y,z)]
    cx,cy,cz=math.cos(x),math.cos(y),math.cos(z)
    sx,sy,sz=math.sin(x),math.sin(y),math.sin(z)
    q=(sx*cy*cz+cx*sy*sz,cx*sy*cz-sx*cy*sz,cx*cy*sz+sx*sy*cz,cx*cy*cz-sx*sy*sz)
    return (-q[0],-q[1],q[2],q[3])

def generate(data,arm_gap=13,elbow_bend=12):
    bones=data['bones'];resolved={}
    for role,candidates in ALIASES.items():
        found=next((bone for name in candidates for bone in bones if bone['name']==name),None)
        if found:resolved[role]=found
    required=['left_arm','right_arm','left_elbow','right_elbow']
    if any(role not in resolved for role in required):raise ValueError('Both upper-arm and elbow bones must be mapped')
    angles={}
    for side,sign in [('left',1),('right',-1)]:
        a=resolved[side+'_arm']['position'];b=resolved[side+'_elbow']['position']
        dx,dy=b[0]-a[0],b[1]-a[1]
        current=math.atan2(dy,dx)
        desired=math.radians(-90+sign*arm_gap)
        delta=math.degrees(desired-current)
        delta=(delta+180)%360-180
        if abs(delta)>100:raise ValueError('Unexpected bone axis; inspect this skeleton before generating a pose')
        angles[side]=delta
    frames=[];period=360
    for frame in range(0,period+1,10):
        t=frame/30;breath=math.sin(2*math.pi*t/4);sway=math.sin(2*math.pi*t/12)
        states={
          'left_arm':((0,0,0),(0,0,angles['left']+.16*breath)),
          'right_arm':((0,0,0),(0,0,angles['right']-.16*breath)),
          'left_elbow':((0,0,0),(-elbow_bend,0,5+.15*sway)),
          'right_elbow':((0,0,0),(-elbow_bend,0,-5+.15*sway)),
          'left_wrist':((0,0,0),(4,0,-2)), 'right_wrist':((0,0,0),(4,0,2)),
          'upper':((0,0,0),(.36*breath,.10*sway,.18*sway)),
          'chest':((0,0,0),(.30*breath,-.10*sway,-.10*sway)),
          'lower':((0,0,0),(0,0,-.12*sway)),
          'center':((.065*sway,.018*(1-math.cos(2*math.pi*t/4)),0),(0,0,0)),
        }
        for role,(position,euler) in states.items():
            if role not in resolved:continue
            name=resolved[role]['name'].encode('shift_jis')
            if len(name)>15:raise ValueError('VMD bone name exceeds 15 Shift-JIS bytes')
            interpolation=bytes([20]*8+[107]*8)*4
            frames.append(name.ljust(15,b'\0')+struct.pack('<I3f4f',frame,*position,*quaternion(*euler))+interpolation)
    header=b'Vocaloid Motion Data 0002'.ljust(30,b'\0')+b'AIRI original idle'.ljust(20,b'\0')
    binary=header+struct.pack('<I',len(frames))+b''.join(frames)+struct.pack('<5I',0,0,0,0,0)
    report={'ok':True,'originalProceduralMotion':True,'durationSeconds':12,'fps':30,'frameStep':10,'boneKeyframes':len(frames),
            'mappedBones':{k:v['name'] for k,v in resolved.items()},'armTargetGapDegrees':arm_gap,
            'armZCorrectionDegrees':angles,'elbowForwardBendDegrees':elbow_bend,
            'loopEndpointsMatch':True,'headEyeMouthTracks':False,'physicsRequired':False,
            'sha256':hashlib.sha256(binary).hexdigest(),'bytes':len(binary),
            'scope':'Generic algorithm; mapping and pose must be visually checked on each skeleton. No official mesh, texture, or motion data is included.'}
    return binary,report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bones',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    p.add_argument('--arm-gap',type=float,default=13);p.add_argument('--elbow-bend',type=float,default=12);a=p.parse_args()
    if not 8<=a.arm_gap<=20 or not 0<=a.elbow_bend<=25:p.error('Use arm gap 8..20 and elbow bend 0..25 degrees')
    binary,report=generate(json.loads(a.bones.read_text(encoding='utf-8')),a.arm_gap,a.elbow_bend)
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_bytes(binary);a.out.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True,indent=2))

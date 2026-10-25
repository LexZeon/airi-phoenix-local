# MMD facial expression compatibility

Verified against AIRI commit `f1b81967f0d476eecf4e8848760f4de106310a9e` and one locally supplied PMX. The independent test called the real `MMDScene.setEmotion(name, 1)` and captured neutral, happy, angry and sad images. Happy visibly closes the smiling eyes; angry and sad produce more restrained eyebrow/eyelid differences. This is facial morph control, not gesture motion.

`Stage.vue` accepts the same emotion vocabulary as the MMD scene:

```text
<|ACT {"emotion":{"name":"happy","intensity":0.4}}|>
```

Valid names are `happy`, `sad`, `angry`, `think`, `surprised`, `awkward`, `question`, `curious`, `neutral`. The spelling is `surprised`, with a final `d`. Unsupported names fall back to neutral. Intensity is clamped to 0..1.

The model has 71 morphs. AIRI's default resolver selected these slots without custom overrides:

| AIRI slot | Model morph | Verification |
| --- | --- | --- |
| blink | まばたき | Present and resolved; procedural blink retained |
| blinkLeft / blinkRight | ウィンク / ウィンク右 | Present and resolved |
| vowelA / I / U / E / O | あ / い / う / え / お | All present and resolved; actual speech input was not part of the video-only test |
| smile | 笑い | Actual happy image captured |
| anger | 怒り | Actual angry image captured |
| sad | 悲しむ | Actual sad image captured |
| surprise | びっくり | Present and resolved; no separate screenshot test |
| serious | じと目 | Present and resolved; no separate screenshot test |
| troubled | none | No default candidate exists in this model |

Default emotion weights, before intensity scaling, come from AIRI's own `constants/morphs.ts`:

| Emotion | Morph slots |
| --- | --- |
| happy | smile .8, vowelA .2 |
| sad | sad .75, troubled .3 |
| angry | anger .8 |
| surprised | surprise .8, vowelO .4 |
| think | troubled .5, serious .4 |
| awkward | troubled .6, smile .2 |
| question | troubled .4, surprise .2 |
| curious | surprise .35, smile .25 |
| neutral | Clears expression slots |

Missing slots are ignored, so the unresolved `troubled` slot weakens think/awkward/question and one component of sad. A model-specific override such as `mmdStore.morphOverrides = { ...mmdStore.morphOverrides, troubled: '悲し' }` uses a present eyebrow morph, but that particular override has **not** been visually validated. Preserve existing overrides and verify before enabling it. No automatic override is applied by the idle helper.

The original idle has no head, eye, neck or morph tracks. Native gaze, blink and wLipSync therefore retain their normal control paths. This compatibility check does not claim that a TTS-to-audio-source lip-sync run or emotion gesture VMD was tested. No emotion gesture motions were supplied.

Source: [AIRI morph candidates and emotion weights](https://github.com/moeru-ai/airi/blob/f1b81967f0d476eecf4e8848760f4de106310a9e/packages/stage-ui-mmd/src/constants/morphs.ts), [emotion names](https://github.com/moeru-ai/airi/blob/f1b81967f0d476eecf4e8848760f4de106310a9e/packages/stage-ui-mmd/src/constants/emotions.ts).

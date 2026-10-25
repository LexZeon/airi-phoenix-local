# Layered Live2D faces: geometry checks and visual acceptance

A face can pass every parameter test and still look wrong. The local standing-model repair made that distinction concrete: an early version passed 135 Core geometry cases and visible pixel-change checks, but the user still saw misdirected eyes. A later revision restores the specific reference face selected by the user and adds semantic image checks. Character pictures, textures, models and complete private authoring projects are not distributed here.

## Reference and neutral placement

Keep the actual selected reference beside the render. File names such as “old” or “v2” do not establish which face the user prefers. Inspect the particular eye shape, pupil, highlight, brow and mouth, and preserve recoverable source parts when those are the desired design.

An eyelash sprite's bounding box is a poor pupil anchor. A long outer lash can bias the box in the opposite direction in the two eyes. Measuring the actual opening helps diagnose that error, but **pupil/white-region centroid equality is not a beauty criterion**. A natural reference can have intentional inward convergence and upper-lid overlap. The visible pupil is also not the centroid of a gold-colored region: upper iris shading and lid clipping bias that measurement.

Check the complete brow/eye assembly against the nose, mouth, jaw and head plane. Centering each iris inside its own opening does not fix a whole eye pair displaced on the face. A canvas center is not necessarily a facial landmark, either. Review the same pose and scale before changing placement.

## Splitting an existing WholeEye

When the selected art already has a good eye, a technical split can preserve its character better than generating another eye style:

1. Preserve the existing visible iris, pupil, highlight and fixed lash pixels.
2. Use an explicit inner-opening mask. Fill the white hole only inside the intersection of that opening and the iris footprint, using known sclera colors.
3. Treat a visible iris crop separately from its complete disk geometry. The upper quarter may already be hidden behind the eyelid; its visible bounding box is not the disk center.
4. If a small hidden cap is needed for gaze, supplement only the previously occluded region from a compatible full-iris source. Do not replace the visible reference pupil and highlight merely to obtain a complete disk.
5. Keep eyelids fixed while the iris tracks, and clip the iris with a real runtime mask. Verify nearly closed states so an iris outline does not remain as a gold ghost.

Keep reconstruction masks and pixel provenance. A faint line may cross skin and hair; a broad skin-color rectangle can erase hair along with the intended mark. The selected reference may contain the same line. Prefer a scoped, reviewable decision over an automatic cleanup. Transparent PNG pixels can contain colored RGB under zero alpha; that does not establish a visible background that needs repainting.

## Shared motion must be tested on the base face

Testing iris versus eye frame is necessary, but insufficient. The base may contain the nose, skin and entire head while only the new facial parts belong to a separate motion group. Sample reference points in the base and in the eyes, brows and mouth under body motion and combined head/body/breath poses.

Read the weighting formula before changing an apparently reversed range. In the audited implementation the weight is `1 - smoothstep(clamp((y-full)/(zero-full)))`. A descending range can deliberately make body translation zero above the neck. The actual Core probe tested body-X minus/plus extremes at three identical head/body-Z/breath contexts: six comparisons showed zero movement of the tested face/feature anchors. No redundant dependency was added for that suspected issue.

## Useful acceptance layers

| Layer | What was checked | Limit |
|---|---|---|
| Core | Binary accepted; 135 parameter/combined geometry cases; real iris mask counts | Does not establish likeness |
| Standard installed renderer | 29 actual AIRI Pixi/Cubism WebGL frames | Still needs human comparison |
| Extended renderer matrix | 45 frames, including eye-open 0.65, gaze, full/partial blink, head tilt and combined body poses | An isolated renderer is not a completed main-app import |
| Semantic pixels | Closed eyes have no gold iris ghost; opposite eye unchanged; mouth does not alter eyes; both visible irises travel in the requested direction | Color-region centroids are direction checks, not a naturalness score |
| Actual Core landmarks | Same signed iris movement and base-face/feature coherence | Numerical alignment alone is not visual acceptance |
| Visual review | Same-size reference, whole face, full body, expressions and control sheets | Final user preference remains material |

The reference-face revision passed 33 checks and retained the original approved body/hair/clothing source bytes. Candidate preparation kept the canonical model separate; deployment retained the older archive for rollback. The real main-app helper subsequently confirmed an imported Live2D ZIP and a new display-model binding for the distinct standing card. This proves import, not active native visual inspection or final user acceptance: both remain unverified in the sanitized report. Preparing the art did not change voice or camera settings.

Do not publish private reference pictures, generated character art, user model textures, runtime state, tokens or screenshots containing other applications merely to substantiate these methods. A sanitized report can state the checks, counts, failure causes, correction and remaining integration boundary without distributing those assets.

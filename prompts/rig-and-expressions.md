# Binding and expression prompt pack

Read the project schema and one working example. Inspect alpha bounds and preview the neutral composite. Work in the project's declared canvas coordinates; make source paths relative to the project. Keep the user's original assets intact.

Bind left/right eye openness independently, lips to the target app's mouth-open parameter, and shallow head/body movement to the actual mesh. Preserve texture continuity at neck and hair boundaries. Draw facial features beneath explicit hair occluders when required.

Validate natural gaze separately from pixel differences. A sprite's alpha bounding box can include long outer lashes, so its center is not necessarily the center of the eye-white opening. For a requested frontal neutral gaze, use the actual eye opening's landmark/connected-component center and the iris center, then visually check both eyes together. Verify target-specific X/Y signs and gaze amplitude in actual renders; top-down source-image Y differs from the usual positive-up EyeBallY convention. Preserve an intentionally asymmetric source gaze when fidelity to that exact illustration is the goal. Different PNG hashes, changing pixels and finite Core geometry cannot establish that the gaze looks natural.

Each expression needs distinct parameter values or layers that visibly change the avatar. Record how a reference becomes a practical rig expression. If a reference includes an unavailable arm pose or special iris, omit that feature or describe the translation; do not label an unchanged sprite as that animation.

Suggested iteration request:

> Inspect this project and neutral preview. Adjust only the geometry/placement or parameters needed to correct the observed issue. Rebuild and run Core validation. Compare neutral, blink, mouth-open and representative expression previews. Explain any remaining visual limit and preserve the prior project revision.

For AIRI, use the exact expression names in its model manifest. An emotion word in the character prompt alone is not an expression controller. Use AIRI's supported Act expression syntax and verify at least one change in the live renderer.

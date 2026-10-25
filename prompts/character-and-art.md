# Character and artwork prompt pack

Use these as adaptable production briefs, not text that must be copied verbatim.

## Evidence brief

Identify the exact character/version/costume. Prefer official character pages and official video sources for factual claims. For expression references record a URL, timestamp or image identifier, a short original visual description, and uncertainty. Separate canon from roleplay interpretation. Do not invent missing facts or quote whole scenes.

Before generating a new character, search for existing Live2D and 3D/MMD/VRM releases, unless the user has already supplied the relevant verified results or requested an offline-only authoring session. Record the actual URLs, model format, author/official identity, availability and applicable readme/license terms. If nothing suitable is found, record the searches and uncertainty rather than claiming no model exists anywhere.

For miHoYo/HoYoverse and similar anime-game characters, prioritize the game's official creator/model distribution pages and the publisher's official account on **模之屋 / Aplaybox**. Verify the account through an official cross-link or publisher identity evidence; a title containing the game name is insufficient. The verified Zenless Zone Zero account used by this example is `https://www.aplaybox.com/u/352588796/model`. Search its current releases rather than assuming a new character has no model because a general search engine has not indexed it. Use the normal download flow, including the user's existing login when needed. Do not bypass account, interaction, password or download restrictions. Keep restricted downloaded models outside the public repository and release ZIP; publish only links, reference notes and authoring configuration.

A permitted 3D model can supply orthographic or three-quarter reference views and help check facial proportions, costume silhouette, accessories and expression morphs. Separate permission to download, use as reference, modify, use in an AI companion and redistribute; these can differ. Keep restricted model files local and link their original distribution page instead of bundling them into the public tool. Do not turn a game asset extraction or an unverified mirror into an official release claim.

Select recognizable expressions that fit this character's personality. Describe observable eyelid, eyebrow, mouth and posture changes instead of a generic list of emotion names. A static source does not prove a hand or body animation exists.

## Choose an artwork route

If a permitted layered source exists, preserve it rather than regenerating the face.
For fidelity to a specific official pose, retain its face outline, asymmetry, hair,
costume, accessories and silhouette. A front-facing symmetric redesign is an optional
new art direction requiring the user's preference, not the default production step.
A 3D package with video-only terms is not automatically usable as a desktop model or
as generative-AI input. If that use is restricted, retain its URL/terms and choose a
separately permitted reference/authoring route.

For an original or permitted new illustration:

> Create the requested avatar base with transparent margins. Keep the selected identity,
> pose, facial proportions, linework and costume. Leave only the eye/brow/mouth areas
> needed for independent binding as clean matching skin. Do not omit distinctive props,
> wings or accessories unless the user chooses that adaptation. This is an intermediate
> layer, not the finished avatar.

For a small underlay edit to an existing permitted illustration:

> Treat the supplied exact crop as the edit target. Remove only the requested eyes,
> brows or tiny mouth into matching skin. Preserve asymmetry, nose, face contour, hair,
> ornaments and pose. Do not beautify, make younger/rounder, rotate or symmetrize the
> face. The compiler will sample the generated patch only inside explicit small masks;
> it must never replace the whole face crop.

The agent uses its own available image tools for semantic editing. The toolkit's
`source_overlays` performs only deterministic externally supplied patch compositing.
Compare neutral reconstruction with the source before changing the actual app. For a
pixel-preserving route, require zero changes outside explicit masks and restore original
feature pixels in neutral. Keep the editable configuration and the exact prompts.

## Facial atlas brief

> Match the base's identity and linework. Produce a transparent equal-cell atlas of independent open eyes, closed-eye lash lines, eyebrows, neutral/smiling/worried mouth lines, an open speaking mouth, a surprised mouth and optional cheek accents. Every component has its own cell with margins, no whole head, no surrounding skin rectangle and no text. Specify the exact row/column order and viewer-left/viewer-right convention.

Check actual dimensions and alpha before authoring cell coordinates. A request for a particular image size is not proof that the generator returned that size.

For more capable rigs, provide genuinely separated hair, head, torso, arm and mouth/eye interior layers. Avoid large turns when unseen surfaces have not been drawn. Use the target app's existing legal runtime; keep its Core out of the generated asset bundle.

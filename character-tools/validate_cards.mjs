// SPDX-License-Identifier: MIT
// Read-only compatibility checks against an existing AIRI checkout.
// Usage: node validate_cards.mjs <airi-checkout> <config-json> <export-directory>
import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const [airiRoot, configPath, out] = process.argv.slice(2);
if (!airiRoot || !configPath || !out) throw new Error('Expected airi-checkout, config-json, export-directory');
const load = async file => JSON.parse(await readFile(file, 'utf8'));
const config = await load(configPath);
const native = await load(path.join(out, `${config.id}.airi-native.json`));
const v3 = await load(path.join(out, `${config.id}.ccv3.json`));
const v2 = await load(path.join(out, `${config.id}.sillytavern-v2.json`));
const { parseCharacterCardV3 } = await import(pathToFileURL(path.join(airiRoot, 'packages/ccc/src/codec/characterCardV3.ts')));
const { normalizeActPayload } = await import(pathToFileURL(path.join(airiRoot, 'packages/pipelines-audio/src/llm-streaming-control/payloads.ts')));
const { createLive2DExpressionsContext, parseLive2DExpression } = await import(pathToFileURL(path.join(airiRoot, 'packages/stage-ui-live2d/src/contexts/expressions.ts')));
assert.equal(parseCharacterCardV3(v3).compatibility, 'current');
assert.equal(v2.spec, 'chara_card_v2');
assert.equal(v2.spec_version, '2.0');
for (const key of ['name', 'description', 'personality', 'scenario', 'first_mes', 'mes_example', 'creator_notes', 'system_prompt', 'post_history_instructions', 'creator', 'character_version'])
  assert.equal(typeof v2.data[key], 'string', key);
for (const key of ['alternate_greetings', 'tags']) assert.ok(Array.isArray(v2.data[key]));
assert.equal(typeof v2.data.extensions, 'object');
assert.equal(v2.data.system_prompt, config.systemPrompt);
for (const expression of config.expressions ?? []) {
  assert.deepEqual(normalizeActPayload({ expression: { name: expression.name, duration: 3 } }),
    { expression: { name: expression.name, duration: 3 } });
  assert.ok(native.systemPrompt.includes(expression.name));
}
assert.deepEqual(normalizeActPayload({ expression: null }), { expression: null });
// Exercise the real expression registry/executor with synthetic parameter data;
// this proves the API path without touching a renderer or claiming visual QA.
const context = createLive2DExpressionsContext({ getParameterDefault: () => 0, isEnabled: () => true });
for (const expression of config.expressions ?? []) context.register(parseLive2DExpression(
  expression.name, `expressions/${expression.name}.exp3.json`,
  JSON.stringify({ Parameters: [{ Id: 'ParamTestOnly', Value: 0.5, Blend: 'Overwrite' }] }),
));
let resets = 0;
context.setExecutor({ activate: name => { context.reset(); return context.activate(name); }, reset: () => { resets++; context.reset(); return true; } });
for (const expression of config.expressions ?? []) {
  assert.equal(await context.execute({ name: expression.name }), true);
  assert.equal(context.parameters.value.get('ParamTestOnly').currentValue, 0.5);
}
assert.equal(await context.execute({ name: 'Unknown_TestOnly' }), false);
if (config.expressions?.length) {
  assert.equal(await context.execute({ name: config.expressions[0].name, duration: 0.01 }), true);
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.equal(resets, 1);
  assert.equal(context.parameters.value.get('ParamTestOnly').currentValue, 0);
}
assert.equal(await context.resetExecution(), true);
context.clear();
const require = createRequire(import.meta.url);
const { mergeNewCard } = require('./merge-card.cjs');
const previous = [['existing-user-card', { name: 'Existing', extensions: { airi: { modules: { consciousness: { provider: 'leave-provider', model: 'leave-model' } } } } }]];
const before = JSON.stringify(previous);
const first = mergeNewCard(previous, native, { cardId: config.id, displayModelId: 'display-model-test-only' });
assert.equal(first.added, true);
assert.equal(JSON.stringify(previous), before);
assert.equal(JSON.stringify(first.entries[0]), JSON.stringify(previous[0]));
assert.equal(first.entries[1][1].extensions.airi.avatarModels[0].displayModelId, 'display-model-test-only');
first.entries[1][1].systemPrompt = 'A user edit to preserve';
const second = mergeNewCard(first.entries, native, { cardId: config.id });
assert.equal(second.added, false);
assert.equal(second.entries[1][1].systemPrompt, 'A user edit to preserve');
assert.equal(second.entries.length, 2);
const report = {
  passed: true,
  ccv3: 'Parsed by the installed AIRI @proj-airi/ccc source schema',
  sillyTavernV2: 'Required field types checked against Character Card V2 specification',
  expressions: { count: (config.expressions ?? []).length, parser: 'All names and reset accepted by actual AIRI normalizeActPayload', executor: 'Actual AIRI expression context accepted all names, changed a synthetic test parameter, rejected unknown names and reset on timer' },
  merge: 'Existing cards, caller input and edits remain unchanged; duplicate initialization is idempotent',
  limitation: 'This does not exercise a running renderer or guarantee that every expression visibly animates the eventual model.',
};
await writeFile(path.join(out, 'card-validation.json'), JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify(report));

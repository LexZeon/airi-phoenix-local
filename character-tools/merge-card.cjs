'use strict';
// SPDX-License-Identifier: MIT

// Pure helper for a caller-owned initialization transaction. No storage, network,
// imports from AIRI internals, or process side effects. Do not run this against a
// live IndexedDB database. Prefer AIRI's normal package import whenever possible.
function clone(value) { return JSON.parse(JSON.stringify(value)); }

function mergeNewCard(cardsInput, card, options = {}) {
  const entries = typeof cardsInput === 'string' ? JSON.parse(cardsInput) : clone(cardsInput ?? []);
  if (!Array.isArray(entries) || entries.some(e => !Array.isArray(e) || e.length !== 2 || typeof e[0] !== 'string'))
    throw new Error('Expected AIRI card map serialized as [id, card][]');
  if (!card || typeof card.name !== 'string' || !card.extensions?.airi?.modules)
    throw new Error('Expected the exported AIRI native card');
  const requestedId = options.cardId;
  if (typeof requestedId !== 'string' || !requestedId.trim())
    throw new Error('An explicit stable cardId is required');
  // Idempotent initialization. Existing user edits, avatar binding, prompts and
  // modules are preserved even when an ID already exists. Never update all cards.
  if (entries.some(([id]) => id === requestedId))
    return { entries, storageValue: JSON.stringify(entries), cardId: requestedId, added: false };
  const next = clone(card);
  next.extensions.airi.avatarModels = [];
  delete next.extensions.airi.defaultAvatarModelId;
  if (options.displayModelId) {
    if (typeof options.displayModelId !== 'string') throw new Error('displayModelId must be a string');
    const avatarId = `${requestedId}-avatar`;
    next.extensions.airi.avatarModels = [{
      id: avatarId, displayModelId: options.displayModelId, type: 'live2d',
      config: { controls: { disabledExpressions: [], disabledMotions: [] } },
    }];
    next.extensions.airi.defaultAvatarModelId = avatarId;
  }
  entries.push([requestedId, next]);
  return { entries, storageValue: JSON.stringify(entries), cardId: requestedId, added: true,
    requiresModelImport: !options.displayModelId };
}

module.exports = { mergeNewCard };

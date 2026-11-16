// What the harness does before each question, kept apart from pi so tests can drive it: attach (or
// re-attach) to the game, re-read the save so the game date is current, and fetch the schema card.
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { attachFix } from './fm-reader-session.mjs';

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));

/** Where schema cards are cached: PI_FM_CARD_DIR, else <pi-fm>/tmp/schema-cards. */
export function cardDirectory(env = process.env) {
  return env.PI_FM_CARD_DIR || join(ROOT, 'tmp', 'schema-cards');
}

/**
 * Returns {save, attachError, schemaCard, notice}. Never throws: an attach failure becomes
 * `attachError` ({message, fix}), which the prompt states word for word.
 */
export async function prepareTurn({ session, cards, hasReader = true }) {
  if (!hasReader) return { save: null, attachError: null, schemaCard: null, notice: null };
  try {
    await session.refresh();
  } catch (error) {
    const message = String(error?.message ?? error);
    session.error = { message, fix: attachFix(message) };
  }
  const attachError = session.error ?? null;
  const save = attachError ? null : session.summary();
  let schemaCard = null;
  if (!attachError && cards) {
    try { schemaCard = await cards.get(session.serverInfo?.version ?? 'unknown'); } catch { schemaCard = null; }
  }
  const notice = attachError ? `FM reader: ${attachError.message} Fix: ${attachError.fix}` : null;
  return { save, attachError, schemaCard, notice };
}

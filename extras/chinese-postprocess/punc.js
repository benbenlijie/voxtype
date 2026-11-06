/**
 * Remove spacing artifacts that are unambiguous in common transcripts.
 * Ordinary spaces between words are intentionally left unchanged.
 */
export function tidy(text) {
  return text
    // Chinese punctuation does not take spaces on either side.
    .replace(/\s*([，。！？；：、（）「」『』【】《》])/gu, '$1')
    .replace(/([，。！？；：、（）「」『』【】《》])\s+/gu, '$1')
    // Restore punctuation and separators split by speech recognition.
    .replace(/\s+([.,:;%!?])/gu, '$1')
    .replace(/([0-9])\s*\.\s*([0-9])/gu, '$1.$2')
    .replace(/([0-9])\s*:\s*([0-9])/gu, '$1:$2')
    .replace(/([0-9])\s*%/gu, '$1%')
    .replace(/([A-Za-z])\s+-\s*(?=[0-9])/gu, '$1-')
    .replace(/\s*\/\s*/gu, '/')
    .replace(/\bC\s*\+\s*\+/gu, 'C++');
}

/**
 * Apply injectable language conversion and punctuation restoration steps.
 * Model failures preserve the successfully converted text.
 */
export async function processText(text, { toSimplified, restorePunctuation } = {}) {
  if (!text.trim()) return text;

  const simplified = toSimplified ? await toSimplified(text) : text;
  if (!/\p{Script=Han}/u.test(simplified) || !restorePunctuation) {
    return tidy(simplified);
  }

  try {
    const restored = await restorePunctuation(simplified);
    return typeof restored === 'string' && restored.length > 0
      ? tidy(restored)
      : tidy(simplified);
  } catch {
    return tidy(simplified);
  }
}

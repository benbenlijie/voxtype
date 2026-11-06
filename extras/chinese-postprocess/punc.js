import { spawn } from 'node:child_process';

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
 * Run a user-installed punctuation adapter without a shell.
 * The adapter receives UTF-8 text on stdin and returns processed text on stdout.
 */
export function runPunctuationCommand(command, text, {
  env = process.env,
  timeoutMs = 15000,
  maxOutputBytes = 1024 * 1024,
  scriptArgs = [],
} = {}) {
  if (!command) return Promise.reject(new Error('No punctuation adapter configured'));

  return new Promise((resolve, reject) => {
    const child = spawn(command, scriptArgs, { env, stdio: ['pipe', 'pipe', 'ignore'] });
    const chunks = [];
    let outputBytes = 0;
    let settled = false;
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      finish(new Error('Punctuation adapter timed out'));
    }, timeoutMs);

    function finish(error, output) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error) reject(error);
      else resolve(output);
    }

    child.on('error', () => finish(new Error('Punctuation adapter could not start')));
    child.stdout.on('data', (chunk) => {
      outputBytes += chunk.length;
      if (outputBytes > maxOutputBytes) {
        child.kill('SIGKILL');
        finish(new Error('Punctuation adapter output exceeded the limit'));
        return;
      }
      chunks.push(chunk);
    });
    child.on('close', (code) => {
      const output = Buffer.concat(chunks).toString('utf8');
      if (code !== 0 || !output.trim()) {
        finish(new Error('Punctuation adapter returned no usable result'));
      } else {
        finish(null, output);
      }
    });
    child.stdin.on('error', () => {});
    child.stdin.end(text, 'utf8');
  });
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

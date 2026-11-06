import test from 'node:test';
import assert from 'node:assert/strict';
import { processText } from '../punc.js';

test('skips punctuation restoration for English-only text', async () => {
  let called = false;
  const result = await processText('Hello world.', {
    toSimplified: (text) => text,
    restorePunctuation: () => { called = true; return 'unexpected'; },
  });
  assert.equal(result, 'Hello world.');
  assert.equal(called, false);
});

test('converts traditional Chinese and restores punctuation for Chinese text', async () => {
  let received;
  const result = await processText('繁體文字', {
    toSimplified: (text) => `简体:${text}`,
    restorePunctuation: (text) => { received = text; return '你好 ， 世界 ！'; },
  });
  assert.equal(received, '简体:繁體文字');
  assert.equal(result, '你好，世界！');
});

test('returns empty input without invoking processing functions', async () => {
  let called = false;
  const result = await processText(' \n\t', {
    toSimplified: () => { called = true; return 'unexpected'; },
    restorePunctuation: () => { called = true; return 'unexpected'; },
  });
  assert.equal(result, ' \n\t');
  assert.equal(called, false);
});

test('keeps simplification and punctuation spacing when the model is unavailable', async () => {
  const result = await processText('繁體文字', {
    toSimplified: () => '简体 文字',
    restorePunctuation: () => null,
  });
  assert.equal(result, '简体 文字');
});

test('keeps completed simplification when punctuation inference fails', async () => {
  const result = await processText('繁體文字', {
    toSimplified: () => '简体 文字',
    restorePunctuation: () => { throw new Error('model failure'); },
  });
  assert.equal(result, '简体 文字');
});

test('tidies only the restored model output', async () => {
  const result = await processText('GPT -4o 繁體', {
    toSimplified: () => 'GPT -4o 简体',
    restorePunctuation: () => 'GPT -4o ， 简体',
  });
  assert.equal(result, 'GPT-4o，简体');
});

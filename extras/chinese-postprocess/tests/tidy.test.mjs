import test from 'node:test';
import assert from 'node:assert/strict';
import { tidy } from '../punc.js';

test('removes spaces inside decimal numbers', () => {
  assert.equal(tidy('2 . 0'), '2.0');
});

test('removes spaces inside times', () => {
  assert.equal(tidy('12 : 30'), '12:30');
});

test('removes spaces inside percentages', () => {
  assert.equal(tidy('3 . 5 %'), '3.5%');
});

test('joins a spaced hyphen in a product name', () => {
  assert.equal(tidy('GPT -4o'), 'GPT-4o');
});

test('joins spaces around a slash', () => {
  assert.equal(tidy('TCP / IP'), 'TCP/IP');
});

test('joins spaces in C++', () => {
  assert.equal(tidy('C + +'), 'C++');
});

test('keeps exactly one space after an English sentence period', () => {
  assert.equal(tidy('Hello . World'), 'Hello. World');
});

test('removes extra spaces around Chinese punctuation', () => {
  assert.equal(tidy('你好 ， 世界 ！ 好吗 ？'), '你好，世界！好吗？');
});

test('preserves ordinary English word spacing', () => {
  assert.equal(tidy('Hello   kind world'), 'Hello   kind world');
});

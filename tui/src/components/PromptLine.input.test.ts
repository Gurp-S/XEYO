import React, {useState} from 'react';
import {render} from 'ink';
import {PassThrough, Writable} from 'node:stream';
import test from 'node:test';
import assert from 'node:assert/strict';
import {PromptLine} from './PromptLine.js';

test('command keys preserve draft and caret; pasted text still edits', async () => {
  const stdin = new PassThrough() as any;
  stdin.isTTY = true; stdin.setRawMode = () => {}; stdin.ref = () => {}; stdin.unref = () => {};
  const stdout = new Writable({write(_chunk, _encoding, done) {done();}}) as any;
  stdout.isTTY = true; stdout.columns = 100; stdout.rows = 30;
  let submitted = '';
  function Draft() {
    const [value, setValue] = useState('');
    return React.createElement(PromptLine, {value, onChange: setValue,
      onSubmit: (v: string) => {submitted = v;}, mode: 'agent', busy: false});
  }
  const instance = render(React.createElement(Draft), {stdin, stdout, stderr: stdout,
    exitOnCtrlC: false, patchConsole: false, debug: true});
  const key = async (s: string) => {stdin.write(s); await new Promise(r => setTimeout(r, 50));};
  try {
    await new Promise(r => setTimeout(r, 80));
    await key('ab'); await key('\x1b[D'); await key('\x12'); // Ctrl+R belongs to App.
    await key('r🙂'); await key('\r');
    assert.equal(submitted, 'ar🙂b');
    await key('\x7f'); await key('\r');
    assert.equal(submitted, 'arb', 'backspace removes one Unicode character');
  } finally {instance.unmount();}
});

import React, {useEffect, useRef, useState} from 'react';
import {Text, useInput} from 'ink';

/** Prompt editing owns printable keys; App owns command keys. */
export function PromptTextInput({value, onChange, onSubmit, placeholder = ''}: {
  value: string; onChange: (value: string) => void;
  onSubmit: (value: string) => void; placeholder?: string;
}) {
  const chars = Array.from(value);
  const [offset, setOffset] = useState(chars.length);
  const expectedValue = useRef(value);
  const cursor = Math.min(offset, chars.length);
  useEffect(() => {
    if (expectedValue.current !== value) setOffset(Array.from(value).length);
    expectedValue.current = value;
  }, [value]);

  useInput((input, key) => {
    if (key.ctrl || key.meta || key.escape || key.tab || key.upArrow || key.downArrow
      || key.pageUp || key.pageDown) return;
    if (key.return) {onSubmit(value); return;}
    if (key.leftArrow) {setOffset(Math.max(0, cursor - 1)); return;}
    if (key.rightArrow) {setOffset(Math.min(chars.length, cursor + 1)); return;}
    let next = chars.slice();
    let position = cursor;
    if (key.backspace || key.delete) {
      if (!cursor) return;
      next.splice(cursor - 1, 1); position--;
    } else {
      // A pasted chunk is one input event; preserve its printable Unicode text.
      const inserted = Array.from(input.replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, ''));
      if (!inserted.length) return;
      next.splice(cursor, 0, ...inserted); position += inserted.length;
    }
    expectedValue.current = next.join('');
    setOffset(position);
    onChange(expectedValue.current);
  });

  if (!value && placeholder) {
    const [first, ...rest] = Array.from(placeholder);
    return <Text dimColor><Text inverse>{first}</Text>{rest.join('')}</Text>;
  }
  return <Text>{chars.slice(0, cursor).join('')}<Text inverse>{chars[cursor] ?? ' '}</Text>{chars.slice(cursor + 1).join('')}</Text>;
}

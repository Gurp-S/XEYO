import {signal} from '@preact/signals-react';

const value = signal('a');
value.value = 'b';
if (value.value !== 'b') {
  throw new Error('signal update failed');
}

console.log('signals-react-import-ok');

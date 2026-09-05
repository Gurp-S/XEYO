const fs=require('fs');
const p='E:/nodejs/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-session-persistence-jsonl/lib/index.js';
const s=fs.readFileSync(p,'utf8').split('\n');
process.stdout.write('=== scanZstdFrames (497-565) ===\n');
process.stdout.write(s.slice(496,565).join('\n')+'\n');

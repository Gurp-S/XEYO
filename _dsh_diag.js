const fs=require('fs');
const p='E:/nodejs/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-session-persistence-jsonl/lib/index.js';
const s=fs.readFileSync(p,'utf8').split('\n');
const hits=[];
s.forEach((l,i)=>{ if(/decompress|Decompression|koffi|zstd|zstandard|readFirstZstdLine|listArtifacts|assertZstd|deflate|gunzip|createReadStream|readline/i.test(l)) hits.push(String(i+1)+'| '+l.trim()); });
process.stdout.write(hits.join('\n')+'\n');

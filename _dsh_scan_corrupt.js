const fs=require('fs'),os=require('os'),path=require('path');
const {zstdDecompressSync}=require('node:zlib');
const ZSTD=4247762216;
function frames(buf){const out=[];let o=0;while(buf.length-o>=4&&buf.readUInt32LE(o)===ZSTD){const s=o;o+=4;if(o===buf.length)break;const d=buf.readUInt8(o);o++;if((d&24)!==0)break;const cs=d>>>6,sg=(d&32)!==0,ck=(d&4)!==0,df=d&3;const db=df===3?4:df;const cb=cs===0?(sg?1:0):(1<<cs);const rh=(sg?0:1)+db+cb;if(buf.length-o<rh)break;o+=rh;let ok=false;for(;;){if(buf.length-o<3)break;const bh=buf.readUIntLE(o,3);o+=3;const lb=(bh&1)!==0,bt=(bh>>>1)&3,bs=bh>>>3;if(bt===3)break;const pb=bt===1?1:bs;if(buf.length-o<pb)break;o+=pb;if(lb){ok=true;break}}if(!ok)break;if(ck){if(buf.length-o<4)break;o+=4}out.push([s,o])}return out}
const root=os.homedir()+'/.dsh/sessions';
let bad=[];
function walk(d){
  for(const e of fs.readdirSync(d,{withFileTypes:true})){
    const fp=path.join(d,e.name);
    if(e.isDirectory()){walk(fp);continue}
    if(!e.name.endsWith('.zstd'))continue;
    let buf=fs.readFileSync(fp);
    let txt='';
    try{for(const[s,e]of frames(buf))txt+=zstdDecompressSync(buf.subarray(s,e)).toString('utf8');}catch{continue}
    let ln=0;
    for(const l of txt.split('\n')){ln++;if(!l.startsWith('{'))continue;let o;try{o=JSON.parse(l)}catch{continue}
      if(o.type!=='tool/call')continue;const raw=o.data&&o.data.arguments;if(typeof raw!=='string')continue;
      try{JSON.parse(raw)}catch(e){bad.push({file:fp,line:ln,id:(o.data&&o.data.callId)||'?',err:String(e.message).slice(0,80),head:raw.slice(0,160)});}
    }
    buf=null;txt=null;
  }
}
walk(root);
console.log('total corrupt tool/call args: '+bad.length);
for(const b of bad.slice(0,25))console.log('\n'+b.file.replace(os.homedir(),'~')+' L'+b.line+' call='+b.id+'\n  ERR '+b.err+'\n  RAW '+JSON.stringify(b.head));

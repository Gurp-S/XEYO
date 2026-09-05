const fs=require('fs'),os=require('os'),path=require('path');
const root=os.homedir()+'/.dsh/sessions';
let total=0,zstd=0,big=0;
function walk(d){for(const e of fs.readdirSync(d,{withFileTypes:true})){
  const fp=path.join(d,e.name);
  if(e.isDirectory())walk(fp);
  else if(e.name.endsWith('.zstd')){zstd++;const sz=fs.statSync(fp).size;total+=sz;if(sz>1024*1024)big++;}
}}
walk(root);
console.log('zstd files:',zstd,' total bytes:',total,' files>1MB:',big);
// top 20 largest zstd with path
const arr=[];
function walk2(d){for(const e of fs.readdirSync(d,{withFileTypes:true})){
  const fp=path.join(d,e.name);
  if(e.isDirectory())walk2(fp);
  else if(e.name.endsWith('.zstd'))arr.push([fs.statSync(fp).size,fp]);
}}
walk2(root);
arr.sort((a,b)=>b[0]-a[0]);
for(const[sz,fp]of arr.slice(0,20))console.log((sz/1024/1024).toFixed(2)+'MB  '+fp.replace(os.homedir(),'~'));

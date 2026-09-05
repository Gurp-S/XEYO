const cp=require('child_process');
// 1) identify the process on 3080 vs dsh
function run(cmd){try{return cp.execSync(cmd,{encoding:'utf8',stdio:['ignore','pipe','pipe']})}catch(e){return 'ERR:'+e.message}}
console.log('=== PID 14352 ===');
console.log(run('tasklist /FI "PID eq 14352" /FO LIST'));
console.log('=== any node/dsh web processes ===');
console.log(run('wmic process where "name=\'node.exe\'" get ProcessId,CommandLine /format:list'));

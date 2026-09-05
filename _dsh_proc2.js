const cp=require('child_process');
function run(cmd){
  try{
    const r=cp.spawnSync('powershell',['-NoProfile','-Command',cmd],{encoding:'utf8',stdio:['ignore','pipe','pipe']});
    return (r.stdout||'')+(r.stderr||'');
  }catch(e){return 'ERR '+e.message}
}
console.log('=== PID 14352 identity ===');
console.log(run("Get-CimInstance Win32_Process -Filter \"ProcessId=14352\" | Select-Object ProcessId,CreationDate,CommandLine | Format-List"));
console.log('=== all dsh/node processes ===');
console.log(run("Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | Select-Object ProcessId,CreationDate,CommandLine | Format-List"));

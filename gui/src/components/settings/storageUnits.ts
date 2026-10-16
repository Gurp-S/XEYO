const MIB = 1024 * 1024;
export function bytesToStorageDraft(bytes: number): string { return String(bytes / MIB); }
export function storageDraftToBytes(raw: string): {ok:true;value:number|null}|{ok:false;message:string} {
 if (!raw.trim()) return {ok:true,value:null};
 const bytes = Number(raw) * MIB;
 if (!Number.isFinite(bytes) || bytes < 0 || !Number.isSafeInteger(Math.round(bytes))) return {ok:false,message:'存储上限必须是非负数，且不能超过可精确保存的范围'};
 return {ok:true,value:Math.round(bytes)};
}

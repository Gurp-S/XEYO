export type TerminalLine = {kind:'in'|'out'|'err'|'info';text:string};
export const TERMINAL_MAX_CHARS = 2_000_000;
export const TERMINAL_MAX_BLOCKS = 2000;
export function appendTerminalBuffer(current: TerminalLine[], added: TerminalLine[]) {
	const lines=[...current,...added];
	let chars=lines.reduce((n,line)=>n+line.text.length,0);
	let discardedChars=0;
	let start=0;
	while(start < lines.length && (lines.length-start > TERMINAL_MAX_BLOCKS || chars-lines[start].text.length >= TERMINAL_MAX_CHARS)) {
		chars-=lines[start].text.length;
		discardedChars+=lines[start++].text.length;
	}
	const kept=lines.slice(start);
	if(chars > TERMINAL_MAX_CHARS && kept.length) {
		const excess=chars-TERMINAL_MAX_CHARS;
		kept[0]={...kept[0],text:kept[0].text.slice(excess)};
		discardedChars+=excess;
	}
	return {lines:kept,discardedChars};
}

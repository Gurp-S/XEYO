import {afterEach, describe, expect, it, vi} from 'vitest';
import {startVisiblePolling} from './visiblePolling';
import {appendTerminalBuffer,TERMINAL_MAX_CHARS,TERMINAL_MAX_BLOCKS} from './terminalBuffer';
import {scrollMarkdownHeading} from './markdownAnchor';
import {workspaceGitFiles} from './workspaceGit';

afterEach(()=>{vi.useRealTimers();vi.restoreAllMocks();document.body.innerHTML='';});
describe('GUI repair boundaries',()=>{
	it('slow polling never overlaps, pauses when hidden, and aborts on dispose',async()=>{
		vi.useFakeTimers();
		let visibility='visible';
		vi.spyOn(document,'visibilityState','get').mockImplementation(()=>visibility as DocumentVisibilityState);
		let release!:()=>void;let signal!:AbortSignal;
		const read=vi.fn((next:AbortSignal)=>{signal=next;return new Promise<void>(r=>{release=r;});});
		const stop=startVisiblePolling(read,100);
		await vi.advanceTimersByTimeAsync(1000);expect(read).toHaveBeenCalledTimes(1);
		visibility='hidden';document.dispatchEvent(new Event('visibilitychange'));release();
		await vi.advanceTimersByTimeAsync(1000);expect(read).toHaveBeenCalledTimes(1);
		visibility='visible';document.dispatchEvent(new Event('visibilitychange'));expect(read).toHaveBeenCalledTimes(2);
		stop();expect(signal.aborted).toBe(true);release();
		await vi.advanceTimersByTimeAsync(1000);expect(read).toHaveBeenCalledTimes(2);
	});
	it('bounds both giant blocks and thousands of small terminal results',()=>{
		const giant=appendTerminalBuffer([],[{kind:'out',text:'x'.repeat(TERMINAL_MAX_CHARS+20)}]);
		expect(giant.lines[0].text.length).toBe(TERMINAL_MAX_CHARS);expect(giant.discardedChars).toBe(20);
		const many=appendTerminalBuffer([],Array.from({length:TERMINAL_MAX_BLOCKS+40},()=>({kind:'out' as const,text:'ok'})));
		expect(many.lines.length).toBe(TERMINAL_MAX_BLOCKS);expect(many.discardedChars).toBe(80);
	});
	it('heading links stay inside their own message even with duplicate heading ids',()=>{
		document.body.innerHTML='<article><h2 id="same">First</h2></article><article><h2 id="same">Second</h2></article>';
		const roots=document.querySelectorAll('article');const first=vi.fn(),second=vi.fn();
		roots[0].firstElementChild!.scrollIntoView=first;roots[1].firstElementChild!.scrollIntoView=second;
		scrollMarkdownHeading(roots[1],'same');expect(first).not.toHaveBeenCalled();expect(second).toHaveBeenCalledOnce();
	});
	it('keeps Git additions, deletions, untracked and mixed states',()=>{
		const files=workspaceGitFiles({ok:true,repo:true,cwd:'x',staged:[{path:'a',status:'A'},{path:'mixed',status:'A'}],unstaged:[{path:'d',status:'D'},{path:'mixed',status:'M'}],untracked:[{path:'u',status:'??'}]});
		expect(files.map(f=>[f.path,f.gitStatus])).toEqual([['a','A'],['mixed','A / M'],['d','D'],['u','?']]);
	});
});

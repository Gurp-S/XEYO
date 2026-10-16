import {create} from 'zustand';
import {samePath} from '@/lib/paths';

import {appendTerminalBuffer,type TerminalLine} from '@/lib/terminalBuffer';
export type {TerminalLine} from '@/lib/terminalBuffer';

type TerminalSessionState = {
	rootPath: string;
	command: string;
	lines: TerminalLine[];
	discardedChars:number;
	clearOutput:()=>void;
	history: string[];
	cursor: number;
	busy: boolean;
	sequence: number;
	ensureRoot: (rootPath: string) => void;
	setCommand: (command: string) => void;
	setCursor: (cursor: number) => void;
	beginCommand: (text: string, rootPath: string) => number | null;
	appendLines: (sequence: number, lines: TerminalLine[]) => void;
	finishCommand: (sequence: number) => void;
};

export const useTerminalSessionStore = create<TerminalSessionState>()((set, get) => ({
	rootPath: '',
	command: '',
	lines: [],
	discardedChars:0,
	history: [],
	cursor: -1,
	busy: false,
	sequence: 0,
	ensureRoot(rootPath) {
		const current = get();
		if (samePath(current.rootPath, rootPath)) return;
		set(state => ({
			rootPath,
			command: '',
			lines: [],
	discardedChars:0,
			history: [],
			cursor: -1,
			busy: false,
			sequence: state.sequence + 1,
		}));
	},
	clearOutput() {set({lines:[],discardedChars:0});},
	setCommand(command) {
		set({command});
	},
	setCursor(cursor) {
		set({cursor});
	},
	beginCommand(text, rootPath): number | null {
		const current = get();
		const command = text.trim();
		if (!command || current.busy || !samePath(current.rootPath, rootPath)) {
			return null;
		}
		const sequence = current.sequence + 1;
		const buffer=appendTerminalBuffer(current.lines,[{kind:'in',text:command}]);
		set({
			sequence,
			command: '',
			cursor: -1,
			busy: true,
			lines:buffer.lines,
			discardedChars:current.discardedChars+buffer.discardedChars,
			history: [command, ...current.history.filter(item => item !== command)].slice(0, 30),
		});
		return sequence;
	},
	appendLines(sequence, lines) {
		set(state => {
			if(state.sequence!==sequence)return state;
			const buffer=appendTerminalBuffer(state.lines,lines);
			return {lines:buffer.lines,discardedChars:state.discardedChars+buffer.discardedChars};
		});
	},
	finishCommand(sequence) {
		set(state => (state.sequence === sequence ? {busy: false} : state));
	},
}));

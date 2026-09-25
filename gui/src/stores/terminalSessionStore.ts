import {create} from 'zustand';
import {samePath} from '@/lib/paths';

export type TerminalLine = {kind: 'in' | 'out' | 'err' | 'info'; text: string};

type TerminalSessionState = {
	rootPath: string;
	command: string;
	lines: TerminalLine[];
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
			history: [],
			cursor: -1,
			busy: false,
			sequence: state.sequence + 1,
		}));
	},
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
		set({
			sequence,
			command: '',
			cursor: -1,
			busy: true,
			lines: [...current.lines, {kind: 'in', text: command}],
			history: [command, ...current.history.filter(item => item !== command)].slice(0, 30),
		});
		return sequence;
	},
	appendLines(sequence, lines) {
		set(state =>
			state.sequence === sequence
				? {lines: [...state.lines, ...lines]}
				: state,
		);
	},
	finishCommand(sequence) {
		set(state => (state.sequence === sequence ? {busy: false} : state));
	},
}));

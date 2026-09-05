import {create} from 'zustand';

const STORAGE_KEY = 'xeyo.commandPalette.recents.v1';
const MAX_RECENT_AGENTS = 12;
const MAX_RECENT_FILES = 12;

export type RecentAgent = {
	id: string;
	title: string;
	spaceName: string;
	touchedAt: number;
};

export type RecentFile = {
	path: string;
	name: string;
	touchedAt: number;
};

type PersistedRecents = {
	agents: RecentAgent[];
	files: RecentFile[];
};

function loadRecents(): PersistedRecents {
	if (typeof localStorage === 'undefined') {
		return {agents: [], files: []};
	}
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (!raw) {
			return {agents: [], files: []};
		}
		const parsed = JSON.parse(raw) as Partial<PersistedRecents>;
		return {
			agents: Array.isArray(parsed.agents) ? parsed.agents.slice(0, MAX_RECENT_AGENTS) : [],
			files: Array.isArray(parsed.files) ? parsed.files.slice(0, MAX_RECENT_FILES) : [],
		};
	} catch {
		return {agents: [], files: []};
	}
}

function saveRecents(agents: RecentAgent[], files: RecentFile[]) {
	if (typeof localStorage === 'undefined') {
		return;
	}
	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify({agents, files}));
	} catch {
		/* 配额 / 隐私模式 */
	}
}

type CommandPaletteState = {
	open: boolean;
	recentAgents: RecentAgent[];
	recentFiles: RecentFile[];
	openPalette: () => void;
	closePalette: () => void;
	togglePalette: () => void;
	touchAgent: (agent: Omit<RecentAgent, 'touchedAt'> & {touchedAt?: number}) => void;
	touchFile: (file: Omit<RecentFile, 'touchedAt'> & {touchedAt?: number}) => void;
};

const initial = loadRecents();

export const useCommandPaletteStore = create<CommandPaletteState>((set, get) => ({
	open: false,
	recentAgents: initial.agents,
	recentFiles: initial.files,
	openPalette() {
		set({open: true});
	},
	closePalette() {
		set({open: false});
	},
	togglePalette() {
		set(s => ({open: !s.open}));
	},
	touchAgent(agent) {
		const touchedAt = agent.touchedAt ?? Date.now();
		const title = agent.title.trim() || '新对话';
		const next: RecentAgent[] = [
			{id: agent.id, title, spaceName: agent.spaceName, touchedAt},
			...get().recentAgents.filter(a => a.id !== agent.id),
		].slice(0, MAX_RECENT_AGENTS);
		const files = get().recentFiles;
		saveRecents(next, files);
		set({recentAgents: next});
	},
	touchFile(file) {
		const touchedAt = file.touchedAt ?? Date.now();
		const path = file.path.trim();
		if (!path) {
			return;
		}
		const name = file.name.trim() || path.split(/[\\/]/).pop() || path;
		const next: RecentFile[] = [
			{path, name, touchedAt},
			...get().recentFiles.filter(f => f.path !== path),
		].slice(0, MAX_RECENT_FILES);
		const agents = get().recentAgents;
		saveRecents(agents, next);
		set({recentFiles: next});
	},
}));

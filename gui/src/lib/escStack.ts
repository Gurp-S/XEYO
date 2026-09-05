type EscLayer = {
	id: string;
	handler: () => void;
};

const layers: EscLayer[] = [];
let listening = false;

function onKeyDown(e: KeyboardEvent): void {
	if (e.key !== 'Escape' || e.isComposing) {
		return;
	}
	const top = layers[layers.length - 1];
	if (!top) {
		return;
	}
	top.handler();
	e.preventDefault();
	e.stopPropagation();
}

function ensureListener(): void {
	if (listening) {
		return;
	}
	window.addEventListener('keydown', onKeyDown, true);
	listening = true;
}

export function pushEscLayer(id: string, handler: () => void): void {
	popEscLayer(id);
	layers.push({id, handler});
	ensureListener();
}

export function popEscLayer(id: string): void {
	for (let i = layers.length - 1; i >= 0; i--) {
		if (layers[i].id === id) {
			layers.splice(i, 1);
			return;
		}
	}
}

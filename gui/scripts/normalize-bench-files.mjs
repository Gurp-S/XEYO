import {readdir, rename} from 'node:fs/promises';
import {join} from 'node:path';

const dir = join(process.cwd(), 'bench-results');
const names = await readdir(dir);
const source = names.find(name => name.trim() === 'chatpage-blocks.json' && name !== 'chatpage-blocks.json');
if (source) {
	await rename(join(dir, source), join(dir, 'chatpage-blocks.json'));
	console.log(`normalized ${JSON.stringify(source)}`);
} else {
	console.log('no trailing-space benchmark file found');
}

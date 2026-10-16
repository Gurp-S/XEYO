// Build frozen, comparable GUI variants without changing the shared checkout.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {build, mergeConfig} from 'vite';
import {loadConfigFromFile} from 'vite';

const root = process.cwd();
const base = path.resolve(process.env.STARTUP_AB_DIR || '.tmp/startup-ab');
const variant = process.argv[2] || 'before';
if (!['before', 'after'].includes(variant)) throw new Error('Expected before or after');
if (variant === 'before' && fs.existsSync(path.join(base, 'before-modules.json'))) {
  throw new Error('The before baseline is frozen. Choose a fresh STARTUP_AB_DIR for another comparison.');
}
const snapshot = path.join(base, 'source');
if (!fs.existsSync(snapshot)) {
  fs.mkdirSync(snapshot, {recursive: true});
  fs.cpSync(path.join(root, 'src'), path.join(snapshot, 'src'), {recursive: true});
  for (const name of ['index.html', 'pet.html', 'package.json']) fs.copyFileSync(path.join(root, name), path.join(snapshot, name));
}
// Explicit owned files only. Concurrent edits elsewhere never change the A/B corpus.
for (const relative of process.argv.slice(3)) {
  const target = path.join(snapshot, relative);
  fs.mkdirSync(path.dirname(target), {recursive: true});
  fs.copyFileSync(path.join(root, relative), target);
}
const loaded = await loadConfigFromFile({command: 'build', mode: 'production'}, path.join(root, 'vite.config.ts'));
fs.copyFileSync(path.join(root, 'vite.config.ts'), path.join(base, `${variant}-vite.config.ts`));
// The repository cleanup plugin targets its regular dist; this isolated build
// must never modify another task's output directory.
loaded.config.plugins = loaded.config.plugins.filter(plugin => plugin?.name !== 'omit-deferred-public-assets');
const modules = {};
const config = mergeConfig(loaded.config, {
  configFile: false,
  root: snapshot,
  publicDir: path.join(root, 'public'),
  resolve: {alias: {'@': path.join(snapshot, 'src')}},
  build: {outDir: path.join(base, variant), manifest: true, rollupOptions: {
    input: {main: path.join(snapshot, 'index.html'), pet: path.join(snapshot, 'pet.html')},
  }},
  plugins: [{name: 'startup-ab-evidence', generateBundle(_, bundle) {
    for (const [name, entry] of Object.entries(bundle)) if (entry.type === 'chunk') {
      modules[name] = {bytes: Buffer.byteLength(entry.code), imports: entry.imports, dynamicImports: entry.dynamicImports,
        modules: Object.entries(entry.modules).map(([id, info]) => ({id: id.replaceAll(snapshot.replaceAll('\\', '/'), '<snapshot>'), bytes: info.renderedLength})).sort((a,b) => b.bytes-a.bytes)};
    }
  }}],
});
await build(config);
fs.writeFileSync(path.join(base, `${variant}-modules.json`), JSON.stringify(modules, null, 2));
const files = fs.readdirSync(path.join(snapshot, 'src'), {recursive: true}).filter(f => fs.statSync(path.join(snapshot, 'src', f)).isFile());
fs.writeFileSync(path.join(base, `${variant}-sources.json`), JSON.stringify(Object.fromEntries(files.map(f => [f, crypto.createHash('sha256').update(fs.readFileSync(path.join(snapshot, 'src', f))).digest('hex')])), null, 2));

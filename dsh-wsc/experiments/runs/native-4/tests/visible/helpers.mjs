import { cp, mkdtemp, open, readFile, readdir, rm, stat } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

export async function project() {
  const dir = await mkdtemp(path.join(tmpdir(), 'mini-build-visible-'));
  await cp(repoRoot, dir, {
    recursive: true,
    filter: (src) => !/[\\/](out|node_modules)([\\/]|$)/.test(src) && !src.endsWith('build-manifest.json'),
  });
  return dir;
}

export function cleanup(dir) {
  return rm(dir, { recursive: true, force: true });
}

let scratch = null;

function stdioDir() {
  scratch ??= mkdtemp(path.join(tmpdir(), 'mini-build-stdio-'));
  return scratch;
}

// Runs the real CLI in a child process. Child stdio is redirected to files
// instead of pipes: some sandboxes refuse to let a child inherit a pipe, and
// file handles are the portable way to capture its output either way.
export async function cli(dir, args) {
  const base = await stdioDir();
  const outFile = path.join(base, 'stdout.txt');
  const errFile = path.join(base, 'stderr.txt');
  const outFd = await open(outFile, 'w');
  const errFd = await open(errFile, 'w');
  let code;
  try {
    const child = spawn(process.execPath, ['bin/build.js', ...args], {
      cwd: dir,
      stdio: ['ignore', outFd.fd, errFd.fd],
    });
    code = await new Promise((resolve, reject) => {
      child.on('error', reject);
      child.on('close', (exitCode, signal) => resolve(exitCode ?? (signal ? 1 : 0)));
    });
  } finally {
    await outFd.close();
    await errFd.close();
  }
  return { code, stdout: await readFile(outFile, 'utf8'), stderr: await readFile(errFile, 'utf8') };
}

export async function build(dir, args = []) {
  const { code, stdout, stderr } = await cli(dir, ['--json', ...args]);
  if (code !== 0) throw new Error(`build failed (${code}): ${stderr}`);
  return JSON.parse(stdout);
}

export async function readManifest(dir, file = 'build-manifest.json') {
  return JSON.parse(await readFile(path.join(dir, file), 'utf8'));
}

export async function exists(target) {
  try {
    await stat(target);
    return true;
  } catch {
    return false;
  }
}

export async function listFiles(dir, base = dir) {
  const found = [];
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return found;
  }
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) found.push(...(await listFiles(abs, base)));
    else if (entry.isFile()) found.push(path.relative(base, abs).split(path.sep).join('/'));
  }
  return found.sort();
}

export async function outFiles(dir) {
  return listFiles(path.join(dir, 'out'));
}

export async function treeBytes(dir) {
  const files = new Map();
  for (const rel of await listFiles(dir)) files.set(rel, await readFile(path.join(dir, rel)));
  return files;
}

export function readOut(dir, rel) {
  return readFile(path.join(dir, 'out', rel), 'utf8');
}

export function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function waitFor(predicate, timeoutMs = 10000) {
  const started = Date.now();
  while (!(await predicate())) {
    if (Date.now() - started > timeoutMs) throw new Error('timed out waiting for condition');
    await delay(20);
  }
}

#!/usr/bin/env node
// Process-local adapter for the pinned, unmodified npm release. No installer or daemon.
import * as fs from 'node:fs';
import { createHash } from 'node:crypto';
import { gunzipSync } from 'node:zlib';
import { spawn, spawnSync } from 'node:child_process';
import { basename, delimiter, dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

export const PACKAGE = Object.freeze({
  name: 'huashu-motion', version: '0.1.1',
  integrity: 'sha512-RJAUfR4/kP4FwE/41xwMMTx/Ua5KAGDqg6gwUFcg2DLsLvWaZCDtzL6DYD4FuCoPgCfd+Ek/EMB/xZrwq7QjUg==',
});
export const COMMANDS = Object.freeze([
  'help', '--help', '-h', 'version', '--version', '-v', 'new', 'templates', 'demo',
  'studio', 'inbox', 'look', 'done', 'reopen', 'cancel', 'fonts', 'vars', 'set', 'scan',
  'render', 'check', 'qa', 'fork', 'voice', 'sound', 'still', 'swatch', 'learn', 'samples',
  'export', 'doctor', 'undo',
]);
const USAGE = `Usage: node motion-graphics.mjs --root PROJECT_ROOT [--project FILM_DIR] <om-command> <args...>
Runtime: PROJECT_ROOT/.dev/motion-graphics/runtime.json (schema_version 1).
All arguments after the command are forwarded unchanged to the pinned native om CLI.
--root/--project before the command are launcher options. Use "help" for native help.`;
const fail = (message) => { throw new Error(message); };
const hash = (bytes, algorithm = 'sha256', encoding = 'hex') => createHash(algorithm).update(bytes).digest(encoding);
const samePath = (a, b) => process.platform === 'win32' ? a.toLowerCase() === b.toLowerCase() : a === b;
const within = (base, path) => { const r = relative(base, path); return !isAbsolute(r) && r !== '..' && !r.startsWith(`..${sep}`); };

// Resolve existing ancestors too: aliases and symlinks share a scope, even for a new directory.
export function canonicalPath(path) {
  let current = resolve(path);
  const missing = [];
  while (!fs.existsSync(current)) {
    const parent = dirname(current);
    if (parent === current) fail(`Cannot resolve project path: ${path}`);
    missing.unshift(basename(current));
    current = parent;
  }
  return resolve(fs.realpathSync(current), ...missing);
}

export function parseInvocation(argv, cwd = process.cwd()) {
  let root, project, i = 0;
  for (; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--') { i++; break; }
    const key = a.split('=')[0];
    if (key !== '--root' && key !== '--project') break;
    const eq = a.indexOf('=');
    const value = eq >= 0 ? a.slice(eq + 1) : argv[++i];
    if (!value || value.startsWith('--')) fail(`${key} requires a path`);
    if (key === '--root') { if (root) fail('Duplicate --root'); root = value; }
    else { if (project) fail('Duplicate --project'); project = value; }
  }
  if (!root) fail('Explicit --root PROJECT_ROOT is required (including from an installed Skill)');
  const command = argv[i] || 'help';
  if (!COMMANDS.includes(command)) fail(`Unsupported native command: ${command}`);
  return { root: canonicalPath(resolve(cwd, root)), project, command, args: argv.slice(i + 1) };
}

// Only inspect the native parser's result to locate the project; never rebuild its argv.
export function nativeOperands(args) {
  const flags = {}, pos = [];
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a.startsWith('--')) {
      const [key, value] = a.slice(2).split('='); // matches pinned upstream parser
      flags[key] = value !== undefined ? value
        : args[i + 1] && !args[i + 1].startsWith('--') ? args[++i] : true;
    } else pos.push(a);
  }
  return { flags, pos };
}

export function projectScope(invocation) {
  const { root, project, command, args } = invocation;
  const { flags, pos } = nativeOperands(args);
  if (flags.project === true || flags.project === '') fail('--project requires an actual project path');
  const declared = project || (typeof flags.project === 'string' ? flags.project : undefined);
  // With a launcher --project, omitted project operands use that working directory.
  // When operands exist, their relative paths keep their original --root meaning.
  let operand, fileInput = false;
  switch (command) {
    case 'done': case 'reopen': case 'cancel': operand = pos[1]; break;
    case 'look': operand = flags.at ? pos[0] : pos[1]; break;
    case 'set': operand = pos.find((p) => !p.includes('=')); break;
    case 'fonts': operand = pos[0] === 'add' ? pos[2] : undefined; break;
    case 'learn': operand = pos[0] === 'harvest' ? pos[1] : undefined; break;
    case 'export': operand = pos[1]; break;
    // fork creates its second operand: history/learn scope belongs to that new film.
    case 'fork': operand = pos[1] || pos[0]; break;
    case 'qa': operand = pos[0]; fileInput = !!operand && /\.(mp4|mov|webm)$/i.test(operand); break;
    case 'still': case 'swatch':
      operand = pos[0];
      fileInput = command === 'swatch' || (!!operand && /\.html?$/i.test(operand));
      break;
    case 'demo': operand = pos[0] || 'huashu-motion-demo'; break;
    case 'new': case 'studio': case 'inbox': case 'vars': case 'scan':
    case 'render': case 'check': case 'undo': case 'voice': case 'sound': operand = pos[0]; break;
  }
  let target = operand ? canonicalPath(resolve(root, operand)) : undefined;
  if (target && (fileInput || (fs.existsSync(target) && fs.statSync(target).isFile()))) target = dirname(target);
  const explicit = declared ? canonicalPath(resolve(root, declared)) : undefined;
  if (project && typeof flags.project === 'string' && !samePath(explicit, canonicalPath(resolve(root, flags.project)))) {
    fail('Conflicting launcher --project and native --project');
  }
  if (target && explicit && !samePath(target, explicit) && !(fileInput && within(explicit, target))) {
    fail('Project operand conflicts with --project; use one actual project');
  }
  const scope = explicit || target || root;
  let working = operand ? root : explicit || root;
  if (!fs.existsSync(working)) {
    if (!['learn', 'samples', 'doctor', 'help', '--help', '-h', 'version', '--version', '-v'].includes(command)) {
      fail('Explicit project does not exist; create it with new <dir> first');
    }
    working = root; // reading preferences before a film exists must still be possible
  }
  return { project: scope, cwd: working, home: join(scope, '.om', 'huashu-motion') };
}

// The release archive is small and contains only regular npm package entries.
// Reject extra tar features rather than silently accepting links or unsafe paths.
export function archiveFiles(archive, integrity = PACKAGE.integrity) {
  if (`sha512-${hash(archive, 'sha512', 'base64')}` !== integrity) fail('Source archive integrity mismatch');
  const tar = gunzipSync(archive, { maxOutputLength: 64 * 1024 * 1024 });
  const files = new Map();
  let offset = 0;
  const text = (bytes) => bytes.toString('utf8').replace(/\0.*$/s, '');
  while (offset + 512 <= tar.length && tar[offset]) {
    const header = tar.subarray(offset, offset + 512);
    const prefix = text(header.subarray(345, 500));
    const name = (prefix ? `${prefix}/` : '') + text(header.subarray(0, 100));
    const sizeText = text(header.subarray(124, 136)).trim();
    if (!/^[0-7]+$/.test(sizeText)) fail('Invalid source archive size');
    const size = Number.parseInt(sizeText, 8);
    const stored = Number.parseInt(text(header.subarray(148, 156)).trim(), 8);
    const checksum = header.reduce((n, v, i) => n + (i >= 148 && i < 156 ? 32 : v), 0);
    if (stored !== checksum) fail('Invalid source archive header');
    if (!name.startsWith('package/') || /[\\]/.test(name) || name.split('/').includes('..') || ![0, 48].includes(header[156])) {
      fail(`Unsupported source archive entry: ${name}`);
    }
    if (offset + 512 + size > tar.length) fail('Truncated source archive');
    const path = name.slice('package/'.length);
    if (!path || files.has(path)) fail('Duplicate or empty source archive path');
    files.set(path, tar.subarray(offset + 512, offset + 512 + size));
    offset += 512 + Math.ceil(size / 512) * 512;
  }
  if (!files.has('cli/om.js') || !files.has('package.json')) fail('Source archive missing CLI/package.json');
  return files;
}

export function verifySource(root, source) {
  if (!source || source.name !== PACKAGE.name || source.version !== PACKAGE.version || source.integrity !== PACKAGE.integrity) {
    fail('Runtime source must bind the pinned huashu-motion@0.1.1 npm integrity');
  }
  if (typeof source.install_dir !== 'string' || typeof source.archive !== 'string') fail('Source requires install_dir and archive paths');
  const expected = resolve(root, '.dev/tools/huashu-motion-0.1.1');
  const install = canonicalPath(resolve(root, source.install_dir));
  if (!samePath(install, expected)) fail('Source install_dir must be the real project-local .dev/tools/huashu-motion-0.1.1');
  const archive = canonicalPath(resolve(root, source.archive));
  if (!within(resolve(root, '.dev'), archive)) fail('Source archive must be project-local under .dev');
  const files = archiveFiles(fs.readFileSync(archive));
  for (const [path, bytes] of files) {
    const actual = canonicalPath(join(install, path));
    if (!within(install, actual) || !fs.statSync(actual).isFile()) fail(`Source file escapes install_dir: ${path}`);
    if (hash(fs.readFileSync(actual)) !== hash(bytes)) fail(`Installed source differs from pinned release: ${path}`);
  }
  const pkg = JSON.parse(fs.readFileSync(join(install, 'package.json'), 'utf8'));
  if (pkg.name !== PACKAGE.name || pkg.version !== PACKAGE.version || pkg.bin?.om !== 'cli/om.js') fail('Installed package identity/bin mismatch');
  return { cli: join(install, 'cli/om.js'), cli_sha256: hash(files.get('cli/om.js')), install };
}

export function childEnvironment(inherited, runtime, scope) {
  const env = { ...inherited };
  // Windows treats environment keys case-insensitively; Node's spawn does not deduplicate them.
  for (const key of Object.keys(env)) {
    if (['PATH', 'OM_HOME', 'OM_CHROME', 'OM_SAMPLES', 'NODE_OPTIONS', 'NODE_PATH', 'HOME', 'USERPROFILE'].includes(key.toUpperCase())) delete env[key];
  }
  const originalPath = Object.entries(inherited).find(([key]) => key.toUpperCase() === 'PATH')?.[1] || '';
  env.PATH = [dirname(runtime.node), dirname(runtime.ffmpeg), originalPath].filter(Boolean).join(delimiter);
  env.OM_HOME = scope.home;
  env.OM_CHROME = runtime.chrome;
  env.OM_SAMPLES = join(scope.home, 'samples');
  // The upstream optional TTS/ASR cache uses os.homedir(), rather than OM_HOME.
  env.HOME = env.USERPROFILE = join(scope.home, 'home');
  return env;
}

export function prepareLaunch(argv, { cwd = process.cwd(), env = process.env } = {}) {
  const invocation = parseInvocation(argv, cwd);
  if (!fs.statSync(invocation.root).isDirectory()) fail('--root must be an existing directory');
  const manifestPath = join(invocation.root, '.dev/motion-graphics/runtime.json');
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8').replace(/^\uFEFF/, ''));
  if (manifest.schema_version !== 1) fail('Unsupported runtime manifest schema_version (expected 1)');
  const binding = verifySource(invocation.root, manifest.source);
  const runtime = {};
  for (const key of ['node', 'chrome', 'ffmpeg', 'ffprobe']) {
    if (typeof manifest[key] !== 'string' || !manifest[key]) fail(`Runtime manifest requires ${key} path`);
    runtime[key] = canonicalPath(resolve(invocation.root, manifest[key]));
    if (!fs.statSync(runtime[key]).isFile()) fail(`Runtime ${key} must be a file`);
  }
  const privateBin = resolve(invocation.root, '.dev/motion-graphics/bin');
  const ffSuffix = process.platform === 'win32' ? '.exe' : '';
  for (const name of ['ffmpeg', 'ffprobe']) {
    if (!samePath(runtime[name], join(privateBin, name + ffSuffix))) fail(`${name} must be prepared in project-local .dev/motion-graphics/bin/${name}${ffSuffix}`);
  }
  const scope = projectScope(invocation);
  const childEnv = childEnvironment(env, runtime, scope);
  const version = spawnSync(runtime.node, ['--version'], { env: childEnv, encoding: 'utf8', timeout: 10_000, windowsHide: true });
  if (version.error || version.status !== 0 || !/^v(\d+)\./.test(version.stdout || '') || Number(/^v(\d+)\./.exec(version.stdout)[1]) < 22) {
    fail(`Configured process-local Node must be >=22: ${version.error?.message || (version.stdout || version.stderr || '').trim()}`);
  }
  return { executable: runtime.node, args: [binding.cli, invocation.command, ...invocation.args],
    cwd: scope.cwd, env: childEnv, scope, binding };
}

// Inherit streams (including interactive stdin), stay attached, forward shutdown signals.
// Never unref a studio/inbox process or claim completion before it exits.
export function runLaunch(plan, { spawnChild = spawn, signalSource = process } = {}) {
  return new Promise((resolveResult, reject) => {
    const child = spawnChild(plan.executable, plan.args, {
      cwd: plan.cwd, env: plan.env, stdio: 'inherit', shell: false, windowsHide: true,
    });
    const signals = ['SIGINT', 'SIGTERM', 'SIGHUP'];
    const handlers = signals.map((signal) => [signal, () => { if (!child.killed) child.kill(signal); }]);
    for (const [signal, handler] of handlers) signalSource.on(signal, handler);
    const clean = () => { for (const [signal, handler] of handlers) signalSource.removeListener(signal, handler); };
    child.once('error', (error) => { clean(); reject(error); });
    child.once('exit', (code, signal) => {
      clean();
      resolveResult(code ?? ({ SIGINT: 130, SIGTERM: 143, SIGHUP: 129 }[signal] || 1));
    });
  });
}

export async function main(argv = process.argv.slice(2)) {
  if (argv.length === 1 && ['--help', '-h'].includes(argv[0])) { console.log(USAGE); return 0; }
  try { return await runLaunch(prepareLaunch(argv)); }
  catch (error) { console.error(`motion-graphics: ${error.message}`); return 2; }
}
if (process.argv[1] && samePath(resolve(process.argv[1]), fileURLToPath(import.meta.url))) process.exitCode = await main();



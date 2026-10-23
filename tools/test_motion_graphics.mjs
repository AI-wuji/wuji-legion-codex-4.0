import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import * as fs from 'node:fs';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { gzipSync } from 'node:zlib';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import {
  PACKAGE, COMMANDS, parseInvocation, nativeOperands, projectScope, canonicalPath,
  archiveFiles, verifySource, childEnvironment, prepareLaunch, runLaunch,
} from '../legion/skills/wuji-legion-4-0/scripts/motion-graphics.mjs';

// Fixtures stay in memory; this suite creates no films, comments, models or runtime files.
// A fixture result only demonstrates adapter behavior, never professional motion QA.
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const SCRIPT = join(ROOT, 'legion/skills/wuji-legion-4-0/scripts/motion-graphics.mjs');
const root = canonicalPath(ROOT);
const invoke = (command, ...args) => parseInvocation(['--root', ROOT, command, ...args]);
const scope = (command, ...args) => projectScope(invoke(command, ...args));
const homeFor = (path) => join(canonicalPath(path), '.om', 'huashu-motion');

test('requires explicit root from any cwd; rejects unsupported command and malformed launcher options', () => {
  for (const argv of [[], ['doctor'], ['--root'], ['--root', '--project'], ['--root', ROOT, '--root', ROOT], ['--root', ROOT, 'exec']]) {
    assert.throws(() => parseInvocation(argv));
  }
  const inv = parseInvocation(['--root=' + ROOT, 'doctor'], dirname(ROOT));
  assert.equal(inv.root, root);
  assert.equal(inv.command, 'doctor');
  assert.equal(invoke('help').command, 'help');
});

test('native argv remains byte-for-byte string-equivalent, including spaces, Unicode and shell metacharacters', () => {
  const args = ['new film', '--out', 'out dir/a=b.mp4', '--title=a=b', '中文 "x" $() & ;', '--unknown', '--boolean'];
  const inv = invoke('render', ...args);
  assert.deepEqual(inv.args, args);
  assert.equal(inv.args[4], args[4]);
  // These quirks are upstream's parser semantics, not argument rewrites by this adapter.
  assert.deepEqual(nativeOperands(['--at=0', 'film']), { flags: { at: '0' }, pos: ['film'] });
});

test('every native command is reachable through the command boundary', () => {
  for (const command of COMMANDS) assert.equal(invoke(command).command, command);
  assert.equal(new Set(COMMANDS).size, COMMANDS.length);
});

test('projects use actual canonical directories and do not share experience or samples', () => {
  const a = scope('render', 'film a');
  const b = scope('render', 'film b');
  assert.notEqual(a.home, b.home);
  assert.equal(a.home, homeFor(join(root, 'film a')));
  assert.equal(scope('render', './tools/../film a').home, a.home);
  assert.equal(scope('new', 'film a').home, a.home);
  assert.equal(scope('doctor').home, homeFor(root));
  assert.equal(scope('demo').home, homeFor(join(root, 'huashu-motion-demo')));
  assert.equal(scope('learn', 'launch', 'rhythm').home, homeFor(root));
  assert.equal(scope('learn', 'add', 'user prefers quick cuts', '--kind', 'observed').home, homeFor(root));
  assert.equal(scope('learn', '--project', 'film a', 'launch').home, a.home);
  assert.equal(scope('learn', 'status').home, homeFor(root));
});

test('project positions follow native comment, variables, font, export, fork and file forms', () => {
  const p = 'film a', expected = homeFor(join(root, p));
  const cases = [
    ['look', 'comment-id', p], ['look', '--at', '0', p], ['look', p, '--at=2.5'],
    ['done', 'id', p, '--note', 'done locally'], ['reopen', 'id', p], ['cancel', 'id', p],
    ['set', 'headline=a=b', p, 'color=#fff'], ['fonts', 'add', 'Noto Sans SC', p],
    ['learn', 'harvest', p], ['export', 'html', p, '--title', 'Title'], ['fork', 'old film', p, '--size', '1080x1920'],
    ['still', p + '/index.html', '--at', '1,2'], ['swatch', p + '/directions.md'], ['qa', p + '/movie.mp4'],
  ];
  for (const [cmd, ...args] of cases) assert.equal(scope(cmd, ...args).home, expected, JSON.stringify([cmd, ...args]));
});

test('explicit project uses project cwd for omitted operands and rejects misleading cross-project scope', () => {
  const inv = parseInvocation(['--root', ROOT, '--project', 'tools', 'render', '--format', 'mp4']);
  assert.equal(projectScope(inv).cwd, canonicalPath(join(root, 'tools')));
  assert.equal(projectScope(inv).home, homeFor(join(root, 'tools')));
  assert.deepEqual(inv.args, ['--format', 'mp4']);
  assert.throws(() => projectScope(parseInvocation(['--root', ROOT, '--project', 'a', 'render', 'b'])), /conflicts/);
  assert.throws(() => projectScope(parseInvocation(['--root', ROOT, '--project', 'a', 'learn', '--project', 'b'])), /Conflicting/);
  assert.equal(scope('render', 'film a', '--project', 'film a').home, homeFor(join(root, 'film a')));
  const beforeNew = projectScope(parseInvocation(['--root', ROOT, '--project', 'not-yet-created-film', 'learn', 'launch']));
  assert.equal(beforeNew.cwd, root);
  assert.equal(beforeNew.home, homeFor(join(root, 'not-yet-created-film')));
  assert.throws(() => projectScope(parseInvocation(['--root', ROOT, '--project', 'not-yet-created-film', 'render'])), /does not exist/);
  assert.equal(scope('qa', 'film a/out/movie.mp4', '--project', 'film a').home, homeFor(join(root, 'film a')));
  assert.throws(() => scope('learn', '--project'), /actual project path/);
});

test('environment injection is private, overrides inherited scopes and handles Windows Path casing', () => {
  const original = { Path: 'original-path', OM_HOME: 'shared', OM_SAMPLES: 'shared-samples', OM_CHROME: 'wrong',
    NODE_OPTIONS: '--require unsafe', NODE_PATH: 'unsafe', USERPROFILE: 'shared-user', KEEP: 'yes' };
  const saved = { ...original };
  const runtime = { node: join(root, 'node-bin/node.exe'), ffmpeg: join(root, 'private-bin/ffmpeg.exe'), chrome: join(root, 'chrome.exe') };
  const env = childEnvironment(original, runtime, scope('render', 'film a'));
  assert.deepEqual(original, saved);
  assert.equal(env.Path, undefined);
  assert.equal(env.NODE_OPTIONS, undefined);
  assert.equal(env.NODE_PATH, undefined);
  assert.equal(env.KEEP, 'yes');
  assert.equal(env.OM_HOME, homeFor(join(root, 'film a')));
  assert.equal(env.OM_CHROME, runtime.chrome);
  assert.equal(env.OM_SAMPLES, join(env.OM_HOME, 'samples'));
  assert.equal(env.HOME, join(env.OM_HOME, 'home'));
  assert.equal(env.USERPROFILE, env.HOME);
  assert.ok(env.PATH.startsWith(dirname(runtime.node)));
  assert.ok(env.PATH.endsWith('original-path'));
});

function makeTar(files) {
  const blocks = [];
  for (const [path, data] of files) {
    const content = Buffer.from(data), header = Buffer.alloc(512);
    header.write('package/' + path);
    header.write(content.length.toString(8).padStart(11, '0') + '\0', 124);
    header.fill(32, 148, 156);
    header[156] = 48;
    const sum = header.reduce((n, v) => n + v, 0);
    header.write(sum.toString(8).padStart(6, '0') + '\0 ', 148);
    blocks.push(header, content, Buffer.alloc((512 - content.length % 512) % 512));
  }
  return gzipSync(Buffer.concat([...blocks, Buffer.alloc(1024)]));
}
const integrity = (bytes) => 'sha512-' + createHash('sha512').update(bytes).digest('base64');

test('archive validation detects corruption, traversal and duplicate entries before source execution', () => {
  const data = [['package.json', '{}'], ['cli/om.js', 'console.log("fixture")']];
  const tar = makeTar(data);
  assert.equal(archiveFiles(tar, integrity(tar)).get('cli/om.js').toString(), data[1][1]);
  assert.throws(() => archiveFiles(tar), /integrity mismatch/); // fixture can never satisfy release pin
  const bad = Buffer.from(tar); bad[10] ^= 1;
  assert.throws(() => archiveFiles(bad, integrity(tar)), /integrity mismatch/);
  const traversal = makeTar([...data, ['../escape', 'x']]);
  assert.throws(() => archiveFiles(traversal, integrity(traversal)), /Unsupported/);
  const duplicate = makeTar([...data, ['cli/om.js', 'different']]);
  assert.throws(() => archiveFiles(duplicate, integrity(duplicate)), /Duplicate/);
  assert.throws(() => verifySource(root, { ...PACKAGE, version: '9.9.9' }), /pinned/);
  assert.throws(() => verifySource(root, { ...PACKAGE, install_dir: '../foreign', archive: 'unused' }), /project-local/);
});

test('spawn forwards argv/streams, native failure and signal cleanup without detached studio', async () => {
  const source = new EventEmitter(), child = new EventEmitter();
  let observed, killed;
  child.kill = (signal) => { killed = signal; child.killed = true; queueMicrotask(() => child.emit('exit', null, signal)); };
  const plan = { executable: process.execPath, args: ['cli.js', 'studio', 'film with spaces', '--no-open'], cwd: root, env: { MARK: 'x' } };
  const pending = runLaunch(plan, { signalSource: source, spawnChild: (...args) => { observed = args; return child; } });
  assert.deepEqual(observed.slice(0, 2), [plan.executable, plan.args]);
  assert.deepEqual(observed[2], { cwd: root, env: plan.env, stdio: 'inherit', shell: false, windowsHide: true });
  source.emit('SIGTERM');
  assert.equal(killed, 'SIGTERM');
  assert.equal(await pending, 143);
  for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) assert.equal(source.listenerCount(signal), 0);
  const failed = new EventEmitter();
  const exit = runLaunch(plan, { signalSource: source, spawnChild: () => failed });
  failed.emit('exit', 7, null);
  assert.equal(await exit, 7);
  const broken = new EventEmitter();
  const error = runLaunch(plan, { signalSource: source, spawnChild: () => broken });
  broken.emit('error', new Error('ENOENT fixture'));
  await assert.rejects(error, /ENOENT/);
  assert.equal(source.listenerCount('SIGTERM'), 0);
});

test('real child failure is preserved and missing native executable rejects', async () => {
  const result = await runLaunch({ executable: process.execPath, args: ['-e', 'process.exit(7)'], cwd: root, env: process.env });
  assert.equal(result, 7);
  await assert.rejects(runLaunch({ executable: join(root, 'nonexistent-node-executable'), args: [], cwd: root, env: process.env }), /ENOENT/);
});

test('CLI rejects missing root/unknown command nonzero without an installed runtime', () => {
  for (const argv of [[], ['--root', ROOT, 'not-a-native-command']]) {
    const r = spawnSync(process.execPath, [SCRIPT, ...argv], { encoding: 'utf8', windowsHide: true });
    assert.equal(r.status, 2);
    assert.match(r.stderr, /motion-graphics:/);
  }
});

test('real child preserves stdout/stderr, Unicode/metacharacter argv and native nonzero status', () => {
  const childArgs = ['中文 a=b', '$() & ; "quotes"', '--unknown=raw'];
  const code = `import { runLaunch } from ${JSON.stringify(new URL('../legion/skills/wuji-legion-4-0/scripts/motion-graphics.mjs', import.meta.url).href)};
    const args = ${JSON.stringify(childArgs)};
    process.exitCode = await runLaunch({ executable: process.execPath,
      args: ['-e', 'console.log(JSON.stringify(process.argv.slice(1))); console.error("native stderr"); process.exit(7)', '--', ...args],
      cwd: process.cwd(), env: process.env });`;
  const r = spawnSync(process.execPath, ['--input-type=module', '-e', code], { cwd: root, encoding: 'utf8', windowsHide: true });
  assert.equal(r.status, 7);
  assert.deepEqual(JSON.parse(r.stdout), childArgs);
  assert.equal(r.stderr.trim(), 'native stderr');
});
const manifestExists = fs.existsSync(join(ROOT, '.dev/motion-graphics/runtime.json'));
test('optional real installed release binding and native version (read-only, no professional QA claim)', { skip: !manifestExists }, () => {
  const nativeArgs = ['film a', '--out', 'out dir/a=b.mp4', '--frames', 'png', '--unknown=raw'];
  const forwarded = prepareLaunch(['--root', ROOT, 'render', ...nativeArgs]);
  assert.deepEqual(forwarded.args.slice(1), ['render', ...nativeArgs]);
  const p = prepareLaunch(['--root', ROOT, 'version']);
  assert.match(p.binding.cli_sha256, /^[a-f0-9]{64}$/);
  assert.equal(p.env.OM_HOME, homeFor(root));
  const r = spawnSync(p.executable, p.args, { cwd: p.cwd, env: p.env, encoding: 'utf8', windowsHide: true });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.stdout.trim(), PACKAGE.version);
  // Source/installed Skill invocation works independently from the caller's cwd.
  const outside = spawnSync(process.execPath, [SCRIPT, '--root', ROOT, 'version'], {
    cwd: dirname(ROOT), encoding: 'utf8', windowsHide: true,
  });
  assert.equal(outside.status, 0, outside.stderr);
  assert.equal(outside.stdout.trim(), PACKAGE.version);
});



const upstreamCli = join(ROOT, '.dev/tools/huashu-motion-0.1.1/cli/om.js');
test('allowlist covers the pinned upstream HELP and switch independently of the adapter list', {
  skip: !fs.existsSync(upstreamCli),
}, () => {
  const source = fs.readFileSync(upstreamCli, 'utf8');
  const nativeSwitch = source.slice(source.indexOf('switch (cmd) {'), source.indexOf('// Rendering knobs'));
  const switchCommands = [...new Set([...nativeSwitch.matchAll(/\bcase\s+'([^']+)'\s*:/g)].map((m) => m[1]))];
  assert.ok(switchCommands.length > 20, 'expected actual upstream command switch');
  assert.deepEqual([...COMMANDS].sort(), switchCommands.sort(), 'missing or invented native command');
  const nativeHelp = source.slice(source.indexOf('const HELP ='), source.indexOf('function parse('));
  const helpCommands = [...new Set([...nativeHelp.matchAll(/^\s+om\s+([a-z]+)/gm)].map((m) => m[1]))];
  assert.ok(helpCommands.includes('undo'), 'regression must exercise upstream undo declaration');
  for (const command of helpCommands) assert.ok(COMMANDS.includes(command), `native HELP command missing: ${command}`);
});

test('real undo dispatch preserves project argv and isolated scope, then forwards native missing-project failure', {
  skip: !manifestExists,
}, () => {
  // An absent project deliberately makes native openProject fail before undo can write.
  // Never run undo against the live film or create a fixture project outside the write set.
  const project = `.dev/adapter-undo-no-project-${process.pid}`;
  const another = project + '-other';
  assert.equal(fs.existsSync(join(ROOT, project)), false);
  const p = prepareLaunch(['--root', ROOT, 'undo', project]);
  const q = prepareLaunch(['--root', ROOT, 'undo', another]);
  assert.deepEqual(p.args, [upstreamCli, 'undo', project]);
  assert.equal(p.cwd, root);
  assert.equal(p.env.OM_HOME, homeFor(join(root, project)));
  assert.equal(q.env.OM_HOME, homeFor(join(root, another)));
  assert.notEqual(p.env.OM_HOME, q.env.OM_HOME);
  assert.throws(() => prepareLaunch(['--root', ROOT, '--project', another, 'undo', project]), /conflicts/);
  const direct = spawnSync(p.executable, p.args, { cwd: p.cwd, env: p.env, encoding: 'utf8', windowsHide: true });
  const wrapped = spawnSync(process.execPath, [SCRIPT, '--root', ROOT, 'undo', project], {
    cwd: dirname(ROOT), encoding: 'utf8', windowsHide: true,
  });
  assert.equal(direct.status, 1, direct.stderr);
  assert.equal(wrapped.status, direct.status, wrapped.stderr);
  assert.equal(wrapped.stdout, direct.stdout);
  assert.equal(wrapped.stderr, direct.stderr);
  assert.match(wrapped.stderr, /no index\.html/);
  assert.doesNotMatch(wrapped.stderr, /Unsupported native command/);
  assert.equal(fs.existsSync(join(ROOT, project)), false, 'no project or OM_HOME may be created by this failure');
});

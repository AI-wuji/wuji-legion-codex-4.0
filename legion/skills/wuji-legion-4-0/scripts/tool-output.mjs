// Task-local output artifacts; no scheduler, database, hooks or model calls.
import {readFileSync, writeFileSync, realpathSync, mkdirSync, statSync, openSync, closeSync} from 'node:fs';
import {resolve, relative, dirname, isAbsolute} from 'node:path';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';

const MAX_BYTES = 64 * 1024 * 1024;
const MAX_PAGE = 8192;
export const hash = bytes => createHash('sha256').update(bytes).digest('hex');
function inside(root, candidate) {
  const rel = relative(root, candidate);
  if (rel === '..' || rel.startsWith('..\\') || rel.startsWith('../') || isAbsolute(rel))
    throw new Error('Artifact path escapes the authorized workspace');
  return candidate;
}
function filePath(workspace, name, writing = false) {
  if (!name || isAbsolute(name)) throw new Error('Artifact must use a workspace-relative path');
  const root = realpathSync(workspace);
  const file = inside(root, resolve(root, name));
  if (!writing) return inside(root, realpathSync(file));
  // Check each existing parent before creating another: never mkdir through an external junction.
  let parent = root;
  for (const part of relative(root, dirname(file)).split(/[\\/]/).filter(Boolean)) {
    parent = resolve(parent, part);
    try { inside(root, realpathSync(parent)); }
    catch (error) {
      if (error.code !== 'ENOENT') throw error;
      mkdirSync(parent);
      inside(root, realpathSync(parent));
    }
  }
  return file;
}
function boundedRead(file) {
  if (statSync(file).size > MAX_BYTES) throw new Error('Artifact exceeds the 64 MiB local helper limit');
  const bytes = readFileSync(file);
  if (bytes.length > MAX_BYTES) throw new Error('Artifact grew beyond the local helper limit');
  return bytes;
}
const criticalKey = /^(?:errors?|(?:[a-z]+_)?errors|errorInfo|isError|stderr|exit_?code|signal|(?:[a-z]+_)?state|status|success|ok|complete|isComplete|permissions?|authority|authori[sz]ation|safety|security|approval|denied|blocked|warnings?|unknowns?|output_complete|critical_fields_complete|[a-z_]*(?:complete|incomplete))$/i;
function criticalFields(value) {
  const fields = [];
  let examined = 0, incomplete = false;
  function visit(item, pointer = '', depth = 0) {
    if (!item || typeof item !== 'object') return;
    if (depth > 32 || ++examined > 50000) { incomplete = true; return; }
    for (const [key, child] of Object.entries(item)) {
      const path = pointer + '/' + key.replace(/~/g, '~0').replace(/\//g, '~1');
      if (criticalKey.test(key)) {
        const encoded = JSON.stringify(child);
        if (Buffer.byteLength(path) > 240 || fields.length >= 24 || Buffer.byteLength(encoded) > 800 ||
            Buffer.byteLength(JSON.stringify([...fields, {pointer:path,value:child}])) > 2800) {
          incomplete = true;
          continue;
        }
        fields.push({pointer: path, value: child});
      } else visit(child, path, depth + 1);
    }
  }
  visit(value);
  return {fields, incomplete};
}
export function summarize(workspace, name) {
  const file = filePath(workspace, name);
  const bytes = boundedRead(file);
  let value, format = 'binary-or-text';
  try { value = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes)); format = 'json'; }
  catch { /* no false JSON completeness guarantee */ }
  const critical = value === undefined ? {fields: [], incomplete: true} : criticalFields(value);
  // An exit code is process state, not proof that the encoded stdout has been read.
  if (value?.stdout_base64) critical.incomplete = true;
  const topKeys=[];let keysIncomplete=false;
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    for (const key of Object.keys(value)) {
      if (Buffer.byteLength(key)>100 || Buffer.byteLength(JSON.stringify([...topKeys,key]))>512) { keysIncomplete=true; break; }
      topKeys.push(key);
    }
  }
  return {
    kind: 'wuji-tool-output-artifact', file, sha256: hash(bytes), total_bytes: bytes.length,
    format, critical_field_scope: 'recognized JSON status/error/permission keys; arbitrary schemas need original readback', top_level_keys: topKeys, top_level_keys_incomplete: keysIncomplete,
    critical_fields: critical.fields, critical_fields_complete: !critical.incomplete,
    summary_is_full_evidence: false, read_required: critical.incomplete, execution_authority: false,
    next: {command: 'read', workspace: realpathSync(workspace), file: name, sha256: hash(bytes), offset: 0, bytes: 4096},
    measurement: {artifact_bytes: bytes.length, tokens: 'unknown', fees: 'unknown'},
  };
}
export function readPage(workspace, name, expectedHash, offset = 0, size = 4096) {
  if (!/^[a-f0-9]{64}$/.test(expectedHash ?? '')) throw new Error('Exact sha256 is required');
  if (!Number.isSafeInteger(offset) || offset < 0 || !Number.isInteger(size) || size < 1 || size > MAX_PAGE)
    throw new Error('Page offset/size invalid; size must be 1..8192 bytes');
  const file = filePath(workspace, name), raw = boundedRead(file);
  if (hash(raw) !== expectedHash) throw new Error('Artifact changed: stale sha256');
  if (offset > raw.length) throw new Error('Offset is beyond the artifact');
  const end = Math.min(raw.length, offset + size);
  const page = raw.subarray(offset, end);
  // Base64 preserves all binary/UTF-8 boundaries; UTF-8 is a convenience only when exact.
  let text;
  try { text = new TextDecoder('utf-8', {fatal:true, ignoreBOM:true}).decode(page);
    if (Buffer.byteLength(JSON.stringify(text)) > Math.ceil(size * 4 / 3) + 16) text = undefined;
  } catch {}
  return {file, sha256: expectedHash, total_bytes: raw.length, offset, next_offset:end,
    complete:end === raw.length, ...(text === undefined ? {page_base64:page.toString('base64')} : {text}),
    execution_authority:false};
}
export function capture(workspace, name, command) {
  if (!command.length) throw new Error('capture requires an explicit program after --');
  const file = filePath(workspace, name, true);
  // Reserve before executing: duplicate receipts must never replay a side-effecting command.
  const fd = openSync(file, 'wx', 0o600);
  try {
  const result = spawnSync(command[0], command.slice(1), {
    cwd: realpathSync(workspace), shell:false, windowsHide:true, encoding:null,
    maxBuffer:MAX_BYTES / 4, timeout:120000,
  });
  const raw = Buffer.from(JSON.stringify({
    exit_code:result.status, signal:result.signal,
    error:result.error ? {code:result.error.code ?? null, message:result.error.message} : null,
    stdout_base64:(result.stdout ?? Buffer.alloc(0)).toString('base64'),
    stderr_base64:(result.stderr ?? Buffer.alloc(0)).toString('base64'),
    // Keep failed command stderr readable in the bounded receipt, or require readback.
    stderr:(result.stderr ?? Buffer.alloc(0)).toString('utf8'),
    output_complete:!result.error,
  }));
  if (raw.length > MAX_BYTES) throw new Error('Captured envelope exceeds artifact limit');
  writeFileSync(fd, raw);
  return {...summarize(workspace, name), captured_process:{exit_code:result.status, signal:result.signal,
    output_complete:!result.error}, success:result.status === 0 && !result.error};
  } finally { closeSync(fd); }
}
export function selectField(workspace, name, expectedHash, pointer) {
  const file = filePath(workspace, name), raw = boundedRead(file);
  if (!/^[a-f0-9]{64}$/.test(expectedHash ?? '') || hash(raw) !== expectedHash)
    throw new Error('Exact current sha256 is required');
  if (typeof pointer !== 'string' || !pointer.startsWith('/') || pointer.length > 1024 || /~(?![01])/u.test(pointer))
    throw new Error('Use an exact JSON pointer');
  let selected = JSON.parse(new TextDecoder('utf-8', {fatal:true}).decode(raw));
  for (const segment of pointer.slice(1).split('/').map(s => s.replace(/~1/g,'/').replace(/~0/g,'~'))) {
    if (!selected || typeof selected !== 'object' || !Object.hasOwn(selected, segment)) throw new Error('JSON pointer not found');
    selected = selected[segment];
  }
  if (Buffer.byteLength(JSON.stringify(selected)) > 4096)
    return {file, sha256:expectedHash, pointer, selected_omitted:true, read_required:true,
      reason:'Field exceeds 4096-byte budget; choose a narrower pointer or read byte pages', execution_authority:false};
  return {file, sha256:expectedHash, pointer, selected, selection_is_full_file:false, execution_authority:false};
}
export function main(args) {
  const action=args.shift(), split=args.indexOf('--');
  const command=split < 0 ? [] : args.splice(split).slice(1);
  const options={};
  if (args.length % 2) throw new Error('Options must be --key value pairs');
  const allowed=new Set(['workspace','file','sha256','offset','bytes','pointer']);
  for(let i=0;i<args.length;i+=2) {
    const key=args[i].slice(2);
    if (!args[i].startsWith('--') || !allowed.has(key) || Object.hasOwn(options,key)) throw new Error('Unknown or repeated option');
    options[key]=args[i+1];
  }
  if (!options.workspace || !options.file) throw new Error('--workspace and --file are required');
  if(action==='summarize') return summarize(options.workspace, options.file);
  if(action==='read') return readPage(options.workspace, options.file, options.sha256,
    Number(options.offset ?? 0), Number(options.bytes ?? 4096));
  if(action==='select') return selectField(options.workspace, options.file, options.sha256, options.pointer);
  if(action==='capture') return capture(options.workspace, options.file, command);
  throw new Error('Use summarize, read, select or capture');
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try { const result=main(process.argv.slice(2)); console.log(JSON.stringify(result));
    if (result.success === false) process.exitCode=1;
  } catch(error) { console.error(JSON.stringify({success:false,error:error.message})); process.exitCode=1; }
}

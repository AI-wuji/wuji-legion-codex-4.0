import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdirSync, mkdtempSync, writeFileSync, readFileSync, symlinkSync} from 'node:fs';
import {resolve, join} from 'node:path';
import {summarize, readPage, selectField, capture, hash} from '../legion/skills/wuji-legion-4-0/scripts/tool-output.mjs';

mkdirSync('.dev/context-output-tests', {recursive:true});
function workspace() {return mkdtempSync(resolve('.dev/context-output-tests/task-'));}
function fixture() {
  const root=workspace(), name='raw.json';
  const value={payload:'原始🧭資料'.repeat(14000), detail:{state:'failed',success:false,complete:false,approval:'denied',
    errors:[{kind:'AuthorityDenied',detail:'cannot publish'}], permissions:{allowed:['read'],denied:['charge','publish']}}};
  const raw=Buffer.from(JSON.stringify(value));writeFileSync(join(root,name),raw);
  return {root,name,value,raw};
}
test('large output has nested critical fields, compact receipt, and exact Unicode readback',()=>{
  const f=fixture(), receipt=summarize(f.root,f.name);
  assert.equal(receipt.sha256,hash(f.raw));assert.equal(receipt.critical_fields_complete,true);
  assert.deepEqual(receipt.critical_fields.find(x=>x.pointer==='/detail/permissions').value,f.value.detail.permissions);
  assert.equal(receipt.critical_fields.find(x=>x.pointer==='/detail/state').value,'failed');
  for (const [key,value] of Object.entries({success:false,complete:false,approval:'denied'}))
    assert.equal(receipt.critical_fields.find(x=>x.pointer==='/detail/'+key).value,value);
  assert.equal(receipt.summary_is_full_evidence,false);assert.equal(receipt.measurement.tokens,'unknown');
  assert.ok(Buffer.byteLength(JSON.stringify(receipt))<f.raw.length / 10);
  const chunks=[];let offset=0;
  do {const page=readPage(f.root,f.name,receipt.sha256,offset,127);
    chunks.push(page.text===undefined?Buffer.from(page.page_base64,'base64'):Buffer.from(page.text));
    offset=page.next_offset;assert.equal(page.sha256,receipt.sha256);
    if(page.complete)break;
  } while(true);
  assert.deepEqual(Buffer.concat(chunks),f.raw);
});
test('stale, invalid size/offset and traversal references are rejected',()=>{
  const f=fixture(), r=summarize(f.root,f.name);
  for(const [offset,size] of [[-1,20],[0,0],[0,8193],[r.total_bytes+1,10]])
    assert.throws(()=>readPage(f.root,f.name,r.sha256,offset,size));
  assert.throws(()=>summarize(f.root,'../other.json'),/escapes/);
  assert.throws(()=>readPage(f.root,f.name,'forged',0,20),/sha256/);
  writeFileSync(join(f.root,f.name),'changed');
  assert.throws(()=>readPage(f.root,f.name,r.sha256,0,10),/stale/);
});
test('large critical fields and unstructured logs require readback',()=>{
  const root=workspace();writeFileSync(join(root,'long.json'),JSON.stringify({errors:['x'.repeat(9000)],permissions:{denied:['all']}}));
  const r=summarize(root,'long.json');assert.equal(r.critical_fields_complete,false);assert.equal(r.read_required,true);
  assert.ok(JSON.stringify(r).length<4096);
  writeFileSync(join(root,'log.txt'),'Warning: no permission\n'+'log\n'.repeat(4000));
  assert.equal(summarize(root,'log.txt').read_required,true);
});
test('capture preserves failed process stdout/stderr and never overwrites an artifact',()=>{
  const root=workspace();const r=capture(root,'task/output.json',[process.execPath,'-e',
    'process.stdout.write("z".repeat(25000));process.stderr.write("permission denied");process.exit(7)']);
  assert.equal(r.success,false);assert.equal(r.captured_process.exit_code,7);
  const original=JSON.parse(readFileSync(join(root,'task/output.json'),'utf8'));
  assert.equal(Buffer.from(original.stdout_base64,'base64').length,25000);
  assert.equal(Buffer.from(original.stderr_base64,'base64').toString(),'permission denied');
  assert.ok(r.critical_fields.some(x=>x.pointer==='/stderr'&&x.value==='permission denied'));
  assert.throws(()=>capture(root,'task/output.json',[process.execPath,'-e',
    'require("node:fs").writeFileSync("replayed.txt","forbidden replay")']),/EEXIST/);
  assert.throws(()=>readFileSync(join(root,'replayed.txt')),/ENOENT/);
});
test('junctions outside the workspace cannot be read or used as capture destinations',()=>{
  const root=workspace(), outside=workspace();writeFileSync(join(outside,'secret.txt'),'not authorized');
  symlinkSync(outside,join(root,'linked'),process.platform==='win32'?'junction':'dir');
  assert.throws(()=>summarize(root,'linked/secret.txt'),/escapes/);
  assert.throws(()=>capture(root,'linked/new/output.json',[process.execPath,'-e','console.log(1)']),/escapes/);
});

test('exact JSON selection bounds output, rejects stale versions and does not invent missing fields',()=>{
 const f=fixture(),r=summarize(f.root,f.name);
 const result=selectField(f.root,f.name,r.sha256,'/detail/errors/0/kind');
 assert.equal(result.selected,'AuthorityDenied');assert.equal(result.selection_is_full_file,false);
 assert.equal(selectField(f.root,f.name,r.sha256,'/payload').selected_omitted,true);
 assert.throws(()=>selectField(f.root,f.name,r.sha256,'/detail/missing'),/not found/);
 assert.throws(()=>selectField(f.root,f.name,r.sha256,'/bad~2key'),/pointer/);
 writeFileSync(join(f.root,f.name),'changed');
 assert.throws(()=>selectField(f.root,f.name,r.sha256,'/payload'),/sha256/);
});

test('binary, BOM and control characters are lossless, and failed startup has a durable failure receipt',()=>{
 const root=workspace();const raw=Buffer.from([239,187,191,0,0,255,128,1]);
 writeFileSync(join(root,'binary.dat'),raw);const r=summarize(root,'binary.dat');
 const first=readPage(root,'binary.dat',r.sha256,0,3);
 assert.deepEqual(first.text===undefined?Buffer.from(first.page_base64,'base64'):Buffer.from(first.text),raw.subarray(0,3));
 const binary=readPage(root,'binary.dat',r.sha256,3,5);assert.deepEqual(Buffer.from(binary.page_base64,'base64'),raw.subarray(3));
 const receipt=capture(root,'missing.json',['wuji-nonexistent-command-20261014']);
 assert.equal(receipt.success,false);assert.equal(receipt.captured_process.output_complete,false);
 assert.ok(JSON.parse(readFileSync(join(root,'missing.json'),'utf8')).error);
});

import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

function load() {
  const module={exports:{}}
  const code=ts.transpileModule(readFileSync(new URL('../src/utils/importDrop.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText
  vm.runInNewContext(code,{module,exports:module.exports})
  return module.exports
}
const entry = (name) => ({name,isFile:true,isDirectory:false,file:resolve=>resolve({name,size:10})})

test('folder drop reads every reader page and preserves nested relative paths',async()=>{
  const {collectDroppedFiles}=load()
  const batches=[[entry('a.xls')],[{name:'nested',isDirectory:true,isFile:false,createReader:()=>{let n=0;return {readEntries:resolve=>resolve(n++?[]:[entry('b.zip')])}}}],[]]
  const folder={name:'资料',isDirectory:true,isFile:false,createReader:()=>({readEntries:resolve=>resolve(batches.shift()||[])})}
  const files=await collectDroppedFiles({items:[{kind:'file',webkitGetAsEntry:()=>folder}],files:[]})
  assert.deepEqual(Array.from(files,f=>f.webkitRelativePath),['资料/a.xls','资料/nested/b.zip'])
})

test('normal file drop falls back when directory entry API is unavailable',async()=>{
  const {collectDroppedFiles}=load()
  const zip={name:'课表.zip'}
  const result=await collectDroppedFiles({items:[],files:[zip]})
  assert.equal(result[0],zip)
})

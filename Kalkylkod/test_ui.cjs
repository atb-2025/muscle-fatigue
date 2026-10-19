// Behaviour checks with a small DOM stub; this is not visual browser verification.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(__dirname+'/index.html','utf8');
const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
function element(){const classes=new Set();return {value:'',textContent:'',disabled:false,open:false,children:[],style:{},dataset:{},attributes:{},setAttribute(k,v){this.attributes[k]=v},removeAttribute(k){delete this.attributes[k]},clientWidth:400,clientHeight:240,
classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),toggle(x,yes){if(yes===undefined)yes=!classes.has(x);yes?classes.add(x):classes.delete(x)},contains:x=>classes.has(x)},
append(...a){this.children.push(...a)},replaceChildren(){this.children=[]},showModal(){this.open=true},close(){this.open=false},focus(){},select(){},scrollIntoView(){},addEventListener(){},
getContext(){return new Proxy({},{get:(o,k)=>o[k]||(()=>{}),set:(o,k,v)=>(o[k]=v,true)})}};}
const elements=Object.fromEntries(ids.map(id=>[id,element()]));
const pending={id:'a'.repeat(32),name:'Test',duration:5,n_samples:10000,source:'TEST'};
let requests=[],failSave=false,failDelete=false,confirmDelete=true;
const result={...pending,date:'2026-10-18T16:00:00',overall_rms:1,overall_mav:.8,fs:2000,notes:[],t:[],rms:[],mav:[],signal_t:[],signal_v:[]};
const second={...result,id:'b'.repeat(32),name:'Ben <test>',fatigue:'Mycket trött'};
let rows=[result];
const idle={active:false,status:'Redo',n:0,elapsed:0,pin:null,rms:null,mav:null,t:[],v:[],index:{score:null,label:'Väntar'},calibration:{phase:'idle',progress:0,instruction:'Starta'}};
const sandbox={console,devicePixelRatio:1,setInterval(){},window:{addEventListener(){}},confirm:()=>confirmDelete,
document:{getElementById:id=>elements[id],querySelectorAll:()=>[],createElement:element},
fetch:async(path,opts)=>{
  requests.push([path,opts]);
  if(path==='/api/pending/save'&&failSave)return {ok:false,json:async()=>({error:'Disk full'})};
  if(path==='/api/delete'&&failDelete)return {ok:false,json:async()=>({error:'Kunde inte radera'})};
  let j={ok:true};
  if(path==='/api/status')j=idle;
  if(path==='/api/analyses')j=rows;
  if(path==='/api/pending/save')j=result;
  if(path.startsWith('/api/analysis/'))j=rows.find(a=>a.id===path.split('/').pop());
  if(path==='/api/delete')rows=rows.filter(a=>a.id!==JSON.parse(opts.body).id);
  if(path==='/api/edit'){const d=JSON.parse(opts.body);rows=rows.map(a=>a.id===d.id?{...a,...d}:a);j=rows.find(a=>a.id===d.id)}
  return {ok:true,json:async()=>j}
}};
vm.createContext(sandbox);vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],sandbox);
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{await tick();vm.runInContext('offerSave('+JSON.stringify(pending)+')',sandbox);
assert.equal(elements.saveDialog.open,true);elements.saveName.value='Biceps';elements.saveComment.value='8 kg';
await vm.runInContext('decideRecording(true)',sandbox);assert.equal(elements.saveDialog.open,false);assert.equal(vm.runInContext('tab',sandbox),'history');assert.equal(elements.history.children.length,1);assert.equal(JSON.parse(requests.find(x=>x[0]==='/api/pending/save')[1].body).name,'Biceps');
vm.runInContext('offerSave('+JSON.stringify(pending)+')',sandbox);await vm.runInContext('decideRecording(false)',sandbox);assert.equal(elements.saveDialog.open,false);assert.ok(requests.some(x=>x[0]==='/api/pending/discard'));
vm.runInContext('offerSave('+JSON.stringify(pending)+')',sandbox);failSave=true;await vm.runInContext('decideRecording(true)',sandbox);assert.equal(elements.saveDialog.open,true);assert.equal(elements.saveError.textContent,'Disk full');assert.equal(elements.saveRecording.disabled,false);
// Exercise actual row buttons, not just helper calls.
rows=[result,second];await vm.runInContext('history()',sandbox);
let [firstRow,secondRow]=elements.history.children;
assert.equal(firstRow.children[0].children[0].children.length,1); // no label
assert.equal(secondRow.children[0].children[0].children[1].textContent,'Mycket trött');
assert.equal(secondRow.children[0].children[0].children[0].textContent,'Ben <test>');
await firstRow.children[1].children[0].onclick();
assert.equal(firstRow.classList.contains('selected'),true);
await secondRow.children[1].children[0].onclick();
assert.equal(firstRow.classList.contains('selected'),false);
assert.equal(secondRow.classList.contains('selected'),true);
assert.equal(secondRow.attributes['aria-current'],'true');
confirmDelete=false;const before=requests.length;
await secondRow.children[1].children[1].onclick();assert.equal(requests.length,before);
confirmDelete=true;failDelete=true;
await secondRow.children[1].children[1].onclick();
assert.equal(elements.history.children.length,2);assert.equal(elements.error.textContent,'Kunde inte radera');
assert.equal(vm.runInContext('current.id',sandbox),second.id);
failDelete=false;
// Deleting another row leaves the open result selected.
await firstRow.children[1].children[1].onclick();
assert.equal(elements.history.children.length,1);assert.equal(vm.runInContext('current.id',sandbox),second.id);
assert.equal(elements.history.children[0].classList.contains('selected'),true);
elements.editName.value=second.name;elements.fatigue.value='Lite trött';
await elements.saveEdit.onclick();
assert.equal(elements.history.children[0].children[0].children[0].children[1].textContent,'Lite trött');
// Delete the open analysis: both the row and its result disappear.
await elements.history.children[0].children[1].children[1].onclick();
assert.equal(vm.runInContext('current',sandbox),null);
assert.equal(elements.result.classList.contains('hidden'),true);
assert.equal(elements.history.children[0].className,'empty');
console.log('UI event tests passed: recording dialog, selection, labels, edit, delete, cancel and failure');
})().catch(e=>{console.error(e);process.exitCode=1});

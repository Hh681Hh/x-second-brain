/* Node's built-in test runner. DOM/protocol fixtures only, no mocked AI success. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');
const directory=path.join(__dirname,'../xsecondbrain/browser_extension');
const core=require(path.join(directory,'clipper-core.js'));
function root({text='这是明确标记的原创测试样例。先保留资料出处，再检索相关段落，证据不足需要人工处理。',more=false,card=false,rich=false,id='0'}={}){
  const time={getAttribute:key=>key==='datetime'?'2026-10-20T00:00:00Z':'',closest:selector=>selector==='a[href]'?{getAttribute:()=>'/fixture/status/'+id}:null};
  const body={innerText:text};
  return {querySelectorAll(selector){return selector==='time'?[time]:selector.includes('show-more')&&more?[{closest:()=>null}]:[];},querySelector(selector){
    if(selector==='time')return time;
    if(selector.includes('RichText')||selector.includes('longformRichText'))return rich?body:null;
    if(selector==='[data-testid="tweetText"]')return body;
    if(selector.includes('show-more'))return more?{}:null;
    if(selector.includes('a[href*='))return card?{}:null;
    if(selector==='[data-testid="User-Name"]')return {innerText:'测试作者\n@fixture'};
    if(selector.startsWith('h1'))return {innerText:'【明确标记的协议测试样例】'};
    return null;
  }};
}
test('canonical post identities reject unsupported URLs',()=>{
  assert.equal(core.canonical('https://x.com/fixture/status/123/history'),'https://x.com/i/web/status/123');
  assert.equal(core.canonical('https://twitter.com/fixture/status/123?s=20'),'https://x.com/i/web/status/123');
  assert.equal(core.canonical('https://x.com/i/article/123'),'https://x.com/i/article/123');
  for(const url of ['https://x.com.attacker.test/a/status/1','https://user:pass@x.com/a/status/1','http://x.com/a/status/1','https://x.com:9000/a/status/1','https://x.com/home','javascript:alert(1)'])assert.equal(core.canonical(url),null);
});
test('inline quoted timestamps never become an Article source or publication date',()=>{
  const article=root({rich:true,id:'123'});
  const originalTimes=article.querySelectorAll('time');
  const quote={closest:selector=>selector.includes('RichText')?{}:null,getAttribute:()=> 'incorrect quote date'};
  article.querySelectorAll=selector=>selector==='time'?[quote,...originalTimes]:selector.includes('show-more')?[quote]:[];
  const payload=core.extract(article,'https://x.com/fixture/status/123');
  assert.equal(payload.url,'https://x.com/i/web/status/123');
  assert.equal(payload.published_at,'2026-10-20T00:00:00Z');
});
test('a reply without its own permalink is not relabeled as the current post',()=>{
  const reply=root({id:'2'});reply.querySelectorAll=()=>[];
  const main=root({id:'1'});
  const doc={querySelector:()=>null,querySelectorAll:()=>[reply,main]};
  assert.equal(core.currentRoot(doc,'https://x.com/fixture/status/1'),main);
});
test('loaded source remains verbatim with metadata; no invented author or thread',()=>{
  const text='【原创测试】第一段保留 emoji 🧠。\n\n第二段说明证据不足需要人工处理，并明确限制。';
  const payload=core.extract(root({text}),'https://x.com/home','bookmark','fixture-event');
  assert.equal(payload.content,text);assert.equal(payload.url,'https://x.com/i/web/status/0');
  assert.equal(payload.author,'测试作者 @fixture');assert.equal(payload.completeness,'page_text');assert.equal(payload.source_kind,'note');
});
test('show-more, Article cards, empty and oversize bodies are partial',()=>{
  for(const fixture of [{more:true},{card:true},{text:''},{text:'长'.repeat(120001)}])assert.equal(core.extract(root(fixture),'https://x.com/home').completeness,'partial');
  assert.equal(core.extract(root({rich:true}),'https://x.com/i/article/789').url,'https://x.com/i/article/789');
  const payload=core.extract(root({text:'字'.repeat(299)+'🧠正文'}),'https://x.com/home');
  assert.equal(new TextDecoder().decode(new TextEncoder().encode(payload.title)),payload.title);
});
test('current post chooses matching timestamp rather than first reply',()=>{
  const first=root({id:'1'}),second=root({id:'2'});
  const doc={querySelector:()=>null,querySelectorAll:()=>[first,second]};
  assert.equal(core.currentRoot(doc,'https://x.com/fixture/status/2'),second);
  assert.equal(core.currentRoot(doc,'https://x.com/home'),null);
});
function worker(){
  const database={settings:{base:'http://127.0.0.1:8787',token:'fixture-scoped-token'},queue:[]};
  let listener,offline=true,access;
  const posts=[];
  const chrome={runtime:{id:'a'.repeat(32),getURL:name=>'chrome-extension://'+'a'.repeat(32)+'/'+name,onInstalled:{addListener(){}},onStartup:{addListener(){}},onMessage:{addListener(fn){listener=fn;}}},
    storage:{local:{async setAccessLevel(options){access=options.accessLevel;},async get(keys){if(typeof keys==='string')keys=[keys];return Object.fromEntries(keys.map(key=>[key,database[key]]));},async set(value){Object.assign(database,structuredClone(value));},async remove(key){delete database[key];}}},
    alarms:{async create(){},onAlarm:{addListener(){}}},action:{async setBadgeText(){},async setBadgeBackgroundColor(){}},tabs:{async query(){return [];}}};
  const context=vm.createContext({chrome,URL,AbortSignal,structuredClone,console,crypto:globalThis.crypto,fetch:async(url,options)=>{
    if(offline)throw new Error('Fixture network unavailable');
    posts.push({url,options});return {ok:true,json:async()=>({id:'protocol-fixture-only',message:'Protocol accepted, not an AI result'})};
  }});
  context.importScripts=()=>vm.runInContext(fs.readFileSync(path.join(directory,'clipper-core.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(directory,'background.js'),'utf8'),context);
  const sender={id:chrome.runtime.id,tab:{id:1,url:'https://x.com/home'},url:'https://x.com/home'};
  return {database,posts,context,setOnline(){offline=false;},access:()=>access,send:(message,source=sender)=>new Promise(resolve=>listener(message,source,resolve))};
}
test('offline queue survives a failed delivery and clears only after acknowledgement',async()=>{
  const w=worker();const payload=core.extract(root(),'https://x.com/home','bookmark','fixture-event');
  assert.equal((await w.send({type:'queue',payload})).ok,true);
  await vm.runInContext('deliver()',w.context);
  assert.equal(w.database.queue.length,1);assert.match(w.database.lastError,/本地助手/);
  w.setOnline();await vm.runInContext('deliver()',w.context);
  assert.equal(w.database.queue.length,0);assert.equal(w.posts.length,1);
  assert.equal(JSON.parse(w.posts[0].options.body).event_id,'fixture-event');
  assert.equal(w.posts[0].options.credentials,'omit');assert.equal(w.access(),'TRUSTED_CONTEXTS');
});
test('page scripts cannot pair, change destination, clear or enumerate library',async()=>{
  const w=worker();
  for(const type of ['pair','clear','status','forget'])assert.equal((await w.send({type,base:'http://attacker.test'})).ok,false);
  assert.equal((await w.send({type:'queue',payload:{}},{id:'a'.repeat(32),tab:{id:2,url:'https://attacker.test/'},url:'https://attacker.test/'})).ok,false);
  assert.throws(()=>vm.runInContext('localBase("http://127.0.0.1.attacker.test:8787")',w.context));
});
test('queue quota reports failure and preserves existing pending content',async()=>{
  const w=worker();w.database.queue=Array.from({length:100},(_,id)=>({payload:{url:'https://x.com/i/web/status/'+id,content:'fixture '+id},blocked:false}));
  const result=await w.send({type:'queue',payload:core.extract(root({id:'1000'}),'https://x.com/home')});
  assert.equal(result.ok,false);assert.match(result.error,/队列已满/);assert.equal(w.database.queue.length,100);
});

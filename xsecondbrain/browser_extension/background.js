'use strict';
importScripts('clipper-core.js');
const DEFAULT_BASE='http://127.0.0.1:8787',MAX_QUEUE=100,MAX_CHARS=1500000;
let serial=Promise.resolve();
function exclusive(work){const result=serial.then(work);serial=result.catch(()=>{});return result;}
function localBase(value){
  let url;try{url=new URL(value);}catch{throw new Error('本地地址格式不正确。');}
  if(url.protocol!=='http:'||!['127.0.0.1','localhost'].includes(url.hostname)||url.username||url.password||url.pathname!=='/'||url.search||url.hash)throw new Error('只能连接这台电脑上的本地助手。');
  return url.origin;
}
function isX(value){try{return new URL(value).protocol==='https:'&&['x.com','www.x.com','twitter.com','www.twitter.com'].includes(new URL(value).hostname);}catch{return false;}}
async function initialize(){
  await chrome.storage.local.setAccessLevel({accessLevel:'TRUSTED_CONTEXTS'});
  await chrome.alarms.create('deliver-clips',{periodInMinutes:1});
}
initialize().catch(()=>{});
chrome.runtime.onInstalled.addListener(()=>initialize());chrome.runtime.onStartup.addListener(()=>{initialize();deliver().catch(()=>{});});
async function request(path,settings,body){
  const headers={'Content-Type':'application/json','X-XSB-Extension':chrome.runtime.id};
  if(settings.token)headers.Authorization='Bearer '+settings.token;
  let response;try{response=await fetch(localBase(settings.base||DEFAULT_BASE)+'/api/browser'+path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(6000),credentials:'omit',cache:'no-store'});}
  catch{throw new Error('本地助手未响应。内容已留在浏览器，启动后台后会重试。');}
  let data;try{data=await response.json();}catch{throw new Error('这个地址没有运行 X 书签助手，请检查端口。');}
  if(!response.ok){const error=new Error(typeof data.detail==='string'?data.detail:'保存未完成，请重新配对或检查正文。');error.status=response.status;throw error;}
  return data;
}
async function badge(queue,error=''){
  await chrome.action.setBadgeText({text:error?'!':queue.length?String(queue.length):''});
  await chrome.action.setBadgeBackgroundColor({color:error?'#a4633d':'#315b4d'});
}
async function enqueue(payload){
  return exclusive(async()=>{
    if(!payload||!XSBClipper.canonical(payload.url)||typeof payload.content!=='string'||payload.content.length>120000)throw new Error('页面内容不符合保存格式，请展开单条正文后重试。');
    const stored=await chrome.storage.local.get(['queue']);const queue=stored.queue||[];
    if(queue.some(row=>row.payload.url===payload.url&&row.payload.content===payload.content&&row.payload.completeness===payload.completeness))return {ok:true,duplicate:true};
    const chars=queue.reduce((total,row)=>total+row.payload.content.length,0)+payload.content.length;
    if(queue.length>=MAX_QUEUE||chars>MAX_CHARS)throw new Error('待发送队列已满，请先启动本地助手并重试；这条尚未保存。');
    queue.push({payload,blocked:false});
    await chrome.storage.local.set({queue});await badge(queue);return {ok:true,queued:queue.length};
  });
}
async function deliver(retry=false){
  return exclusive(async()=>{
    const stored=await chrome.storage.local.get(['settings','queue']);const settings=stored.settings||{};const queue=stored.queue||[];
    if(retry)for(const row of queue)row.blocked=false;
    if(!settings.token){await badge(queue,queue.length?'请先配对':'');return;}
    let count=0;
    while(count<3){
      const index=queue.findIndex(row=>!row.blocked);if(index<0)break;
      const row=queue[index];
      try{
        const result=await request('/capture',settings,row.payload);
        queue.splice(index,1);
        await chrome.storage.local.set({queue,lastMessage:result.message,lastReceived:Date.now(),lastError:''});
      }catch(error){
        if([400,409,413,422].includes(error.status))row.blocked=true;
        await chrome.storage.local.set({queue,lastError:error.message});await badge(queue,error.message);return;
      }
      count++;
    }
    await badge(queue,queue.some(row=>row.blocked)?'有内容需要处理':'');
  });
}
chrome.alarms.onAlarm.addListener(alarm=>{if(alarm.name==='deliver-clips')deliver().catch(()=>{});});
async function popupMessage(message){
  const stored=await chrome.storage.local.get(['settings','queue','lastError','lastMessage']);const settings=stored.settings||{};
  if(message.type==='status'){
    let remote=null,error=stored.lastError||'';
    if(settings.token){try{remote=await request('/ping',settings);if(!(stored.queue||[]).length)error='';}catch(problem){error=problem.message;}}
    return {ok:true,paired:!!settings.token,enabled:settings.enabled!==false,base:settings.base||DEFAULT_BASE,queued:(stored.queue||[]).length,error,remote,lastMessage:stored.lastMessage||''};
  }
  if(message.type==='pair'){
    const base=localBase(message.base||DEFAULT_BASE);
    const result=await request('/pair',{base},{code:message.code,label:'Chrome / Edge 本地插件'});
    await exclusive(()=>chrome.storage.local.set({settings:{base,token:result.token,enabled:settings.enabled!==false},lastError:''}));
    deliver().catch(()=>{});return {ok:true};
  }
  if(message.type==='capture'){
    const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
    if(!tab?.id||!isX(tab.url))throw new Error('请先打开具体的 X 帖子或 Article。');
    try{return await chrome.tabs.sendMessage(tab.id,{type:'clip-current'});}catch{throw new Error('请刷新这个 X 网页后再试。');}
  }
  if(message.type==='retry'){await deliver(true);return {ok:true};}
  if(message.type==='pause'){
    const enabled=message.enabled===true;
    await exclusive(async()=>{const current=await chrome.storage.local.get('settings');await chrome.storage.local.set({settings:{...current.settings,enabled}});});
    const tabs=await chrome.tabs.query({url:['https://x.com/*','https://www.x.com/*','https://twitter.com/*','https://www.twitter.com/*']});
    await Promise.allSettled(tabs.map(tab=>chrome.tabs.sendMessage(tab.id,{type:'set-capture-enabled',enabled})));return {ok:true};
  }
  if(message.type==='clear'){
    await exclusive(async()=>{await chrome.storage.local.set({queue:[],lastError:''});await badge([]);});return {ok:true};
  }
  if(message.type==='forget'){
    await exclusive(()=>chrome.storage.local.remove('settings'));return {ok:true};
  }
  throw new Error('不支持的插件操作。');
}
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  if(sender.id!==chrome.runtime.id)return;
  const fromX=sender.tab&&isX(sender.url||sender.tab.url);
  const fromPopup=!sender.tab&&sender.url===chrome.runtime.getURL('popup.html');
  const task=(async()=>{
    if(fromX&&message.type==='capture-enabled'){
      const stored=await chrome.storage.local.get('settings');return {ok:true,enabled:stored.settings?.enabled!==false};
    }
    if(fromX&&message.type==='queue'){
      const stored=await chrome.storage.local.get('settings');if(stored.settings?.enabled===false&&message.payload?.capture_method==='bookmark')return {ok:false,error:'自动捕获已暂停。'};
      const result=await enqueue(message.payload);deliver().catch(()=>{});return result;
    }
    if(fromPopup)return popupMessage(message);
    throw new Error('拒绝来自网页的插件控制请求。');
  })();
  task.then(reply,error=>reply({ok:false,error:error.message||'插件操作未完成。'}));return true;
});

'use strict';
const el=id=>document.getElementById(id);let busy=false;
async function send(type,extra={}){const result=await chrome.runtime.sendMessage({type,...extra});if(!result?.ok)throw new Error(result?.error||'插件尚未就绪，请重新打开。');return result;}
function error(problem){el('error').textContent=problem.message;el('error').hidden=false;}
async function refresh(){
  const s=await send('status');el('pair-form').hidden=s.paired;el('connected').hidden=!s.paired;
  el('base').value=s.base;el('auto').checked=s.enabled;
  el('state').textContent=s.remote?'本地知识库已连接':s.paired?'等待本地助手响应':'首次使用，请连接本地知识库';
  el('queue').textContent=s.queued?'浏览器中有 '+s.queued+' 条待发送':'待发送队列为空';el('clear').hidden=!s.queued;
  el('stats').textContent=s.remote?'已入库 '+s.remote.received+' 篇 · 已阅读 '+s.remote.learned+' 篇 · 待补全 '+s.remote.needs_content+' 篇'+(s.remote.queued?' · 正在处理 '+s.remote.queued+' 篇':''):'';
  const problem=s.error||s.remote?.reader_error||(s.remote&&!s.remote.reader_enabled?'阅读引擎暂不可用，正文已保留。请安装并登录 Codex CLI，或配置备用模型。':'');
  if(problem)error(new Error(problem));else el('error').hidden=true;
}
async function action(button,work){if(busy)return;busy=true;button.disabled=true;el('error').hidden=true;try{await work();await refresh();}catch(problem){error(problem);}finally{busy=false;button.disabled=false;}}
el('pair-form').addEventListener('submit',event=>{event.preventDefault();action(event.submitter,async()=>{await send('pair',{base:el('base').value.trim(),code:el('code').value.trim()});el('code').value='';});});
el('capture').addEventListener('click',()=>action(el('capture'),()=>send('capture')));
el('retry').addEventListener('click',()=>action(el('retry'),()=>send('retry')));
el('auto').addEventListener('change',()=>action(el('auto'),()=>send('pause',{enabled:el('auto').checked})));
el('reconnect').addEventListener('click',()=>action(el('reconnect'),()=>send('forget')));
el('clear').addEventListener('click',()=>action(el('clear'),()=>send('clear')));
refresh().catch(error);

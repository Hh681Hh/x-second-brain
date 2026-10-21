'use strict';
const el=(id)=>document.getElementById(id);
let current=null,loading=false;
async function call(path,method='GET',body){
  const token=sessionStorage.getItem('xsb-token');
  const headers={'Content-Type':'application/json'};
  if(token)headers.Authorization='Bearer '+token;
  let response;
  try{response=await fetch('/api'+path,{method,headers,body:body===undefined?undefined:JSON.stringify(body)});}catch{throw new Error('后台脚本未连接，请双击“启动X书签助手.cmd”。');}
  if(response.status===401){el('local-auth').hidden=false;throw new Error('需要服务端 APP_TOKEN 才能连接本地知识库。');}
  const result=await response.json();
  if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'操作未完成，请检查输入和后台状态。');
  return result;
}
async function refresh(fill=false){
  const [s,reader]=await Promise.all([call('/integrations/x'),call('/status')]);
  current=s;
  el('connection-state').textContent=s.sync_enabled?'后台正在等待新收藏':s.connected?'X 已连接，尚未开始自动整理':'尚未连接 X 账号';
  el('setup').hidden=s.connected;el('account').hidden=!s.connected;
  el('activation').hidden=s.sync_enabled;el('active').hidden=!s.sync_enabled;
  el('callback').value=s.redirect_uri;
  if(fill)el('client-id').value=s.client_id;
  el('account-name').textContent=s.account?'已连接 @'+(s.account.username||s.account.id):'';
  el('schedule').textContent='每 '+s.interval_minutes+' 分钟检查一次 · 已自动入库 '+s.imported_total+' 篇。';
  el('reader-state').textContent=(reader.llm_enabled?'阅读引擎：'+reader.llm_model:'阅读引擎尚未配置，仍可保存原文')+' · 库内 '+reader.total+' 篇，已分析 '+reader.learned+' 篇。';
  el('enable').disabled=!s.connected||!el('cost').checked;
  if(s.last_error){el('error').textContent=s.last_error;el('error').hidden=false;}
}
async function action(button,work){
  if(loading)return;
  loading=true;button.disabled=true;el('error').hidden=true;
  try{await work();}catch(error){el('error').textContent=error.message;el('error').hidden=false;}
  finally{loading=false;button.disabled=false;el('enable').disabled=!current?.connected||!el('cost').checked;}
}
el('connect-form').addEventListener('submit',(event)=>{event.preventDefault();action(el('connect-button'),async()=>{
  const config={client_id:el('client-id').value.trim(),interval_minutes:current?.interval_minutes||10,page_size:current?.page_size||20,max_pages:current?.max_pages||3,long_only:current?.long_only??true};
  await call('/integrations/x/config','PUT',config);
  const result=await call('/integrations/x/authorize','POST');const target=new URL(result.authorization_url);
  if(target.origin!=='https://x.com'||target.pathname!=='/i/oauth2/authorize')throw new Error('授权地址无效，连接未开始。');
  location.assign(target.href);
});});
el('local-auth').addEventListener('submit',(event)=>{event.preventDefault();action(event.submitter,async()=>{sessionStorage.setItem('xsb-token',el('app-token').value.trim());await refresh(true);el('local-auth').hidden=true;});});
el('cost').addEventListener('change',()=>el('enable').disabled=!current?.connected||!el('cost').checked);
el('enable').addEventListener('click',()=>action(el('enable'),async()=>{await call('/integrations/x/switch','POST',{enabled:true,acknowledge_api_cost:el('cost').checked});await refresh();}));
el('pause').addEventListener('click',()=>action(el('pause'),async()=>{await call('/integrations/x/switch','POST',{enabled:false});await refresh();}));
el('disconnect').addEventListener('click',()=>action(el('disconnect'),async()=>{const result=await call('/integrations/x/disconnect','POST');await refresh(true);el('error').textContent=result.message;el('error').hidden=false;}));
refresh(true).catch(error=>{el('error').textContent=error.message;el('error').hidden=false;});
setInterval(()=>{if(!document.hidden&&!loading)refresh().catch(error=>{el('error').textContent=error.message;el('error').hidden=false;});},10000);

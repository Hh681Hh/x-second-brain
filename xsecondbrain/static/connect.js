'use strict';
const el=id=>document.getElementById(id);
let busy=false;
async function call(path,method='GET'){
  const headers={'Content-Type':'application/json'};
  const token=sessionStorage.getItem('xsb-token');if(token)headers.Authorization='Bearer '+token;
  let response;try{response=await fetch('/api'+path,{method,headers});}catch{throw new Error('后台未连接，请双击“启动X书签助手.cmd”。');}
  if(response.status===401){el('local-auth').hidden=false;throw new Error('请填写本地知识库的 APP_TOKEN。');}
  const body=await response.json();if(!response.ok)throw new Error(body.detail||'操作未完成，请重试。');return body;
}
function showError(error){el('error').textContent=error.message;el('error').hidden=false;}
async function refresh(){
  const [b,s]=await Promise.all([call('/browser'),call('/status')]);
  el('connection-state').textContent=b.paired?'后台运行正常 · 浏览器插件已配对':'后台已就绪，等待浏览器插件连接';
  el('paired').hidden=!b.paired;
  const seen=b.pairs.map(p=>p.last_seen).filter(Boolean).sort().pop();
  el('pair-state').textContent='已配对 '+b.pairs.length+' 个浏览器插件。'+(seen?' 最近通信：'+new Date(seen).toLocaleString('zh-CN')+'。':'');
  el('capture-state').textContent='插件已入库 '+b.captured_total+' 篇 · 待补全 '+b.needs_content+' 篇。';
  el('capture-instructions').textContent=b.public_fulltext_provider==='fxembed'
    ?'自动补全文已启用：直接点书签，后台会通过 FxEmbed 尝试获取公开长文并阅读分类，无需手动展开。需要补全的帖子 ID 会发送给该非官方服务；取文失败会保留链接并标记待补全。'
    :'未启用第三方补全文：先展开想保存的长文，再点书签。插件只保存页面已加载的内容；预览会留作待补全。';
  el('reader-state').textContent=(s.llm_enabled?'阅读引擎：'+s.llm_model:'未配置阅读引擎，仍可保存和搜索原文')+' · 库内 '+s.total+' 篇，已分析 '+s.learned+' 篇，等待阅读 '+s.queued+' 篇。';
}
async function action(button,work){if(busy)return;busy=true;button.disabled=true;el('error').hidden=true;try{await work();}catch(error){showError(error);}finally{busy=false;button.disabled=false;}}
el('pair-code').addEventListener('click',()=>action(el('pair-code'),async()=>{const result=await call('/browser/pair-code','POST');el('code').textContent=result.code;el('code-box').hidden=false;}));
el('copy-code').addEventListener('click',()=>action(el('copy-code'),async()=>{await navigator.clipboard.writeText(el('code').textContent);el('copy-code').textContent='已复制';}));
el('revoke').addEventListener('click',()=>action(el('revoke'),async()=>{await call('/browser/pairs','DELETE');await refresh();}));
el('local-auth').addEventListener('submit',event=>{event.preventDefault();action(event.submitter,async()=>{sessionStorage.setItem('xsb-token',el('app-token').value.trim());await refresh();el('local-auth').hidden=true;});});
refresh().catch(showError);setInterval(()=>{if(!document.hidden&&!busy)refresh().catch(showError);},10000);

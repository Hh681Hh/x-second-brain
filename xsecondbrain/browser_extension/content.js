/* Isolated-world listener for a real user's click, never clicks/scrolls X itself. */
(() => {
  'use strict';
  let active=true;
  const core=globalThis.XSBClipper;
  function notice(message,error=false){
    const box=document.createElement('div');box.setAttribute('role','status');
    box.textContent=message;
    Object.assign(box.style,{position:'fixed',bottom:'24px',right:'20px',zIndex:'2147483647',maxWidth:'330px',
      padding:'13px 17px',borderRadius:'12px',background:error?'#754d35':'#254b41',color:'white',font:'13px/1.7 system-ui',boxShadow:'0 8px 30px #0003',pointerEvents:'none'});
    document.documentElement.append(box);setTimeout(()=>box.remove(),6500);
  }
  async function send(payload){
    try{
      const result=await chrome.runtime.sendMessage({type:'queue',payload});
      if(!result?.ok)throw new Error(result?.error||'插件未连接，请刷新 X 网页。');
      notice(payload.completeness==='partial'?'书签链接与预览已暂存，可在插件查看补全进度。':'正文已暂存，等待本地助手接收并阅读。');
      return result;
    }catch(error){notice(error.message||'插件已更新，请刷新 X 网页。',true);throw error;}
  }
  chrome.runtime.sendMessage({type:'capture-enabled'}).then(result=>{active=result?.enabled!==false;}).catch(()=>{active=false;});
  document.addEventListener('click',event=>{
    if(!active||!event.isTrusted||!(event.target instanceof Element))return;
    const mark=event.target.closest('[data-testid="bookmark"]');
    if(!mark)return; // Ignore removal, programmatic clicks and unrelated controls.
    const pageUrl=location.href;
    const root=mark.closest('article[data-testid="tweet"]')||core.currentRoot(document,pageUrl);
    if(!root)return;
    const snapshot=core.extract(root,pageUrl,'bookmark');
    const button=mark.closest('button')||mark;
    let stopped=false,stableTimer;
    function end(){if(stopped)return;stopped=true;observer.disconnect();clearTimeout(stableTimer);clearTimeout(deadline);}
    function isMarked(){return button.getAttribute('data-testid')==='removeBookmark'||!!button.querySelector('[data-testid="removeBookmark"]')||!!root.querySelector('[data-testid="removeBookmark"]');}
    function check(){
      if(location.href!==pageUrl){end();return;}
      if(!isMarked()){clearTimeout(stableTimer);stableTimer=null;return;}
      if(!stableTimer)stableTimer=setTimeout(()=>{
        if(!isMarked()){stableTimer=null;return;}
        let payload=snapshot;
        if(root.isConnected){try{payload=core.extract(root,pageUrl,'bookmark',snapshot.event_id);}catch{}}
        end();send(payload).catch(()=>{});
      },1200);
    }
    const observer=new MutationObserver(check);
    // X may replace the whole button; inspect the same post for a short bounded interval.
    observer.observe(root,{attributes:true,childList:true,subtree:true});
    const deadline=setTimeout(end,8000);queueMicrotask(check);
  },true);
  chrome.runtime.onMessage.addListener((message,sender,reply)=>{
    if(sender.id!==chrome.runtime.id)return;
    if(message.type==='set-capture-enabled'){active=message.enabled===true;reply({ok:true});return;}
    if(message.type!=='clip-current')return;
    try{
      const root=core.currentRoot(document,location.href);
      const payload=core.extract(root,location.href,'manual');
      send(payload).then(reply,error=>reply({ok:false,error:error.message}));
    }catch(error){reply({ok:false,error:error.message});}
    return true;
  });
})();

/* Original page extractor. Reads existing DOM only; no navigation or X requests. */
(function (scope) {
  'use strict';
  const MAX_CONTENT=120000;
  function clip(text,limit){const part=text.slice(0,limit);return /[\uD800-\uDBFF]$/.test(part)?part.slice(0,-1):part;}
  function canonical(value,base='https://x.com/'){
    try{
      const u=new URL(value,base);
      if(u.protocol!=='https:'||!['x.com','www.x.com','twitter.com','www.twitter.com'].includes(u.hostname)||u.username||u.password||u.port)return null;
      const post=u.pathname.match(/^\/(?:[A-Za-z0-9_]+|i\/web)\/status\/(\d+)(?:\/history)?\/?$/);
      if(post)return 'https://x.com/i/web/status/'+post[1];
      const article=u.pathname.match(/^\/i\/article\/(\d+)\/?$/);
      return article?'https://x.com/i/article/'+article[1]:null;
    }catch{return null;}
  }
  function visibleText(node){return (node?.innerText??node?.textContent??'').replace(/\r/g,'').replace(/\n{3,}/g,'\n\n').trim();}
  const RICH='[data-testid="twitterArticleRichTextView"], [data-testid="longformRichTextComponent"], [data-testid="articleRichTextView"]';
  function richNode(root){return root.querySelector(RICH);}
  function isOwnMetadata(root,node){
    if(node.closest(RICH))return false;
    const owner=node.closest('article[data-testid="tweet"]');
    return !owner||owner===root;
  }
  function ownTime(root){
    // Inline quotes precede the enclosing Article's publication time in X's DOM.
    return [...root.querySelectorAll('time')].find(node=>isOwnMetadata(root,node))||null;
  }
  function sourceUrl(root,pageUrl){
    const page=canonical(pageUrl);
    // Native Article read views often have no timestamp permalink.
    if(page?.includes('/i/article/')&&richNode(root))return page;
    const time=ownTime(root);
    const permalink=time?.closest('a[href]')?.getAttribute('href');
    return (permalink?canonical(permalink,pageUrl):null)||(richNode(root)?page:null);
  }
  function extract(root,pageUrl,method='bookmark',eventId){
    if(!root)throw new Error('没有找到帖子正文。请打开单条帖子或 Article 后重试。');
    const url=sourceUrl(root,pageUrl);if(!url)throw new Error('请打开具体的 X 帖子或 Article。');
    const rich=richNode(root);
    const body=rich||root.querySelector('[data-testid="tweetText"]');
    let content=visibleText(body);
    // Any truncated inline quote also makes completeness uncertain; keep conservative.
    const showMore=!!root.querySelector('[data-testid="tweet-text-show-more-link"], [data-testid="article-read-more"]');
    const articleCard=!!root.querySelector('a[href*="/i/article/"]')&&!rich;
    const partial=showMore||articleCard||!content||content.length<20||content.length>MAX_CONTENT;
    if(content.length>MAX_CONTENT)content=clip(content,MAX_CONTENT);
    const headline=rich?visibleText(root.querySelector('h1, [data-testid="twitter-article-title"], [data-testid="twitterArticleReadViewTitle"]')):'';
    const name=visibleText(root.querySelector('[data-testid="User-Name"]')).replace(/\n+/g,' ');
    return {event_id:eventId||(scope.crypto?.randomUUID?.()||Date.now()+'-'+Math.random().toString(36).slice(2)),
      url,title:clip(headline||content.split('\n')[0]||'待补全的 X 收藏',300),author:clip(name,200),
      published_at:(ownTime(root)?.getAttribute('datetime')||'').slice(0,80),content,
      completeness:partial?'partial':'page_text',capture_method:method,source_kind:rich?'article':'note'};
  }
  function currentRoot(doc,pageUrl){
    const primary=doc.querySelector('[data-testid="primaryColumn"]')||doc;
    const readView=primary.querySelector('[data-testid="twitterArticleReadView"], [data-testid="articleReadView"]');
    if(readView&&richNode(readView))return readView.closest('article[data-testid="tweet"]')||readView;
    const url=canonical(pageUrl);
    for(const row of primary.querySelectorAll('article[data-testid="tweet"]')){
      if(url&&sourceUrl(row,pageUrl)===url)return row;
    }
    return null;
  }
  scope.XSBClipper={canonical,extract,currentRoot,visibleText};
  if(typeof module!=='undefined'&&module.exports)module.exports=scope.XSBClipper;
})(globalThis);

'use strict';

const $ = (selector) => document.querySelector(selector);
const h = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeURL = (value) => { try { const u = new URL(value); return ['http:', 'https:'].includes(u.protocol) ? u.href : ''; } catch { return ''; } };
const date = (value) => { const d = new Date(value); return Number.isNaN(d.getTime()) ? '日期未知' : d.toLocaleDateString('zh-CN', {month:'2-digit',day:'2-digit'}); };
const state = {route:'home', category:'', status:{}, browser:{}, prefs:{categories:[], interests:''}, articles:[], current:null, readerMode:'quick', evidence:null, importMode:'link', session:null, asking:false, search:false, offset:0, citations:new Map(), citeCounter:0, pendingQuestion:null};
const colors = ['#93a9ab','#b1a0be','#aeb8a0','#c3ab84','#a5b4cf','#abbbb9','#bea6a1','#a9b2bc'];
const ratingNames = {novelty:'信息增量', credibility:'文中证据', relevance:'关注相关性', actionability:'实操价值', longevity:'长期价值'};
let toastTimer;

function toast(message) { const el = $('#toast'); el.textContent = message; el.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => el.hidden = true, 5500); }
async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = sessionStorage.getItem('xsb-token');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (options.body !== undefined && typeof options.body !== 'string') { headers.set('Content-Type','application/json'); options.body = JSON.stringify(options.body); }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 280000);
  try {
    const res = await fetch('/api' + path, {...options, headers, signal:controller.signal});
    const payload = await res.json();
    if (!res.ok) {
      let detail = payload.detail || '操作失败，请重试。';
      if (payload.errors?.length) detail += '\n' + payload.errors.map((e) => `${e.field}: ${e.message}`).join('\n');
      if (res.status === 401) $('#connection-error').textContent = '需要访问令牌。打开“设置与数据”输入服务端的 APP_TOKEN。';
      throw new Error(detail);
    }
    return payload;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('请求超时，服务端任务可能仍在进行。请先检查收藏状态，再决定是否重试。');
    if (error instanceof TypeError) throw new Error('无法连接本地服务。请确认项目仍在运行，并检查当前地址。');
    throw error;
  } finally { clearTimeout(timer); }
}

async function busy(button, action, label='处理中…') {
  if (button.disabled) return;
  const text = button.textContent; button.disabled = true; button.textContent = label;
  try { return await action(); } catch (error) { toast(error.message); } finally { button.disabled = false; button.textContent = text; }
}

function empty(title, text, action='import') { return `<div class="empty-state"><span class="empty-icon">✧</span><h3>${h(title)}</h3><p>${h(text)}</p>${action ? `<button class="button" data-action="${h(action)}">${action === 'import' ? '＋ 收藏第一篇内容' : '打开设置'}</button>` : ''}</div>`; }
function badge(article) {
  const options = {ready:['已分析',''],saved:['原文已存',''],queued:['等待分析','working'],processing:['正在分析','working'],needs_content:['待补充全文','warn'],error:['分析失败','warn']};
  const [label, cls] = options[article.status] || ['已保存',''];
  return `<span class="state-badge ${cls}">${label}</span>`;
}
function topicTag(article, index=0) { return `<span class="topic-tag color${index % 4}">${h(article.category || '其他知识')}</span>`; }
function summaryPreview(article) {
  if (article.quick?.length) return article.quick.map((point) => point.text).join(' ');
  if (article.status === 'needs_content') return '暂未取得全文，补全后才能生成重点摘要。';
  if (['queued','processing'].includes(article.status)) return '正在整理文章重点，完成后会自动显示。';
  if (article.status === 'error') return '分析尚未完成，点击查看原因和已保存的内容。';
  return '原文已保存，尚未生成重点摘要。';
}
function articleRow(article) {
  return `<button class="article-row" data-article="${h(article.id)}"><span class="source-icon" aria-hidden="true">${article.url?.includes('x.com') ? '𝕏' : article.source_kind === 'thread' ? '≋' : '▧'}</span><span class="row-copy"><span class="row-heading"><span class="row-title">${h(article.title)}</span>${topicTag(article)}</span><span class="row-summary${article.quick?.length ? '' : ' pending'}">${h(summaryPreview(article))}</span><span class="row-meta"><span>${h(article.author || '作者未填写')}</span><span>收藏于 ${date(article.saved_at)}</span>${badge(article)}${article.is_read ? '<span>已读</span>' : ''}</span></span><span class="row-action">查看重点 <span aria-hidden="true">→</span></span></button>`;
}
function readingCard(article, index=0) {
  const summary = summaryPreview(article);
  const reasons = article.ratings ? Object.entries(article.ratings).map(([key, value]) => `${ratingNames[key]} ${value.score}/5：${value.reason}`).join('\n') : 'AI 分析完成后会显示评分和具体理由。';
  return `<button class="reading-card" data-article="${h(article.id)}" title="${h(reasons)}"><div class="card-top">${topicTag(article,index)}<span class="score-tag">${article.priority != null ? `阅读价值 <strong>${Number(article.priority).toFixed(1)}</strong> / 5` : '待 AI 评价'}</span></div><h3>${h(article.title)}</h3><p class="card-excerpt">${h(summary)}</p><div class="card-bottom"><span class="author-name">${h(article.author || '作者未填写')}</span><span>${article.is_read ? '已读' : '开始阅读'} ↗</span></div></button>`;
}

async function refreshStatus() {
  [state.status, state.browser] = await Promise.all([api('/status'), api('/browser')]);
  $('#connection-error').hidden = true;
  $('#library-count').textContent = state.status.total;
  $('#model-status').textContent = state.status.llm_enabled ? 'AI 已配置' : '基础收藏模式';
  $('#model-status').classList.toggle('ready', state.status.llm_enabled);
  $('#stats-grid').innerHTML = [
    ['全部收藏',state.status.total,'篇','▤'], ['AI 已整理',state.status.learned,'篇','✧'],
    ['知识与方法',state.status.knowledge_cards || 0,'条','◈']
  ].map(([label,value,unit,icon]) => `<div class="stat"><div class="stat-label">${label}</div><div class="stat-value">${value}<span>${unit}</span></div><span class="stat-decoration" aria-hidden="true">${icon}</span></div>`).join('');
  const s = state.status;
  const title = !s.llm_enabled ? '自动分析尚未配置' : s.queued ? `正在自动整理 ${s.queued} 篇收藏` : '后台自动整理已开启';
  const notes = [state.browser.paired ? '浏览器插件已配对' : '浏览器插件尚未配对'];
  if (state.browser.public_fulltext_provider === 'fxembed') notes.push('公开帖自动补全文已启用');
  if (s.indexed) notes.push(`${s.indexed} 篇已建立语义索引`);
  if (!s.llm_enabled) notes.push('目前只保存原文，配置模型后才能自动生成摘要与分类');
  const pending = [[s.needs_content,'篇待补全文'],[s.failed,'篇分析失败'],[s.saved,'篇仅存原文']].filter(([count]) => count).map(([count,label]) => count + label);
  $('#learning-status').classList.toggle('has-pending',Boolean(s.needs_attention));
  $('#learning-status').innerHTML = `<div class="learning-copy"><strong><span aria-hidden="true">${s.queued ? '◷' : '✧'}</span> ${h(title)}</strong><p>${h(notes.join(' · '))}</p>${pending.length ? `<p class="learning-pending">${h(pending.join(' · '))}，尚未完成学习。</p>` : ''}${s.embedding_error ? `<p class="learning-pending">语义索引暂不可用：${h(s.embedding_error)}</p>` : ''}</div>${s.needs_attention ? '<button class="button" data-action="attention">查看待处理 →</button>' : !state.browser.paired ? '<a class="button" href="/">连接插件 →</a>' : !s.llm_enabled ? '<button class="button" data-action="settings">查看设置 →</button>' : '<span class="learning-hint">摘要与分类自动生成</span>'}`;
}

async function refreshPrefs() {
  state.prefs = await api('/preferences');
  $('#category-nav').innerHTML = state.prefs.categories.map((category,index) => `<a href="#library" data-category="${h(category)}" style="--dot:${colors[index % colors.length]}" class="${state.category === category ? 'active' : ''}">${h(category)}</a>`).join('');
  const select = $('#category-filter');
  select.innerHTML = '<option value="">全部主题</option>' + state.prefs.categories.map((c) => `<option value="${h(c)}">${h(c)}</option>`).join('');
  if (state.category && !state.prefs.categories.includes(state.category)) select.insertAdjacentHTML('beforeend', `<option value="${h(state.category)}">${h(state.category)}（旧分类）</option>`);
  select.value = state.category;
}

async function renderHome() {
  const [recent, priority] = await Promise.all([api('/articles?limit=6'), api('/articles?sort=priority&unread=true&limit=3')]);
  $('#home-priority').innerHTML = priority.articles.length ? priority.articles.map(readingCard).join('') : empty(state.status.total ? '阅读队列已经清空' : '第一份值得保存的知识，从这里开始', state.status.total ? '你的收藏都已读过。新的内容随时可以加入。' : '粘贴一篇 X 长文或文章全文。它会成为你未来能够找回的方法。');
  $('#home-recent').innerHTML = recent.articles.length ? recent.articles.map(articleRow).join('') : empty('这里将保存你的好内容', '收藏时保留原文，提问时重新找到它。');
}

async function renderLibrary(append=false) {
  $('#sort-filter').disabled = false;
  document.querySelectorAll('[data-category]').forEach((el) => el.classList.toggle('active',el.dataset.category === state.category));
  const params = new URLSearchParams({limit:50, offset:append ? state.offset : 0, sort:$('#sort-filter').value, unread:$('#unread-filter').checked});
  const attention = $('#attention-filter').checked;
  params.set('attention', attention);
  if (state.category) params.set('category',state.category);
  const result = await api('/articles?' + params);
  $('#library-title').textContent = state.category || (attention ? '待处理收藏' : '全部收藏');
  if (!append) { state.articles = []; state.offset = 0; }
  state.articles.push(...result.articles); state.offset = state.articles.length;
  $('#library-results').innerHTML = result.total ? `<div class="article-list">${state.articles.map(articleRow).join('')}</div>` : attention ? empty('没有待处理收藏', '当前筛选中没有缺全文、分析失败或仅保存原文的内容。', '') : empty('还没有这一类收藏', '可以先添加内容，也可以换一个主题看看。');
  $('#search-meta').textContent = `${result.total} 篇收藏${state.category ? ' · ' + state.category : ''}${attention ? ' · 待补全文 / 分析失败 / 仅存原文' : ''}`;
  $('#load-more').hidden = state.offset >= result.total;
  state.search = false;
}

function sourceResult(hit) {
  const ev = {article_id:hit.article_id, chunk_id:hit.id, start_offset:hit.start_offset, end_offset:hit.end_offset, quote:hit.text};
  const link = safeURL(hit.url);
  return `<article class="search-result"><h3><a href="#article/${h(hit.article_id)}" data-article="${h(hit.article_id)}">${h(hit.title)}</a></h3><div class="result-meta">${h(hit.author || '作者未填写')} · ${h(hit.category || '')} · ${hit.matched_by?.includes('semantic') ? '语义匹配' : '全文匹配'}${hit.semantic_score ? ' · 相似度 ' + hit.semantic_score.toFixed(2) : ''}</div><p>${h(hit.text)}</p><div class="result-footer">${citation(ev,'查看原文片段')}${link ? `<a class="text-link" href="${h(link)}" target="_blank" rel="noopener noreferrer">打开来源 ↗</a>` : '<span class="muted">用户手工输入，无外部链接</span>'}</div></article>`;
}
async function runSearch() {
  const query = $('#search-query').value.trim();
  if (query.length < 2) return renderLibrary();
  // Semantic search uses indexed source content, so leave the pending-only view.
  $('#attention-filter').checked = false;
  $('#library-title').textContent = state.category || '全部收藏';
  const result = await api('/search?' + new URLSearchParams({q:query, category:state.category, unread:$('#unread-filter').checked, limit:15}));
  state.search = true;
  $('#sort-filter').disabled = true;
  $('#library-results').innerHTML = result.hits.length ? result.hits.map(sourceResult).join('') : empty('没有找到足够相关的内容', '换一种问题描述，或把你想参考的文章加入知识库。', '');
  const modes = {hybrid:'全文 + 语义混合检索',semantic:'语义检索',keyword:'全文检索'};
  $('#search-meta').textContent = `${result.hits.length} 个原文片段 · ${modes[result.mode]}${result.warnings.length ? ' · ' + result.warnings.join(' ') : ''}`;
  $('#load-more').hidden = true;
}

async function route() {
  const raw = location.hash.slice(1) || 'home';
  if (raw.startsWith('article/')) { await openArticle(raw.slice(8)); return; }
  const routeName = ['home','library','priority','chat','network','sync'].includes(raw) ? raw : 'home';
  state.route = routeName;
  document.querySelectorAll('.view').forEach((el) => el.hidden = el.id !== 'view-' + routeName);
  document.querySelectorAll('[data-route]').forEach((el) => el.classList.toggle('active', el.dataset.route === routeName));
  $('#page-breadcrumb').textContent = {home:'工作台',library:'全部收藏',priority:'阅读队列',chat:'知识问答',network:'知识关联',sync:'X 自动同步'}[routeName];
  try {
    if (routeName === 'home') await renderHome();
    if (routeName === 'library') await renderLibrary();
    if (routeName === 'priority') { const result = await api('/articles?sort=priority&unread=true&limit=200'); $('#priority-results').innerHTML = result.articles.length ? result.articles.map(readingCard).join('') : empty('暂时没有未读内容', '你可以加入一篇想认真读的文章。'); }
    if (routeName === 'chat') { await refreshSessions(); if (!state.session && !state.asking) renderChatEmpty(); if (state.pendingQuestion) { const question = state.pendingQuestion; state.pendingQuestion = null; await sendQuestion(question); } }
    if (routeName === 'network') await renderNetwork();
    if (routeName === 'sync') await renderSync(true);
  } catch (error) { toast(error.message); }
}

function showDialog(id) { const dialog = $('#' + id); if (!dialog.open) dialog.showModal(); }
function closeDialog(id) { $('#' + id).close(); }
function setImportMode(mode) {
  state.importMode = mode;
  document.querySelectorAll('[data-import-mode]').forEach((el) => el.classList.toggle('active',el.dataset.importMode === mode));
  $('#import-result').textContent = ''; $('#import-result').className = 'inline-result';
  if (mode === 'link') {
    $('#import-fields').innerHTML = '<label class="field">文章链接<input id="import-url" type="url" placeholder="https://x.com/作者/status/…" maxlength="2048" required></label><label class="field">标题（可选）<input id="import-name" maxlength="300" placeholder="留空时尝试自动获取"></label>';
    $('#import-note').textContent = '此处直接导入 X 链接仍需官方 API；免费自动补全文用于浏览器插件捕获的书签。也可切换“粘贴全文”，普通公开网页可直接提取。';
  } else if (mode === 'text') {
    $('#import-fields').innerHTML = '<label class="field">文章标题<input id="import-name" placeholder="给这份知识一个名字" maxlength="300" required></label><div class="field-row"><label class="field">作者<input id="import-author" placeholder="未知可留空" maxlength="200"></label><label class="field">内容类型<select id="import-kind"><option value="article">文章 / X 长文</option><option value="thread">完整帖子串 Thread</option><option value="note">个人笔记</option></select></label></div><label class="field">来源链接（可选）<input id="import-url" type="url" placeholder="保留真实原文地址，方便回到来源" maxlength="2048"></label><label class="field">完整正文<textarea id="import-text" rows="9" placeholder="直接粘贴原文。Thread 请按作者发文顺序粘贴，并保留重要上下文。" minlength="20" maxlength="120000" required></textarea></label>';
    $('#import-note').textContent = '正文将原样保存在本地。开启远程模型后，文章会发往你配置的模型服务。未配置模型时仍可保存、编辑、搜索及导出。';
  } else {
    $('#import-fields').innerHTML = '<label class="field">每行一个链接，最多 50 条<textarea id="import-links" rows="9" placeholder="https://x.com/作者/status/…\nhttps://…" required></textarea></label>';
    $('#import-note').textContent = '自动去除重复链接，每条分别保存和分析。无法获取的全文会明确标记；使用官方 X API 或模型时消耗对应额度。';
  }
}
function openImport() { setImportMode('link'); showDialog('import-dialog'); }
$('#import-form').addEventListener('submit', (event) => { event.preventDefault(); busy($('#import-submit'), async () => {
  let message;
  if (state.importMode === 'batch') {
    const urls = [...new Set($('#import-links').value.split(/\n/).map((s) => s.trim()).filter(Boolean))];
    if (!urls.length || urls.length > 50) throw new Error('每次需要 1–50 个有效链接。');
    for (const url of urls) if (!safeURL(url)) throw new Error('存在无效链接：' + url.slice(0,70));
    const result = await api('/articles/batch', {method:'POST',body:{articles:urls.map((url) => ({url}))}});
    const errors = result.results.filter((r) => r.error); const duplicate = result.results.filter((r) => r.duplicate).length;
    message = `已接收 ${result.results.length - errors.length} 条，跳过重复 ${duplicate} 条。` + errors.map((r) => '\n' + r.url + '：' + r.error).join('');
  } else {
    const item = {url:$('#import-url').value.trim(), title:$('#import-name').value.trim()};
    if (state.importMode === 'text') Object.assign(item,{author:$('#import-author').value.trim(), content:$('#import-text').value, source_kind:$('#import-kind').value});
    const result = await api('/articles', {method:'POST', body:item});
    message = result.message + ' 可在收藏中查看处理状态。';
  }
  $('#import-result').textContent = message;
  await refreshStatus(); await route(); toast(message);
}, '正在保存…'); });

function citation(evidence, label='原文依据') {
  const key = String(++state.citeCounter); state.citations.set(key,evidence);
  return `<button class="citation" data-citation="${key}" title="${h(evidence.quote?.slice(0,160))}">↗ ${h(label)}</button>`;
}
function pointHTML(point) { return `<div class="grounded-point"><h3>${h(point.label)}</h3><p>${h(point.text)}</p><div>${point.evidence.map((e,i) => citation(e,`依据 ${i+1}`)).join('')}</div></div>`; }
function knowledgeHTML(card, index) {
  const list = (items) => items?.length ? '<ul>' + items.map((x) => `<li>${h(x)}</li>`).join('') + '</ul>' : '原文未说明';
  return `<div class="knowledge-card"><span class="small-label">KNOWLEDGE ${String(index+1).padStart(2,'0')}</span><h3>${h(card.problem)}</h3><dl><dt>具体方法</dt><dd>${h(card.method)}</dd><dt>为什么可能有效 · AI 解读，效果需验证</dt><dd>${h(card.why)}</dd><dt>适用场景</dt><dd>${list(card.scenarios)}</dd><dt>前提条件</dt><dd>${list(card.prerequisites)}</dd><dt>执行步骤</dt><dd>${list(card.steps)}</dd><dt>局限与风险</dt><dd>${list(card.limitations)}</dd><dt>值得重新验证</dt><dd>${list(card.questions)}</dd></dl>${card.evidence.map((e,i) => citation(e,`方法出处 ${i+1}`)).join('')}</div>`;
}
async function openArticle(id, evidence=null) {
  try {
    const dialog = $('#reader-dialog');
    const preserve = dialog.open && state.current?.id === id && !evidence;
    const scrollTop = preserve ? dialog.scrollTop : 0;
    state.current = await api('/articles/' + encodeURIComponent(id));
    if (!preserve) { state.evidence = evidence; state.readerMode = evidence ? 'original' : 'quick'; }
    const a = state.current; const link = safeURL(a.url);
    $('#reader-header').innerHTML = `${topicTag(a)}<h2 id="reader-title">${h(a.title)}</h2><div class="reader-meta"><span>${h(a.author || '作者未填写')}</span><span>收藏于 ${date(a.saved_at)}</span>${link ? `<a href="${h(link)}" target="_blank" rel="noopener noreferrer">打开原文 ↗</a>` : '<span>手工收藏</span>'}${badge(a)}</div><div class="reader-tags">${a.tags.map((tag) => `<span>${h(tag)}</span>`).join('')}</div>${a.status === 'needs_content' || a.ai_error ? `<div class="reader-notice">${h(a.ai_error || a.extraction_note || '尚未取得全文，请补充正文后再分析。')}</div>` : a.extraction_note ? `<details class="source-details"><summary>采集说明</summary><p>${h(a.extraction_note)}</p></details>` : ''}`;
    $('#read-toggle').textContent = a.is_read ? '标为未读' : '标为已读';
    renderReader(); showDialog('reader-dialog'); dialog.scrollTop = scrollTop;
    if (evidence) requestAnimationFrame(() => $('#reader-content mark')?.scrollIntoView({block:'center'}));
  } catch (error) { toast(error.message); }
}
function renderReader() {
  const a = state.current;
  if (!a) return;
  document.querySelectorAll('[data-reader-mode]').forEach((el) => { const active = el.dataset.readerMode === state.readerMode; el.classList.toggle('active',active); el.setAttribute('aria-pressed',String(active)); });
  const content = $('#reader-content');
  if (state.readerMode === 'original') {
    let raw = h(a.content);
    if (state.evidence?.quote) {
      const quote = state.evidence.quote;
      // API offsets use Unicode code points; JavaScript String.slice uses UTF-16 code units.
      let start = [...a.content].slice(0,state.evidence.start_offset).join('').length;
      if (a.content.slice(start,start+quote.length) !== quote) start = a.content.indexOf(quote);
      if (start >= 0) raw = h(a.content.slice(0,start)) + '<mark>' + h(quote) + '</mark>' + h(a.content.slice(start+quote.length));
      else raw = '<div class="banner error">正文已被修订，此引用目前不存在。历史回答保留的是当时的证据快照。</div>' + raw;
    }
    content.innerHTML = a.content ? `<div class="original-label">原始正文 · ${a.content.length.toLocaleString()} 字符${state.evidence ? ' · 已定位引用片段' : ''}</div><div class="original-text">${raw}</div>` : empty('尚未取得正文', '来源可能需要登录或 API 访问权限。点击下方“编辑内容”，直接补充完整原文。','');
    return;
  }
  if (!a.analysis) {
    let message = a.status === 'queued' || a.status === 'processing' ? '后台正在处理。可以先阅读原文，完成后会自动显示摘要。' : !state.status.llm_enabled ? '尚未配置语言模型。原文已保存；在服务端 .env 中配置模型并重启后，点击“重新处理”。' : a.ai_error || '尚未生成分析，请先补全文或重新处理。';
    const title = ['queued','processing'].includes(a.status) ? '正在整理文章重点' : a.status === 'needs_content' ? '还需要完整正文' : '暂时没有重点摘要';
    content.innerHTML = empty(title,message,'') + `<button class="button" data-reader-mode="original">先看已保存的原文 →</button>` + (a.embedding_error ? `<p class="import-note">${h(a.embedding_error)}</p>` : ''); return;
  }
  const analysis = a.analysis;
  if (state.readerMode === 'quick') {
    const methods = analysis.knowledge.slice(0,2);
    content.innerHTML = `<section class="summary-lead"><div class="summary-kicker">30 秒读懂</div><h3>这篇文章讲什么</h3>${analysis.quick.map((point) => `<p>${h(point.text)}</p><div>${point.evidence.map((e) => citation(e,'核对原文')).join('')}</div>`).join('')}</section><section class="summary-section"><div class="summary-section-heading"><h3>记住这几个要点</h3>${analysis.standard.length > 3 ? `<button data-reader-mode="standard" class="text-button">查看全部 ${analysis.standard.length} 个要点 →</button>` : ''}</div><div class="takeaway-list">${analysis.standard.slice(0,3).map((point,i) => `<div class="takeaway"><span class="takeaway-number">${i+1}</span><div><h4>${h(point.label)}</h4><p>${h(point.text)}</p>${point.evidence.map((e) => citation(e,'原文依据')).join('')}</div></div>`).join('')}</div></section>${methods.length ? `<section class="summary-section"><div class="summary-section-heading"><h3>可以怎么做</h3>${analysis.knowledge.length > 2 ? `<button data-reader-mode="deep" class="text-button">全部 ${analysis.knowledge.length} 个方法 →</button>` : ''}</div>${methods.map((card) => `<div class="action-card"><h4>${h(card.problem)}</h4><p>${h(card.method)}</p>${card.steps.length ? `<details class="action-steps"><summary>展开 ${card.steps.length} 个执行步骤</summary><ol>${card.steps.map((step) => `<li>${h(step)}</li>`).join('')}</ol></details>` : ''}${card.evidence.map((e) => citation(e,'方法出处')).join('')}</div>`).join('')}</section>` : ''}<button class="button summary-more" data-reader-mode="standard">继续看 3 分钟精读 →</button>`;
  } else content.innerHTML = analysis[state.readerMode].map(pointHTML).join('');
  if (state.readerMode === 'deep') content.insertAdjacentHTML('beforeend', `<h3>可调用的方法卡</h3>${analysis.knowledge.map(knowledgeHTML).join('')}<h3>阅读价值 · ${a.priority?.toFixed(1) || '—'} / 5</h3><div class="rating-grid">${Object.entries(analysis.ratings).map(([key,value]) => `<div class="rating-item">${h(ratingNames[key] || key)}<strong>${value.score}/5</strong><p>${h(value.reason)}</p></div>`).join('')}</div>`);
  content.insertAdjacentHTML('beforeend', `<div class="credibility-note">${h(analysis.credibility)}</div><p class="import-note">AI 对原文的整理，不代表外部事实已经核验。引用可核对原文，但不能保证推论全部正确。${a.analysis_model ? ' · 模型 ' + h(a.analysis_model) : ''}</p>`);
}
function openEditor() {
  const a = state.current; if (!a) return;
  $('#edit-title').value = a.title; $('#edit-author').value = a.author; $('#edit-published').value = a.published_at;
  const categories = [...new Set([...state.prefs.categories,a.category])]; $('#edit-category').innerHTML = categories.map((c) => `<option value="${h(c)}">${h(c)}</option>`).join(''); $('#edit-category').value = a.category;
  $('#edit-tags').value = a.tags.join(', '); $('#edit-content').value = a.content;
  showDialog('edit-dialog');
}
$('#edit-form').addEventListener('submit', (event) => { event.preventDefault(); busy(event.submitter, async () => {
  const a = state.current; const patch = {};
  const values = {title:$('#edit-title').value.trim(), author:$('#edit-author').value.trim(), published_at:$('#edit-published').value.trim(), category:$('#edit-category').value, content:$('#edit-content').value.trim(), tags:$('#edit-tags').value.split(/[,，]/).map((s) => s.trim()).filter(Boolean)};
  for (const [key,value] of Object.entries(values)) if (JSON.stringify(value) !== JSON.stringify(a[key])) patch[key] = value;
  if (Object.keys(patch).length) await api('/articles/' + a.id, {method:'PATCH',body:patch});
  closeDialog('edit-dialog'); await openArticle(a.id); await refreshStatus(); await route(); toast('收藏已修订。');
}); });
$('#read-toggle').addEventListener('click', (event) => busy(event.currentTarget, async () => { const a = state.current; await api('/articles/' + a.id,{method:'PATCH',body:{is_read:!a.is_read}}); await openArticle(a.id); await refreshStatus(); await route(); }));
$('#reader-edit').addEventListener('click',openEditor);
$('#reader-retry').addEventListener('click', async (event) => {
  if (state.status.llm_enabled && !await confirmAction('重新处理这篇收藏？','将重新调用你配置的模型，可能产生 API 费用。原文会保留。')) return;
  busy(event.target, async () => { const result = await api('/articles/' + state.current.id + '/process',{method:'POST'}); toast(result.message); await openArticle(state.current.id); });
});
$('#reader-delete').addEventListener('click',async () => {
  if (!await confirmAction('删除这篇收藏？','原文、知识结构及索引会一起删除。建议先导出备份。')) return;
  await api('/articles/' + state.current.id, {method:'DELETE'}); closeDialog('reader-dialog'); state.current = null; toast('已删除收藏。'); await refreshStatus(); if (location.hash.startsWith('#article/')) location.hash = 'library'; else await route();
});

function renderChatEmpty() {
  $('#chat-messages').innerHTML = `<div class="chat-empty"><div class="empty-star">✧</div><h2>让过去的灵感，回答今天的问题。</h2><p>不必记得标题和作者。描述你的处境，找到收藏里相关的方法和真实依据。</p><div class="prompt-grid"><button class="prompt-chip" data-prompt="根据我收藏的内容，如何搭建自动客服？">如何搭建自动客服？ ↗</button><button class="prompt-chip" data-prompt="整合我收藏的 AI Agent 文章，提出三个创业方向并说明出处。">整合 AI Agent 创业思路 ↗</button><button class="prompt-chip" data-prompt="我的收藏中有哪些获客方法值得尝试？请给出具体步骤与来源。">找回曾经收藏的获客方法 ↗</button></div>${!state.status.llm_enabled ? '<p class="import-note">当前未配置语言模型，将返回真实检索片段；综合建议需连接模型。</p>' : ''}</div>`;
}
function answerHTML(answer) {
  const sources = answer.sources || []; const unique = [...new Map(sources.map((s) => [s.article_id,s])).values()];
  const sourceNumber = new Map(unique.map((s,i) => [s.article_id,i+1]));
  const claim = (c) => `<div class="answer-claim">${h(c.text)}<div>${(c.evidence || []).map((e) => citation(e,`来源 ${sourceNumber.get(e.article_id) || '↗'}`)).join('')}</div></div>`;
  let result = '<div class="chat-answer"><div class="answer-label">SECOND BRAIN · 依据你的收藏</div>';
  if (answer.mode === 'retrieval_only') result += '<div class="banner info">语言模型尚未配置。这里是相关原文检索结果，尚未生成综合回答。</div>';
  if (answer.claims?.length) result += answer.claims.map(claim).join('');
  if (answer.ai_suggestions?.length) result += '<div class="answer-section-title">AI 补充判断 · 请自行验证</div>' + answer.ai_suggestions.map((s) => `<p class="ai-suggestion">${h(s)}</p>`).join('');
  if (answer.disagreements?.length) result += '<div class="answer-section-title">不同来源的分歧</div>' + answer.disagreements.map(claim).join('');
  if (answer.gaps?.length) result += '<div class="answer-section-title">证据与边界</div>' + answer.gaps.map((s) => `<p class="answer-gap">${h(s)}</p>`).join('');
  if (unique.length) {
    result += '<div class="answer-section-title">检索到的原始来源</div>';
    result += unique.map((s,i) => `<div class="source-card"><button data-article="${h(s.article_id)}">${i+1}. ${h(s.title)}</button><small>${h(s.author || '作者未填写')} · ${h(s.category || '')}</small>${answer.mode === 'retrieval_only' ? `<p>${h(s.text)}</p>${citation({article_id:s.article_id,quote:s.text,start_offset:s.start_offset},'定位原文片段')}` : ''}${safeURL(s.url) ? `<a href="${h(safeURL(s.url))}" target="_blank" rel="noopener noreferrer">打开来源 ↗</a>` : '<small>用户手工输入，没有外部链接</small>'}</div>`).join('');
  }
  result += `<p class="answer-warning">${h(answer.warnings?.join(' ') || '')}${answer.mode === 'ai' ? ' · AI 整理可能有误，请点击引用核对。' : ''}</p></div>`;
  return result;
}
function scrollChat() { const el = $('#chat-messages'); el.scrollTop = el.scrollHeight; }
async function sendQuestion(question) {
  if (state.asking || question.trim().length < 2) return;
  state.asking = true; $('#chat-send').disabled = true;
  if (!state.session) $('#chat-messages').innerHTML = '';
  const el = $('#chat-messages');
  el.insertAdjacentHTML('beforeend', `<div class="chat-user"><span>${h(question)}</span></div><div class="typing-indicator" id="chat-pending">正在检索收藏并核对证据…</div>`);
  $('#chat-question').value = ''; scrollChat();
  try {
    const answer = await api('/chat',{method:'POST',body:{question,session_id:state.session}});
    state.session = answer.session_id; $('#chat-pending')?.remove(); el.insertAdjacentHTML('beforeend',answerHTML(answer)); await refreshSessions(); scrollChat();
  } catch (error) { $('#chat-pending')?.remove(); el.insertAdjacentHTML('beforeend', `<div class="banner error">${h(error.message)}<br>本次没有生成可验证的回答，你可以重试。</div>`); $('#chat-question').value = question; scrollChat(); }
  finally { state.asking = false; $('#chat-send').disabled = false; }
}
async function refreshSessions() {
  const result = await api('/sessions');
  $('#session-list').innerHTML = result.sessions.length ? result.sessions.map((s) => `<button class="session-button ${s.id === state.session ? 'active' : ''}" data-session="${h(s.id)}">${h(s.title)}</button>`).join('') : '<p class="import-note">新的问题，会留在这里。</p>';
}
async function loadSession(id) {
  if (state.asking) return toast('请等待当前回答完成。');
  const result = await api('/sessions/' + encodeURIComponent(id)); state.session = id;
  $('#chat-messages').innerHTML = result.messages.map((message) => message.role === 'user' ? `<div class="chat-user"><span>${h(message.payload.question)}</span></div>` : answerHTML(message.payload)).join(''); await refreshSessions(); scrollChat();
}
$('#chat-form').addEventListener('submit',(event) => { event.preventDefault(); sendQuestion($('#chat-question').value.trim()); });
$('#chat-question').addEventListener('keydown',(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('#chat-form').requestSubmit(); } });
$('#new-chat').addEventListener('click',() => { if (state.asking) return toast('请等待当前回答完成。'); state.session = null; renderChatEmpty(); refreshSessions().catch((e) => toast(e.message)); $('#chat-question').focus(); });
$('#home-ask-form').addEventListener('submit',(event) => { event.preventDefault(); if (state.asking) return toast('请等待当前回答完成，再开始新的问题。'); state.pendingQuestion = $('#home-question').value.trim(); state.session = null; location.hash = 'chat'; });

async function renderNetwork() {
  const result = await api('/articles?limit=200');
  $('#network-select').innerHTML = '<option value="">选择一篇收藏…</option>' + result.articles.filter((a) => a.excerpt).map((a) => `<option value="${h(a.id)}">${h(a.title)}</option>`).join('');
  $('#network-results').innerHTML = empty('每个问题，都可以有多个视角', '这里会展示相似方法的候选文章。要判断共识、互补与分歧，请进一步询问知识库。', '');
}
$('#network-select').addEventListener('change',async (event) => {
  if (!event.target.value) return;
  try { const result = await api('/articles/' + event.target.value + '/related'); $('#network-results').innerHTML = `<div class="banner info">${h(result.note)}</div>` + (result.hits.length ? result.hits.map(sourceResult).join('') : empty('暂未发现相关收藏','继续收集不同视角，相关方法会在这里连接。','')); } catch (error) { toast(error.message); }
});

let syncStatus = null;
const timestamp = (value) => value ? new Date(typeof value === 'number' ? value*1000 : value).toLocaleString('zh-CN') : '尚未检查';
async function renderSync(fillForm=false) {
  const s = await api('/integrations/x');
  syncStatus = s;
  const title = s.sync_enabled ? '自动同步已开启' : s.connected ? '账号已连接 · 同步已暂停' : s.client_configured ? '等待 X 官方授权' : '等待配置开发者应用';
  $('#sync-status').innerHTML = `<h2>${title}</h2><p>${s.connected ? '@'+h(s.account.username || s.account.id)+' · 每 '+s.interval_minutes+' 分钟检查一次' : '目前没有读取你的 X 收藏。完成右侧配置后，在 X 官方页面授权。'}</p><span class="state-badge ${s.sync_enabled ? '' : 'warn'}">${s.running ? '正在检查收藏' : s.sync_enabled ? '后台运行中' : '未在后台读取'}</span>`;
  $('#sync-error').hidden = !s.last_error; $('#sync-error').textContent = s.last_error;
  $('#sync-connect').disabled = !s.client_configured || s.running;
  $('#sync-connect').textContent = s.connected ? '重新授权 X ↗' : '连接 X 账号 ↗';
  $('#sync-disconnect').hidden = !s.connected && !s.client_configured;
  $('#sync-enable').hidden = s.sync_enabled; $('#sync-enable').disabled = !s.connected || !$('#sync-cost').checked || s.running;
  $('#sync-pause').hidden = !s.sync_enabled;
  $('#sync-now').disabled = !s.sync_enabled || s.running || Boolean(s.next_run && s.next_run*1000>Date.now());
  const result = s.last_result || {};
  $('#sync-results').innerHTML = `<div><span>自动入库</span><strong>${s.imported_total} 篇</strong></div><p>最近检查：${h(timestamp(s.last_checked_at))}<br>最近成功：${h(timestamp(s.last_success_at))}${s.next_run ? '<br>下次检查：'+h(timestamp(s.next_run)) : ''}</p>${result.pages ? `<p>上次读取 ${result.pages} 页 · 新增 ${result.imported || 0} 篇 · 待补全文 ${result.needs_content || 0} 篇 · 重复 ${result.duplicate || 0} 条 · 短帖跳过 ${result.skipped || 0} 条</p>` : ''}${s.catching_up ? '<p>正在分批读取更早的收藏，下次检查会继续。</p>' : ''}`;
  if (fillForm) {
    $('#sync-callback').value = s.redirect_uri;
    $('#sync-client-id').value = s.client_id;
    const interval = $('#sync-interval');
    if (![...interval.options].some((o)=>Number(o.value)===s.interval_minutes)) interval.add(new Option('每 '+s.interval_minutes+' 分钟',s.interval_minutes));
    interval.value = String(s.interval_minutes);
    $('#sync-long-only').value = String(s.long_only);
    $('#sync-page-size').value = s.page_size; $('#sync-max-pages').value = s.max_pages;
  }
}
$('#sync-config-form').addEventListener('submit',(event)=> {event.preventDefault(); busy(event.submitter,async()=> {
  await api('/integrations/x/config',{method:'PUT',body:{client_id:$('#sync-client-id').value.trim(),interval_minutes:Number($('#sync-interval').value),long_only:$('#sync-long-only').value==='true',page_size:Number($('#sync-page-size').value),max_pages:Number($('#sync-max-pages').value)}});
  await renderSync(true); toast('连接设置已保存。尚未授权的账号不会自动读取收藏。');
});});
$('#sync-cost').addEventListener('change',()=> {$('#sync-enable').disabled = !syncStatus?.connected || !$('#sync-cost').checked || syncStatus?.running;});
$('#sync-connect').addEventListener('click',(event)=>busy(event.currentTarget,async()=> {
  const result = await api('/integrations/x/authorize',{method:'POST'});
  const url = new URL(result.authorization_url);
  if (url.origin!=='https://x.com' || url.pathname!=='/i/oauth2/authorize') throw new Error('授权地址不正确，未跳转。');
  location.assign(url.href);
}));
$('#sync-enable').addEventListener('click',(event)=>busy(event.currentTarget,async()=> {
  await api('/integrations/x/switch',{method:'POST',body:{enabled:true,acknowledge_api_cost:$('#sync-cost').checked}});
  await renderSync(); await refreshStatus(); toast('自动同步已开启，新收藏将在检查后入库。');
}));
$('#sync-pause').addEventListener('click',(event)=>busy(event.currentTarget,async()=> {
  await api('/integrations/x/switch',{method:'POST',body:{enabled:false}}); await renderSync(); await refreshStatus(); toast('自动同步已暂停。');
}));
$('#sync-now').addEventListener('click',(event)=>busy(event.currentTarget,async()=> {
  try {await api('/integrations/x/sync',{method:'POST'});} finally {await renderSync(); await refreshStatus();}
},'正在检查…'));
$('#sync-disconnect').addEventListener('click',async(event)=> {
  if (!await confirmAction('断开 X 连接？','将停止读取收藏并撤销本地授权。已保存的文章和知识保留。')) return;
  busy(event.currentTarget,async()=> {const result=await api('/integrations/x/disconnect',{method:'POST'}); await renderSync(); await refreshStatus(); toast(result.message);});
});
document.querySelector('[data-open-sync]').addEventListener('click',()=>closeDialog('settings-dialog'));

async function openSettings() {
  $('#settings-categories').value = state.prefs.categories.join('\n'); $('#settings-interests').value = state.prefs.interests || ''; $('#app-token').value = sessionStorage.getItem('xsb-token') || '';
  const s = state.status;
  $('#settings-status').innerHTML = `<div class="settings-status"><strong>${s.llm_enabled ? '语言模型已配置 · ' + h(s.llm_model) : '语言模型未配置 · 基础收藏模式'}</strong><p>语义模型：${h(s.embedding_model || '尚未连接')} · ${h(s.embedding_provider || '未知')}<br>已建立 ${s.indexed || 0} 篇语义索引 · ${s.queued || 0} 个待处理任务<br>${state.browser.paired ? '免费浏览器插件已配对' : '免费浏览器插件尚未配对'}${state.browser.public_fulltext_provider === 'fxembed' ? ' · 公开帖自动补全文已启用' : ''}${s.embedding_error ? '<br>' + h(s.embedding_error) : ''}</p></div>`;
  showDialog('settings-dialog');
}
$('#preferences-form').addEventListener('submit',(event) => { event.preventDefault(); busy(event.submitter,async () => { const categories = $('#settings-categories').value.split('\n').map((c) => c.trim()).filter(Boolean); await api('/preferences',{method:'PUT',body:{categories,interests:$('#settings-interests').value}}); await refreshPrefs(); toast('偏好已保存。新分析将使用这些分类与关注方向。'); }); });
$('#token-form').addEventListener('submit',(event) => { event.preventDefault(); busy(event.submitter,async () => { const value = $('#app-token').value.trim(); if (value) sessionStorage.setItem('xsb-token',value); else sessionStorage.removeItem('xsb-token'); await init(); toast('已连接知识库。'); closeDialog('settings-dialog'); }); });
$('#export-data').addEventListener('click',(event) => busy(event.currentTarget,async () => { const result = await api('/export'); const blob = new Blob([JSON.stringify(result,null,2)],{type:'application/json'}); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'x-second-brain-' + new Date().toISOString().slice(0,10) + '.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url),1000); toast('备份已生成，由浏览器保存到你的下载位置。'); }));
$('#import-backup').addEventListener('change',async (event) => {
  const file = event.target.files?.[0]; if (!file) return;
  try {
    if (file.size > 12000000) throw new Error('备份超过 12 MB，请拆分导入。');
    const payload = JSON.parse(await file.text());
    $('#transfer-result').textContent = '正在校验并导入…';
    const result = await api('/import',{method:'POST',body:payload});
    const warnings = result.results.flatMap((r) => r.warnings || []);
    $('#transfer-result').textContent = result.message + ` 共 ${result.results.length} 篇，恢复 ${result.restored_sessions} 个对话。` + (warnings.length ? '\n' + warnings.join('\n') : '');
    await refreshStatus(); await route();
  } catch (error) { $('#transfer-result').textContent = error.message; } finally { event.target.value = ''; }
});
$('#reindex').addEventListener('click',async (event) => {
  if (!await confirmAction('重建知识索引？','将处理所有已有正文的收藏。开启语言模型时会重新分析并可能产生费用，文章较多时请耐心等待。')) return;
  busy(event.target,async () => { const result = await api('/reindex',{method:'POST'}); $('#transfer-result').textContent = `${result.queued} 篇已加入队列。${result.message}`; await refreshStatus(); });
});

function confirmAction(title, message) {
  $('#confirm-title').textContent = title; $('#confirm-message').textContent = message; showDialog('confirm-dialog');
  return new Promise((resolve) => {
    const dialog = $('#confirm-dialog'); const yes = $('#confirm-yes'); const no = $('#confirm-cancel');
    const finish = (value) => { dialog.removeEventListener('cancel',cancel); yes.onclick = null; no.onclick = null; dialog.close(); resolve(value); };
    const cancel = (event) => { event.preventDefault(); finish(false); };
    yes.onclick = () => finish(true); no.onclick = () => finish(false); dialog.addEventListener('cancel',cancel,{once:true});
  });
}

document.addEventListener('click',(event) => {
  const target = event.target.closest('button,a,[data-article]'); if (!target) return;
  if (target.dataset.close) closeDialog(target.dataset.close);
  if (target.dataset.action === 'import') openImport();
  if (target.dataset.action === 'settings') openSettings();
  if (target.dataset.action === 'attention') {
    state.category = ''; $('#category-filter').value = ''; $('#unread-filter').checked = false;
    $('#attention-filter').checked = true; $('#search-query').value = '';
    if (location.hash === '#library') renderLibrary().catch((e) => toast(e.message)); else location.hash = 'library';
  }
  if (target.dataset.importMode) setImportMode(target.dataset.importMode);
  if (target.dataset.readerMode) { state.readerMode = target.dataset.readerMode; if (state.readerMode !== 'original') state.evidence = null; renderReader(); $('#reader-dialog').scrollTop = 0; }
  if (target.dataset.article) { event.preventDefault(); openArticle(target.dataset.article); }
  if (target.dataset.citation) { const evidence = state.citations.get(target.dataset.citation); if (evidence) openArticle(evidence.article_id,evidence); }
  if (target.dataset.category) { event.preventDefault(); state.category = target.dataset.category; $('#category-filter').value = state.category; if (location.hash === '#library') renderLibrary().catch((e) => toast(e.message)); else location.hash = 'library'; }
  if (target.dataset.route === 'library' && !target.dataset.category) { state.category = ''; $('#category-filter').value = ''; $('#attention-filter').checked = false; if (state.route === 'library') renderLibrary().catch((e) => toast(e.message)); }
  if (target.dataset.prompt) sendQuestion(target.dataset.prompt);
  if (target.dataset.session) loadSession(target.dataset.session).catch((e) => toast(e.message));
});
document.addEventListener('keydown',(event) => { if (event.key.toLowerCase() === 'n' && !event.ctrlKey && !event.metaKey && !event.altKey && !['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName) && !document.querySelector('dialog[open]')) { event.preventDefault(); openImport(); } });
$('#search-form').addEventListener('submit',(event) => { event.preventDefault(); busy(event.submitter,runSearch,'检索中…'); });
$('#category-filter').addEventListener('change',(event) => { state.category = event.target.value; (state.search ? runSearch() : renderLibrary()).catch((e) => toast(e.message)); });
$('#unread-filter').addEventListener('change',() => (state.search ? runSearch() : renderLibrary()).catch((e) => toast(e.message)));
$('#attention-filter').addEventListener('change',() => { $('#search-query').value = ''; renderLibrary().catch((e) => toast(e.message)); });
$('#sort-filter').addEventListener('change',() => renderLibrary().catch((e) => toast(e.message)));
$('#load-more').addEventListener('click',(event) => busy(event.currentTarget,() => renderLibrary(true)));
window.addEventListener('hashchange',route);

let pollRunning = false;
let lastPoll = 0;
async function pollKnowledge(force=false) {
  if (document.hidden || pollRunning) return;
  const interval = state.status.queued || state.status.automatic_sync || state.route === 'sync' ? 4000 : 12000;
  if (!force && Date.now() - lastPoll < interval) return;
  pollRunning = true;
  lastPoll = Date.now();
  const before = JSON.stringify([state.status, state.browser]);
  const recovering = !$('#connection-error').hidden;
  try {
    await refreshStatus();
    if (recovering) await refreshPrefs();
    const changed = recovering || before !== JSON.stringify([state.status, state.browser]);
    if (state.route === 'sync') await renderSync();
    if (changed && state.route === 'home') await renderHome();
    if (changed && state.route === 'library' && !state.search && state.offset <= 50) await renderLibrary();
    if (state.current && $('#reader-dialog').open && ['queued','processing'].includes(state.current.status)) await openArticle(state.current.id);
  } catch (error) {
    $('#connection-error').textContent = error.message + ' 页面会自动重试连接。';
    $('#connection-error').hidden = false;
  }
  finally { pollRunning = false; }
}
setInterval(() => pollKnowledge(),4000);
document.addEventListener('visibilitychange',() => { if (!document.hidden) pollKnowledge(true); });
async function init() {
  try { await Promise.all([refreshStatus(),refreshPrefs()]); await route(); }
  catch (error) { $('#connection-error').textContent = error.message; $('#connection-error').hidden = false; $('#model-status').textContent = '连接设置'; $('#home-priority').innerHTML = empty('连接你的知识空间','确认服务已启动。如果设置了 APP_TOKEN，请打开设置连接。','settings'); }
}
$('#today-label').textContent = new Date().toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long'});
init();

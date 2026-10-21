'use strict';
const docsEscape = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function loadDocs() {
  const target = document.querySelector('#api-output');
  try {
    const token = document.querySelector('#docs-token').value || sessionStorage.getItem('xsb-token');
    const response = await fetch('/api/openapi.json',{headers:token ? {'Authorization':'Bearer '+token} : {}});
    if (!response.ok) throw new Error('无法载入接口说明；若返回 401，请输入 APP_TOKEN。');
    const spec = await response.json();
    target.innerHTML = Object.entries(spec.paths).map(([path,operations]) => `<section class="settings-section"><h2>${docsEscape(path)}</h2>${Object.entries(operations).filter(([method]) => ['get','post','put','patch','delete'].includes(method)).map(([method,operation]) => `<div class="search-result"><h3>${docsEscape(method.toUpperCase())} · ${docsEscape(operation.summary)}</h3>${operation.parameters?.length ? `<p>参数：${docsEscape(operation.parameters.map((p) => p.name + (p.required ? '（必填）' : '')).join('、'))}</p>` : ''}${operation.requestBody ? `<p>请求体：${docsEscape(JSON.stringify(operation.requestBody.content['application/json']?.schema || {}))}</p>` : ''}<p>返回：${docsEscape(Object.keys(operation.responses || {}).join(' / '))}</p></div>`).join('')}</section>`).join('') + `<section class="settings-section"><h2>数据结构</h2><pre class="original-text">${docsEscape(JSON.stringify(spec.components?.schemas,null,2))}</pre></section>`;
  } catch (error) { target.textContent = error.message; }
}
document.querySelector('#docs-token-form').addEventListener('submit',(event) => {event.preventDefault(); loadDocs();});
loadDocs();

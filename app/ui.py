PAGE = r"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>网页测试 MVP</title><style>body{max-width:1000px;margin:32px auto;font-family:sans-serif}
button,input{margin:8px;padding:8px}pre{white-space:pre-wrap;background:#f4f5f7;padding:16px}
.warn{color:#a43}#downloads button{display:inline-block}</style>
<h1>网页测试 MVP：表格 → 计划 → 浏览器 → 证据 → 报告</h1>
<p class="warn">仅本机单用户工具。只上传获授权的测试用例；截图可能包含页面业务数据。</p>
<p>测试环境：<strong id="environment"></strong></p>
<input type="file" id="file" accept=".xlsx"><button id="upload">上传并预览计划</button>
<button id="run" disabled>执行已预览计划</button><p id="status">尚未上传</p>
<div id="downloads"></div><pre id="output"></pre>
<script>
const TOKEN = '__LOCAL_TOKEN__';
let plan = null;
const el = id => document.getElementById(id);
el('environment').textContent = '__BASE_TEXT__';
async function request(url, options={}) {
  options.headers = {...options.headers, 'X-Local-Token': TOKEN};
  const response = await fetch(url, options);
  const value = await response.json();
  if (!response.ok) throw Error(value.error || '请求失败');
  return value;
}
function show(v){el('output').textContent = JSON.stringify(v,null,2);}
el('upload').onclick = async () => {
  plan = null; el('run').disabled = true; el('downloads').replaceChildren();
  try {
    const file = el('file').files[0];
    if(!file || !file.name.toLowerCase().endsWith('.xlsx')) throw Error('请选择 XLSX 文件');
    const value = await request('/api/plans', {method:'POST',
      headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},
      body:await file.arrayBuffer()});
    plan = value; show(value); el('status').textContent = '计划已校验，请确认后执行';
    el('run').disabled = false;
  } catch(e){el('status').textContent = e.message;}
};
async function download(rid, name){
  try {
    const response = await fetch('/files/'+rid+'/'+name, {headers:{'X-Local-Token':TOKEN}});
    if(!response.ok) throw Error('文件尚未生成或不可用');
    const url = URL.createObjectURL(await response.blob());
    const a = document.createElement('a'); a.href=url; a.download=name; a.click();
    setTimeout(()=>URL.revokeObjectURL(url), 10000);
  } catch(e){el('status').textContent=e.message;}
}
function addDownload(rid, name){
  const b=document.createElement('button'); b.textContent='下载 '+name;
  b.onclick=()=>download(rid,name); el('downloads').appendChild(b);
}
el('run').onclick = async () => {
  if(!plan) return;
  el('run').disabled=true;
  try {
    const v=await request('/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({plan_id:plan.plan_id, hash:plan.hash})});
    for(;;){
      const state=await request('/api/runs/'+v.run_id);
      el('status').textContent='任务状态：'+state.status;
      show(state);
      if(!['QUEUED','RUNNING'].includes(state.status)){
        for(const name of ['report.json','report.html','report.xlsx']) addDownload(v.run_id,name);
        for(const c of state.result?.cases || []) for(const s of c.steps)
          if(s.screenshot) addDownload(v.run_id,s.screenshot);
        break;
      }
      await new Promise(r=>setTimeout(r,1500));
    }
  }catch(e){el('status').textContent=e.message; el('run').disabled=false;}
};
</script></html>"""

DEMO = r"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>测试登录页</title>
<h1>本地测试登录页</h1><label>用户名<input id="user"></label>
<label>密码<input id="password" type="password"></label><button id="login">登录</button>
<div id="message"></div><script>
document.getElementById('login').onclick=()=>{
 document.getElementById('message').textContent=
 document.getElementById('user').value==='demo' &&
 document.getElementById('password').value==='demo' ? '欢迎回来' : '登录失败';
};
</script></html>"""

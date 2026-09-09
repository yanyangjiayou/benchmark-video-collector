from __future__ import annotations
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from .pipeline import export_excel, run_job
from .rules import CollectionRequest

app = FastAPI(title="对标视频采集助手")
state = {"status": "idle", "logs": [], "output": None, "error": None, "progress": {}, "records": [], "started_at": None}
login_state = {"status": "unknown", "platform": None, "message": "尚未检查登录"}

class StartPayload(BaseModel):
    request: CollectionRequest
    account_label: str = ""
    transcription_model: Literal["small", "medium"] = "small"
    glossary: str = ""

def add_log(message: str) -> None:
    state["logs"].append(message)
    state["logs"] = state["logs"][-300:]

def worker(payload: StartPayload) -> None:
    try:
        state.update(status="running", logs=[], output=None, error=None, progress={"stage": "正在启动采集"}, records=[], started_at=time.time())
        def update_progress(value: dict) -> None:
            state["progress"] = dict(value)
        def update_records(value: list[dict]) -> None:
            state["records"] = list(value)
        result, summary, records = run_job(payload.request, payload.account_label.strip(), add_log, update_progress,
                                           update_records, payload.transcription_model, payload.glossary)
        state.update(status="done", output=str(result), progress=summary, records=records)
    except Exception as exc:
        add_log(f"失败：{exc}")
        state.update(status="error", error=str(exc))

def login_worker(platform: str) -> None:
    login_state.update(status="checking", platform=platform, message="正在检查登录；如未登录将打开扫码页")
    root = Path(__file__).resolve().parents[1]
    vendor = root / "vendor" / "MediaCrawler"
    env = {**os.environ, "PYTHONPATH": f"{root}:{vendor}", "MPLCONFIGDIR": str(root / "runtime/matplotlib")}
    process = subprocess.run(
        [str(vendor / ".venv/bin/python"), "-m", "mvp.login_worker", platform],
        cwd=vendor, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if process.returncode == 0 and "MVP_LOGIN_CONFIRMED" in process.stdout:
        login_state.update(status="logged_in", message="已登录，可以开始采集")
    else:
        message = (process.stdout + "\n" + process.stderr).strip()[-600:]
        login_state.update(status="not_logged_in", message=message or "未登录或登录超时")

@app.get("/", response_class=HTMLResponse)
def home():
    return HTML

@app.post("/api/preview")
def preview(payload: StartPayload):
    return payload.request.confirmation()

@app.post("/api/start")
def start(payload: StartPayload):
    if login_state["status"] != "logged_in" or login_state["platform"] != payload.request.platform:
        raise HTTPException(400, "请先点击确认登录状态")
    if state["status"] == "running":
        raise HTTPException(409, "已有任务正在运行")
    threading.Thread(target=worker, args=(payload,), daemon=True).start()
    return {"ok": True}

@app.post("/api/login/{platform}")
def login(platform: str):
    if platform not in {"xhs", "dy"}:
        raise HTTPException(400, "不支持的平台")
    if login_state["status"] == "checking":
        return login_state
    threading.Thread(target=login_worker, args=(platform,), daemon=True).start()
    return {"ok": True}

@app.get("/api/login-status")
def get_login_status():
    return login_state

@app.get("/api/status")
def status():
    return state

@app.get("/api/download")
def download():
    output = state.get("output")
    if not output or not Path(output).is_file():
        raise HTTPException(404, "当前没有可下载的结果")
    return FileResponse(output, filename=Path(output).name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.get("/api/download-current")
def download_current():
    records = list(state.get("records") or [])
    if not records:
        raise HTTPException(404, "当前还没有已完成的结果")
    destination = Path(__file__).resolve().parents[1] / "output" / "当前已完成结果.xlsx"
    export_excel(records, destination)
    return FileResponse(destination, filename="当前已完成结果.xlsx",
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

HTML = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>对标视频采集助手</title><style>
body{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;background:#f4f6fb;color:#182033;margin:0}
main{max-width:920px;margin:36px auto;padding:0 20px}.card{background:white;border-radius:16px;padding:24px;box-shadow:0 8px 32px #23304d12}
h1{margin-top:0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}label{display:block;font-size:14px;color:#526079}
input,select{box-sizing:border-box;width:100%;padding:11px;margin-top:6px;border:1px solid #d9dfeb;border-radius:9px}
.full{grid-column:1/-1}button{border:0;border-radius:9px;padding:12px 20px;background:#315efb;color:white;font-weight:600;cursor:pointer}
button.secondary{background:#e9edfa;color:#273451}.actions{display:flex;gap:12px;margin-top:20px;flex-wrap:wrap}
#rulePreview,#status,#results{margin-top:20px;padding:16px;background:#f6f8fc;border-radius:10px;white-space:pre-wrap}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:12px}.metric{background:white;padding:12px;border-radius:8px}.metric b{display:block;font-size:22px}
.download{display:inline-block;margin-top:14px;padding:10px 16px;background:#315efb;color:white;border-radius:8px;text-decoration:none}
table{width:100%;border-collapse:collapse;margin-top:12px;background:white}th,td{padding:9px;border-bottom:1px solid #e4e8f0;text-align:left;vertical-align:top}th{white-space:nowrap}.scroll{overflow:auto}
small{color:#6d7890}@media(max-width:650px){.grid{grid-template-columns:1fr}}
</style></head><body><main><div class="card"><h1>对标视频采集助手</h1>
<p>小红书 / 抖音 · 仅视频 · 本地转写 · Excel导出</p><div class="grid">
<label>平台<select id="platform"><option value="xhs">小红书</option><option value="dy">抖音</option></select></label>
<label>触发方式<select id="trigger" onchange="toggle()"><option value="creator_url">指定博主主页</option><option value="keyword">关键词发现博主</option></select></label>
<label class="full" id="urlbox">博主主页链接<input id="url" value="https://xhslink.cn/o/4TqFUwvrIuJ" placeholder="粘贴主页链接"></label>
<label class="full" id="keybox" style="display:none">关键词（逗号分隔）<input id="keywords" placeholder="看房,房产"></label>
<label id="fanbox" style="display:none">最低粉丝数<input id="fans" type="number" placeholder="例如2000"></label>
<label>账号备注（可选）<input id="account" placeholder="用于Excel账号列"></label>
<label>开始日期<input id="start" type="date" value="2026-08-01"></label><label>结束日期<input id="end" type="date" value="2026-09-09"></label>
<label>最低点赞数<input id="likes" type="number" value="200"></label><label>最多条数<input id="limit" type="number" value="20" min="1" max="50"></label>
<label>转写模式<select id="model"><option value="small">标准（速度较快）</option><option value="medium">准确（速度较慢）</option></select></label>
<label>专业词库（可选）<input id="glossary" placeholder="例如：青山湖,桃李春风,临安"></label>
</div><small>日期不填默认最近30天；点赞不填默认200；条数不填默认10。评论、图片和代理默认关闭。</small>
<div class="actions"><button class="secondary" onclick="preview()">检查规则</button><button onclick="checkLogin()">1. 确认登录状态</button><button id="startButton" onclick="startJob()" disabled>2. 开始采集</button></div>
<div id="loginStatus">登录状态：尚未检查</div><div id="rulePreview"></div><div id="status">采集状态：尚未开始</div><div id="results" style="display:none"></div></div></main>
<script>
const el=id=>document.getElementById(id);
function toggle(){let k=el('trigger').value==='keyword';el('urlbox').style.display=k?'none':'block';el('keybox').style.display=k?'block':'none';el('fanbox').style.display=k?'block':'none'}
function payload(){let r={platform:el('platform').value,trigger_type:el('trigger').value,creator_url:el('url').value,
keywords:el('keywords').value.split(',').map(x=>x.trim()).filter(Boolean),min_likes:Number(el('likes').value||200),max_items:Number(el('limit').value||10),
video_only:true,transcribe_video:true};if(el('start').value)r.start_date=el('start').value;if(el('end').value)r.end_date=el('end').value;
if(el('fans').value)r.min_followers=Number(el('fans').value);return {request:r,account_label:el('account').value,transcription_model:el('model').value,glossary:el('glossary').value}}
async function preview(){let x=await fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())});
el('rulePreview').textContent=x.ok?JSON.stringify(await x.json(),null,2):await x.text()}
async function checkLogin(){el('loginStatus').textContent='登录状态：正在检查…';await fetch('/api/login/'+el('platform').value,{method:'POST'});pollLogin()}
async function pollLogin(){let x=await fetch('/api/login-status'),s=await x.json();el('loginStatus').textContent='登录状态：'+s.message;el('startButton').disabled=!(s.status==='logged_in'&&s.platform===el('platform').value);if(s.status==='checking')setTimeout(pollLogin,1200)}
async function startJob(){if(!window.confirm('已确认登录，现在开始采集？'))return;
el('status').textContent='采集状态：正在提交任务…';
let x=await fetch('/api/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())});
if(!x.ok){el('status').textContent=await x.text();return}poll()}
function esc(v){return String(v??'').replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]))}
function duration(n){n=Math.max(0,Math.round(n||0));return n<60?`${n}秒`:`${Math.floor(n/60)}分${n%60}秒`}
function render(s){let p=s.progress||{}, names={idle:'尚未开始',running:'正在采集',done:'采集完成',error:'采集失败'};
let message=s.status==='idle'?'请确认登录，然后点击“开始采集”。':s.status==='running'?'程序正在执行，请保持页面打开。':s.status==='done'?(p.exported?`采集完成，共导出 ${p.exported} 条结果。${p.media_missing?`其中 ${p.media_missing} 条未取得视频文件，无法转写。`:''}`:`采集完成，但没有符合条件的数据。请降低最低点赞数或调整日期范围后重试。`):`采集失败：${s.error||'请展开运行记录查看原因'}`;
let elapsed=s.started_at?Date.now()/1000-s.started_at:0, estimate=p.estimated_total_seconds||90+Number(el('limit').value||10)*75, remaining=Math.max(0,estimate-elapsed);
let timing=s.status==='running'?`<div>当前阶段：${esc(p.stage||'正在处理')}。已用 ${duration(elapsed)}，预计还需约 ${duration(remaining)}。时间为估算值，取决于视频长度和网络速度。</div>`:'';
el('status').innerHTML=`<b>采集状态：${names[s.status]||s.status}</b><div>${message}</div>${timing}<div class="metrics"><div class="metric"><b>${p.found??0}</b>发现内容</div><div class="metric"><b>${p.videos??0}</b>视频</div><div class="metric"><b>${p.eligible??0}</b>符合条件</div><div class="metric"><b>${p.transcribed??0}</b>完成转写</div><div class="metric"><b>${p.media_missing??0}</b>未完成</div></div>`;
let rows=s.records||[];if(rows.length||s.status==='done'){let body=rows.map(r=>`<tr><td>${esc(r['账号'])}</td><td>${esc(r['标题'])}</td><td>${esc(r['发布时间'])}</td><td>${esc(r['视频转文字'])}</td><td>${esc(r['点赞数'])}</td><td>${esc(r['收藏数'])}</td><td><a href="${esc(r['原始链接'])}" target="_blank">查看原文</a></td></tr>`).join('');el('results').style.display='block';let button=s.status==='done'?'<a class="download" href="/api/download">下载完整 Excel</a>':'<a class="download" href="/api/download-current">下载当前已处理结果</a>';el('results').innerHTML=`<b>采集结果</b><div>${rows.length?`已处理 ${rows.length} 条；成功和未成功的项目都会显示，可随时下载。`:'本次没有符合筛选条件的结果，Excel 中只有表头。'}</div>${rows.length?`<div class="scroll"><table><thead><tr><th>账号</th><th>标题</th><th>发布时间</th><th>视频转文字或失败原因</th><th>点赞</th><th>收藏</th><th>链接</th></tr></thead><tbody>${body}</tbody></table></div>`:''}${button}`}else{el('results').style.display='none'}
let logs=(s.logs||[]).slice(-20).map(esc).join('\n');if(logs)el('status').insertAdjacentHTML('beforeend',`<details><summary>查看运行记录</summary><pre>${logs}</pre></details>`)}
async function poll(){let x=await fetch('/api/status'),s=await x.json();render(s);if(s.status==='running')setTimeout(poll,1500)}
window.addEventListener('DOMContentLoaded',()=>{toggle();pollLogin();poll()});
</script></body></html>"""

from __future__ import annotations
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from .access_guard import PlatformAccessGuard
from .exports import MEDIA_TYPE, list_exports, resolve_export
from .pipeline import JobCancelled, export_excel, run_job
from .rules import CollectionRequest

APP_ID = "benchmark-video-collector"
app = FastAPI(title="Video 采集助手")
ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output"
state = {"status": "idle", "logs": [], "output": None, "error": None, "progress": {}, "records": [], "started_at": None}
access_guard = PlatformAccessGuard(ROOT / "runtime" / "platform_access_guard.json")


def initial_login_state(platform: str) -> dict:
    blocked = access_guard.get(platform)
    if blocked:
        return {
            "status": "restricted",
            "platform": platform,
            "message": "检测到平台操作频繁或安全验证，已暂停该平台。请先在官方页面恢复正常访问。",
            "detected_at": blocked.get("detected_at"),
        }
    return {"status": "unknown", "platform": platform, "message": "尚未检查登录"}


login_states = {platform: initial_login_state(platform) for platform in ("xhs", "dy")}
task_lock = threading.RLock()
cancel_event = threading.Event()
active_process: subprocess.Popen | None = None

class StartPayload(BaseModel):
    request: CollectionRequest
    account_label: str = ""
    transcription_model: Literal["small", "medium"] = "small"
    glossary: str = ""


@app.get("/api/instance")
def instance_info() -> dict[str, str]:
    """Identify this service so launchers never open another local copy by mistake."""
    return {"app_id": APP_ID, "data_scope": "video"}

def add_log(message: str) -> None:
    state["logs"].append(message)
    state["logs"] = state["logs"][-300:]

def worker(payload: StartPayload) -> None:
    global active_process

    def observe_process(process: subprocess.Popen | None) -> None:
        global active_process
        with task_lock:
            active_process = process

    try:
        def update_progress(value: dict) -> None:
            state["progress"] = dict(value)
        def update_records(value: list[dict]) -> None:
            state["records"] = list(value)
        result, summary, records = run_job(payload.request, payload.account_label.strip(), add_log, update_progress,
                                           update_records, payload.transcription_model, payload.glossary,
                                           cancel_event, observe_process)
        state.update(status="done", output=str(result), progress=summary, records=records)
    except JobCancelled as exc:
        add_log(str(exc))
        state.update(status="stopped", error=None, progress={**state.get("progress", {}), "stage": "已停止"})
    except Exception as exc:
        add_log(f"失败：{exc}")
        state.update(status="error", error=str(exc))
        message = str(exc)
        platform_state = login_states[payload.request.platform]
        if payload.request.platform == "xhs" and "操作频繁" in message:
            blocked = access_guard.block("xhs", message)
            platform_state.update(
                status="restricted",
                message="检测到小红书操作频繁或安全验证，已停止并锁定后续采集。请先在官方页面恢复正常访问。",
                detected_at=blocked["detected_at"],
            )
        elif "登录已失效" in message or "登录态未就绪" in message:
            platform_name = "小红书" if payload.request.platform == "xhs" else "抖音"
            platform_state.update(status="not_logged_in", message=f"{platform_name}登录窗口已关闭或登录失效，请重新确认登录")
    finally:
        with task_lock:
            active_process = None

def login_worker(platform: str) -> None:
    platform_state = login_states[platform]
    platform_state.update(status="checking", platform=platform, message="正在检查登录；如未登录将打开扫码页")
    root = Path(__file__).resolve().parents[1]
    vendor = root / "vendor" / "MediaCrawler"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(root), str(vendor))),
        "MPLCONFIGDIR": str(root / "runtime/matplotlib"),
    }
    try:
        process = subprocess.run(
            [sys.executable, "-m", "mvp.login_worker", platform],
            cwd=vendor, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=210
        )
        if process.returncode == 0 and "MVP_LOGIN_CONFIRMED" in process.stdout:
            platform_state.update(status="logged_in", message="已登录，可以开始采集")
            return
        details = (process.stdout + "\n" + process.stderr).strip()
        details = re.sub(r"(?i)(cookie|authorization|xsec_token|mstoken)(['\"]?\s*[:=]\s*)[^\n]+", r"\1\2[已隐藏]", details)
        log_path = root / "runtime" / f"login_{platform}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(details, encoding="utf-8")
        if platform == "xhs" and "MVP_XHS_ACCESS_RESTRICTED" in details:
            blocked = access_guard.block("xhs", "登录检查时检测到小红书操作频繁或安全验证")
            platform_state.update(
                status="restricted",
                message="小红书仍处于操作频繁或安全验证状态，已暂停继续登录和采集。",
                detected_at=blocked["detected_at"],
            )
            return
        if "Timeout" in details or "登录超时" in details or "login qrcode not found" in details:
            message = "登录未完成：请重新确认登录，并在弹出的平台窗口内扫码、确认或完成验证。"
        elif "TargetClosed" in details or "closed" in details.lower():
            message = "登录窗口已关闭，请重新确认登录，并保留窗口直到页面提示登录成功。"
        else:
            message = "登录检查失败，请重试。详细错误已保存在本机运行记录中。"
        platform_state.update(status="not_logged_in", message=message)
    except subprocess.TimeoutExpired:
        platform_state.update(status="not_logged_in", message="登录检查超时，请重新确认登录并在平台窗口完成扫码或验证。")
    except Exception as exc:
        platform_state.update(status="not_logged_in", message=f"无法启动登录检查：{exc}")

@app.get("/", response_class=HTMLResponse)
def home():
    return HTML

@app.post("/api/preview")
def preview(payload: StartPayload):
    return payload.request.confirmation()

@app.post("/api/start")
def start(payload: StartPayload):
    with task_lock:
        blocked = access_guard.get(payload.request.platform)
        if blocked:
            raise HTTPException(423, "该平台因操作频繁或安全验证已暂停；请先在官方页面恢复，再点击“已恢复，重新检查”")
        platform_state = login_states[payload.request.platform]
        if platform_state["status"] != "logged_in":
            raise HTTPException(400, "请先点击确认登录状态")
        if state["status"] in {"running", "stopping"}:
            raise HTTPException(409, "已有任务正在运行")
        cancel_event.clear()
        state.update(status="running", logs=[], output=None, error=None, progress={"stage": "正在启动采集"}, records=[], started_at=time.time())
        threading.Thread(target=worker, args=(payload,), daemon=True).start()
    return {"ok": True}

@app.post("/api/login/{platform}")
def login(platform: str):
    if platform not in {"xhs", "dy"}:
        raise HTTPException(400, "不支持的平台")
    with task_lock:
        if access_guard.get(platform):
            raise HTTPException(423, "平台访问已暂停；请先在官方页面确认恢复正常，再点击“已恢复，重新检查”")
        if state["status"] in {"running", "stopping"}:
            raise HTTPException(409, "采集运行期间不能启动登录检查")
        if any(item["status"] == "checking" for item in login_states.values()):
            raise HTTPException(409, "另一个登录检查正在进行，请稍候")
        login_states[platform].update(status="checking", message="正在启动登录检查")
        threading.Thread(target=login_worker, args=(platform,), daemon=True).start()
    return {"ok": True}

@app.get("/api/login-status")
def get_login_status(platform: str = "xhs"):
    if platform not in login_states:
        raise HTTPException(400, "不支持的平台")
    return login_states[platform]


@app.post("/api/access-guard/{platform}/clear")
def clear_access_guard(platform: str):
    if platform not in login_states:
        raise HTTPException(400, "不支持的平台")
    with task_lock:
        if state["status"] in {"running", "stopping"}:
            raise HTTPException(409, "任务运行期间不能解除暂停")
        access_guard.clear(platform)
        login_states[platform] = initial_login_state(platform)
    return {"ok": True}


@app.post("/api/stop")
def stop():
    with task_lock:
        if state["status"] not in {"running", "stopping"}:
            return {"ok": True, "status": state["status"]}
        cancel_event.set()
        state.update(status="stopping", progress={**state.get("progress", {}), "stage": "正在安全停止"})
        process = active_process
        if process is not None and process.poll() is None:
            process.terminate()
    return {"ok": True, "status": "stopping"}

@app.get("/api/status")
def status():
    return state

@app.get("/api/exports")
def exports():
    return {"items": list_exports(OUTPUT_DIR)}

@app.get("/api/exports/{filename}")
def download_export(filename: str):
    path = resolve_export(OUTPUT_DIR, filename)
    if path is None:
        raise HTTPException(404, "Excel 文件不存在")
    return FileResponse(path, filename=path.name, media_type=MEDIA_TYPE)

@app.get("/api/download")
def download():
    output = state.get("output")
    if not output or not Path(output).is_file():
        raise HTTPException(404, "当前没有可下载的结果")
    return FileResponse(output, filename=Path(output).name, media_type=MEDIA_TYPE)

@app.get("/api/download-current")
def download_current():
    records = list(state.get("records") or [])
    if not records:
        raise HTTPException(404, "当前还没有已完成的结果")
    destination = OUTPUT_DIR / "当前已完成结果.xlsx"
    export_excel(records, destination)
    return FileResponse(destination, filename="当前已完成结果.xlsx", media_type=MEDIA_TYPE)

HTML = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Video 采集助手</title><style>
:root{color-scheme:light;--ink:#182036;--muted:#687188;--line:#e3e7f0;--canvas:#f4f6fb;--accent:#ef4764;--accent-dark:#d73553;--blue:#5b70f1;--navy:#1e263b;--amber:#f5b942;--violet:#8a66e9;--mint:#35b68a}
*{box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:var(--canvas);color:var(--ink);margin:0;min-height:100vh;font-size:16px;line-height:1.55;position:relative}body:before{content:"";position:absolute;inset:0 0 auto;height:270px;background:#e8ecfb;z-index:0}body:after{content:"";position:absolute;right:0;top:0;width:26vw;min-width:260px;height:170px;background:#ffe1e7;border-radius:0 0 0 72px;z-index:0;pointer-events:none}
main{position:relative;z-index:1;max-width:1180px;margin:0 auto;padding:34px 24px 64px}.app-header{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:24px;padding:0 4px}.title-wrap{display:flex;align-items:center;gap:14px}.brand-mark{display:grid;place-items:center;width:48px;height:48px;border-radius:15px;background:var(--accent);color:white;font-size:22px;font-weight:850;box-shadow:7px 7px 0 #f8bd49}.app-header h1{margin:0;font-size:29px;letter-spacing:-.025em}.app-header p{margin:3px 0 0;color:#59647c;font-size:14px}.local-badge{display:flex;align-items:center;gap:8px;padding:8px 12px;border:1px solid #d7dcec;border-radius:999px;background:#ffffffd9;color:#45516c;font-size:13px;font-weight:700}.local-badge:before{content:"";width:8px;height:8px;border-radius:50%;background:var(--mint);box-shadow:0 0 0 4px #35b68a1c}
.workspace{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(330px,.85fr);gap:20px;align-items:start}.card{background:#fff;border:1px solid #e0e4ed;border-radius:20px;padding:26px;box-shadow:0 15px 42px #26324d12}.form-card{position:relative;overflow:hidden;border-top:5px solid var(--blue)}.form-card:after{content:"";position:absolute;right:-38px;top:-48px;width:120px;height:120px;border-radius:30px;background:#fff0b9;transform:rotate(18deg);z-index:0}.form-card>*{position:relative;z-index:1}.card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:22px}.eyebrow{display:block;color:var(--accent);font-size:12px;font-weight:850;letter-spacing:.11em;text-transform:uppercase}.card h2{margin:2px 0 0;font-size:21px;letter-spacing:-.015em}.card-copy{margin:4px 0 0;color:var(--muted);font-size:14px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:17px 16px}.section-heading{display:flex;align-items:center;gap:10px;margin:8px 0 -3px;padding:10px 12px;border-radius:12px}.section-heading:first-child{margin-top:0}.section-heading span{display:grid;place-items:center;width:27px;height:27px;border-radius:8px;background:#fff;color:currentColor;font-size:12px;font-weight:850;box-shadow:0 3px 10px #2734510c}.section-heading b{font-size:15px}.tone-source{background:#edf0ff;color:#4659bd}.tone-filter{background:#fff1d5;color:#8f6210}.tone-transcribe{background:#f1ebff;color:#6a49bd}.full{grid-column:1/-1}label{display:block;color:#3e485d;font-size:14px;font-weight:680}
input,select{width:100%;height:48px;margin-top:7px;padding:0 13px;border:1px solid #d7dce7;border-radius:11px;background:#fff;color:var(--ink);font:inherit;font-size:15px;outline:none;transition:border-color .18s,box-shadow .18s,background .18s}input::placeholder{color:#9ea7b9}input:hover,select:hover{border-color:#abb4c8}input:focus,select:focus{border-color:var(--blue);box-shadow:0 0 0 4px #5b70f116}
.form-note{display:block;margin-top:16px;padding:12px 14px;border-left:4px solid var(--mint);border-radius:0 10px 10px 0;background:#edfaf6;color:#526b64;font-size:13px}.safety-strip{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px}.safety-item{padding:10px 11px;border:1px solid #e4e7f0;border-radius:11px;background:#fafbfe;color:#59647a;font-size:12px}.safety-item b{display:block;color:#29344b;font-size:13px}.actions{display:grid;grid-template-columns:auto 1fr 1fr;gap:10px;margin-top:20px}button{min-height:46px;border:0;border-radius:11px;padding:0 18px;background:var(--accent);color:white;font:inherit;font-size:14px;font-weight:760;cursor:pointer;transition:transform .15s,background .15s,box-shadow .15s}button:hover:not(:disabled){background:var(--accent-dark);box-shadow:0 8px 18px #ef476424;transform:translateY(-1px)}button:focus-visible,.download:focus-visible{outline:3px solid #5b70f138;outline-offset:2px}button:disabled{cursor:not-allowed;background:#d9dde6;color:#929bac;box-shadow:none}.secondary{background:var(--navy);color:#fff}.secondary:hover:not(:disabled){background:#12192b}.ghost{background:#edf0ff;color:#485dbe;border:1px solid #dce1fb}.ghost:hover:not(:disabled){background:#e2e7ff;box-shadow:none}.recovery{display:none;grid-column:1/-1;background:#b36b16}.recovery:hover:not(:disabled){background:#94560e}.stop-task{display:none;width:100%;margin-top:14px;background:#ffffff12;color:#fff;border:1px solid #ffffff28}.stop-task:hover:not(:disabled){background:#ef47642b;box-shadow:none}
#loginStatus{display:flex;align-items:center;min-height:42px;margin-top:12px;padding:10px 13px;border-radius:10px;background:#f3f5f9;color:#566176;font-size:14px}#loginStatus.restricted{background:#fff1df;color:#8a5312;border:1px solid #f1cf9e}#rulePreview{margin-top:12px;padding:14px;border:1px solid #e2e6ed;border-radius:11px;background:#f8f9fc;color:#495469;font:13px/1.65 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap}#rulePreview:empty{display:none}
.status-card{position:sticky;top:20px;overflow:hidden;background:var(--navy);border:0;color:#fff;box-shadow:0 18px 45px #1e263b30}.status-card:before{content:"";position:absolute;right:-24px;top:-36px;width:118px;height:118px;border:20px solid #5b70f1;border-radius:34px;transform:rotate(14deg);opacity:.72}.status-card .card-head,#status{position:relative;z-index:1}.status-card .eyebrow{color:#91a2ff}.status-pill{padding:6px 10px;border-radius:999px;background:#ffffff18;color:#e7ebff;font-size:12px;font-weight:750;border:1px solid #ffffff20}#status{white-space:normal}.status-lead{margin-bottom:14px}.status-lead b{display:block;font-size:18px;margin-bottom:3px}.status-lead>div{color:#b8c1d4;font-size:14px}.timing{margin:14px 0;padding:12px 14px;border-left:3px solid #f6c24f;border-radius:0 10px 10px 0;background:#ffffff0d;color:#e0e5ef;font-size:14px}
.filter-flow{display:flex;flex-direction:column;margin-top:15px}.flow-stage{display:grid;grid-template-columns:34px 1fr auto;align-items:center;gap:11px;min-height:66px;padding:11px 13px;border:1px solid #ffffff16;border-radius:14px;background:#5b70f11d}.flow-stage.detail{background:#ef476417}.flow-stage.qualified{background:#35b68a18}.flow-step{display:grid;place-items:center;width:32px;height:32px;border-radius:10px;background:#ffffff12;color:#aebaff;font-size:11px;font-weight:850}.flow-stage.detail .flow-step{color:#ff9cac}.flow-stage.qualified .flow-step{color:#70dbb8}.flow-copy{min-width:0}.flow-copy strong{display:block;color:#f8f9ff;font-size:14px}.flow-copy small{display:block;margin-top:1px;color:#9faac0;font-size:11px}.flow-value{color:#fff;font-size:27px;font-weight:850;line-height:1}.flow-connector{position:relative;display:grid;grid-template-columns:18px 1fr;gap:9px;min-height:61px;padding:7px 4px}.flow-line{position:relative;display:flex;align-items:flex-end;justify-content:center;color:#8294e8;font-size:17px;line-height:1}.flow-line:before{content:"";position:absolute;top:-1px;bottom:12px;width:1px;background:#6677c580}.flow-line span{position:relative;z-index:1}.flow-filters{display:flex;flex-wrap:wrap;align-content:center;gap:5px}.flow-filter{display:inline-flex;align-items:center;gap:4px;padding:4px 7px;border:1px solid #ffffff10;border-radius:999px;background:#ffffff0a;color:#aeb8ca;font-size:10px;line-height:1.2;white-space:nowrap}.flow-filter b{color:#f5c56a;font-size:11px}.flow-final-label{margin:1px 0 7px;color:#8f9bb3;font-size:10px;font-weight:750;letter-spacing:.08em;text-align:center}.flow-results{display:grid;grid-template-columns:1fr 1fr;gap:9px}.flow-result{display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:61px;padding:10px 12px;border:1px solid #ffffff14;border-radius:13px;background:#35b68a17;color:#b9c4d5;font-size:12px}.flow-result:last-child{background:#f5b94214}.flow-result b{color:#fff;font-size:24px;line-height:1}.metrics-explainer{margin:12px 0 0;padding:10px 12px;border-radius:10px;background:#ffffff0a;color:#aeb8ca;font-size:12px;line-height:1.55}.metrics-explainer b{color:#e5e9f4}details{margin-top:14px;border-top:1px solid #ffffff1c;padding-top:12px}summary{cursor:pointer;color:#ccd4e3;font-size:14px;font-weight:680}pre{max-height:260px;overflow:auto;padding:12px;border-radius:10px;background:#111727;color:#d9e0ea;font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap}
.results-card,.history{margin-top:20px}.results-card{display:none;border-top:5px solid var(--mint)}.results-card[style*="block"]{display:block!important}.history{padding:0;overflow:hidden;border-top:5px solid var(--violet)}.history .card-head{align-items:center;margin:0;padding:21px 24px 16px}.history .eyebrow{color:var(--violet)}.archive-count{display:grid;place-items:center;min-width:76px;padding:10px 13px;border-radius:14px;background:#f1ebff;color:#6848b6;font-size:22px;font-weight:850;line-height:1}.archive-count span{margin-top:5px;font-size:11px;font-weight:700}.empty{margin:0 20px 20px;padding:22px;text-align:center;border:1px dashed #dce1e9;border-radius:12px;color:var(--muted);background:#fafbfc}.file-name{max-width:270px;overflow:hidden;text-overflow:ellipsis;font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;color:#5c6678}.scroll{overflow:auto;border:1px solid #e3e7ed;border-radius:13px}.history .scroll{border:0;border-top:1px solid var(--line);border-radius:0}table{width:100%;border-collapse:collapse;background:white}th,td{padding:12px 16px;border-bottom:1px solid #eaedf2;text-align:left;vertical-align:middle;font-size:14px}th{background:#f7f8fb;color:#5d687b;font-size:12px;font-weight:780;letter-spacing:.02em;white-space:nowrap}tr:last-child td{border-bottom:0}tbody tr:hover{background:#fafbff}.recent-tag{display:inline-block;margin-left:7px;padding:2px 7px;border-radius:999px;background:#edf0ff;color:#5367c8;font-size:11px;font-weight:750}.download{display:inline-flex;align-items:center;justify-content:center;min-height:34px;padding:6px 12px;border-radius:9px;background:var(--navy);color:#fff;text-decoration:none;font-size:13px;font-weight:720;white-space:nowrap}.download:hover{background:#111827}.results-card>.download{margin-top:14px}.history-toggle{width:100%;min-height:48px;border-radius:0;background:#faf9ff;color:#66527f;border-top:1px solid #ece8f5}.history-toggle:hover:not(:disabled){background:#f3effb;box-shadow:none;transform:none}.history-toggle .arrow{display:inline-block;margin-left:8px;transition:transform .2s}.history-toggle[aria-expanded="true"] .arrow{transform:rotate(180deg)}
@media(max-width:900px){main{padding:24px 18px 48px}.workspace{grid-template-columns:1fr}.status-card{position:static}.actions{grid-template-columns:1fr 1fr}.actions .ghost{grid-column:1/-1;grid-row:2}}
@media(max-width:600px){body{font-size:15px}body:after{width:170px;min-width:0;height:120px}.app-header{align-items:flex-start}.local-badge{display:none}.app-header h1{font-size:23px}.brand-mark{width:42px;height:42px}.card{padding:19px;border-radius:16px}.history{padding:0}.history .card-head{padding:18px}.archive-count{min-width:64px;font-size:20px}.grid{grid-template-columns:1fr}.actions,.safety-strip{grid-template-columns:1fr}.actions .ghost,.recovery{grid-column:auto;grid-row:auto}.flow-stage{grid-template-columns:31px 1fr auto;padding:10px}.flow-filters{gap:4px}.flow-filter{font-size:9px}th,td{padding:10px}.file-name{max-width:180px}}
.account-cell{min-width:140px;max-width:260px;overflow-wrap:anywhere;font-weight:650}.account-cell small{display:block;margin-top:4px;color:var(--muted);font-size:12px;font-weight:400}#loginStatus{overflow-wrap:anywhere}
</style></head><body><main>
<header class="app-header"><div class="title-wrap"><div class="brand-mark" aria-hidden="true">采</div><div><h1>Video 采集助手</h1><p>公开内容采集 · 本地转写 · Excel 归档</p></div></div><div class="local-badge">仅在本机运行</div></header>
<section class="workspace"><div class="card form-card"><div class="card-head"><div><span class="eyebrow">New collection</span><h2>新建采集</h2><p class="card-copy">按顺序设置来源、筛选条件和转写参数。</p></div></div><div class="grid">
<div class="section-heading tone-source full"><span>01</span><b>采集来源</b></div>
<label>平台<select id="platform" onchange="platformChanged()"><option value="xhs">小红书</option><option value="dy">抖音</option></select></label>
<label>触发方式<select id="trigger" onchange="toggle()"><option value="creator_url">指定博主主页</option><option value="keyword">关键词发现博主</option></select></label>
<label class="full" id="urlbox">博主主页链接<input id="url" value="" placeholder="粘贴主页链接"></label>
<label class="full" id="keybox" style="display:none">关键词（逗号分隔）<input id="keywords" placeholder="看房,房产"></label>
<label class="full" id="fanbox" style="display:none">最低粉丝数（可选）<input id="fans" type="number" min="0" placeholder="仅用于关键词发现博主；不填则不限制"></label>
<div class="section-heading tone-filter full"><span>02</span><b>筛选条件</b></div>
<label>开始日期<input id="start" type="date"></label><label>结束日期<input id="end" type="date"></label>
<label>最低点赞数<input id="likes" type="number" value="200"></label><label>最多条数<input id="limit" type="number" value="10" min="1" max="50"></label>
<div class="section-heading tone-transcribe full"><span>03</span><b>转写设置</b></div>
<label>转写模式<select id="model"><option value="small">标准（速度较快）</option><option value="medium">准确（速度较慢）</option></select></label>
<label>专业词库（可选）<input id="glossary" placeholder="例如：青山湖,桃李春风,临安"></label>
</div><small class="form-note">系统会按内容 ID 和链接自动去重；评论、图片和代理默认关闭。</small>
<div class="safety-strip"><div class="safety-item"><b>先看列表指标</b>低于点赞门槛不打开详情</div><div class="safety-item"><b>只处理合格内容</b>达到目标条数立即停止</div><div class="safety-item"><b>风控即刻暂停</b>不自动重试或重新登录</div></div>
<div class="actions"><button class="ghost" onclick="preview()">检查规则</button><button id="loginButton" class="secondary" onclick="checkLogin()">1. 确认登录</button><button id="startButton" onclick="startJob()" disabled>2. 开始采集</button><button id="recoveryButton" class="recovery" onclick="recoverLogin()">我已在官方页面恢复，重新检查</button></div>
<div id="loginStatus">登录状态：尚未检查</div><div id="rulePreview"></div></div>
<aside class="card status-card"><div class="card-head"><div><span class="eyebrow">Live status</span><h2>任务状态</h2></div><span id="statusPill" class="status-pill">等待操作</span></div><div id="status"><div class="status-lead"><b>采集状态：尚未开始</b><div>完成登录确认后，即可开始采集。</div></div></div><button id="stopButton" class="stop-task" onclick="stopJob()">停止当前任务</button></aside></section>
<section id="results" class="card results-card" style="display:none"></section>
<section class="card history"><div class="card-head"><div><span class="eyebrow">Export archive</span><h2>历史采集 Excel</h2><p class="card-copy">默认显示最近 3 个批次，全部文件均保存在本机。</p></div><div id="archiveCount" class="archive-count">—<span>历史批次</span></div></div><div id="exports">正在读取历史文件…</div></section></main>
<script>
const el=id=>document.getElementById(id);
let exportItems=[],exportsExpanded=false,selectedPlatform=el('platform').value;
const creatorUrls={xhs:el('url').value,dy:''};
async function api(path,options){let response=await fetch(path,options),data=await response.json();if(!response.ok){let detail=data.detail,message=Array.isArray(detail)?detail.map(x=>x.msg.replace(/^Value error, /,'')).join('；'):detail;throw new Error(message||'请求失败，请重试')}return data}
function toggle(){let k=el('trigger').value==='keyword';el('urlbox').style.display=k?'none':'block';el('keybox').style.display=k?'block':'none';el('fanbox').style.display=el('platform').value==='xhs'&&k?'block':'none'}
function isoDate(d){return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`}
function setDefaultDates(){let end=new Date(),start=new Date(end);start.setDate(start.getDate()-29);if(!el('end').value)el('end').value=isoDate(end);if(!el('start').value)el('start').value=isoDate(start)}
function platformChanged(){creatorUrls[selectedPlatform]=el('url').value;selectedPlatform=el('platform').value;el('url').value=creatorUrls[selectedPlatform]||'';el('url').placeholder=selectedPlatform==='dy'?'粘贴抖音博主主页链接或主页分享文字':'粘贴小红书博主主页链接';el('startButton').disabled=true;toggle();pollLogin()}
function payload(){let r={platform:el('platform').value,trigger_type:el('trigger').value,creator_url:el('url').value,
keywords:el('keywords').value.split(',').map(x=>x.trim()).filter(Boolean),min_likes:Number(el('likes').value||200),max_items:Number(el('limit').value||10),
video_only:true,transcribe_video:true};if(el('start').value)r.start_date=el('start').value;if(el('end').value)r.end_date=el('end').value;
if(el('platform').value==='xhs'&&el('trigger').value==='keyword'&&el('fans').value)r.min_followers=Number(el('fans').value);return {request:r,account_label:'',transcription_model:el('model').value,glossary:el('glossary').value}}
async function preview(){try{let data=await api('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())});el('rulePreview').textContent=JSON.stringify(data,null,2)}catch(error){el('rulePreview').textContent=error.message}}
async function checkLogin(){let button=el('loginButton');button.disabled=true;button.textContent='正在检查…';el('startButton').disabled=true;el('loginStatus').textContent='登录状态：正在检查，请在弹出的平台页面中完成扫码或验证';try{await api('/api/login/'+el('platform').value,{method:'POST'});pollLogin()}catch(error){el('loginStatus').textContent=error.message;button.disabled=false;button.textContent='1. 确认登录'}}
async function pollLogin(){try{let platform=el('platform').value,s=await api('/api/login-status?platform='+platform),matched=s.status==='logged_in',restricted=s.status==='restricted';el('loginStatus').className=restricted?'restricted':'';el('loginStatus').textContent='登录状态：'+s.message;el('startButton').disabled=!matched;el('loginButton').style.display=restricted?'none':'';el('recoveryButton').style.display=restricted?'block':'none';el('loginButton').disabled=s.status==='checking';el('loginButton').textContent=s.status==='checking'?'正在检查…':matched?'重新确认登录':'1. 确认登录';if(s.status==='checking')setTimeout(pollLogin,1200)}catch(error){el('loginStatus').textContent='登录状态暂时无法读取，请重新确认登录';el('startButton').disabled=true;el('loginButton').disabled=false;el('loginButton').textContent='1. 确认登录'}}
async function recoverLogin(){if(!window.confirm('请确认你已经在小红书官方页面正常浏览，并且不再显示“操作频繁”。现在解除本地暂停吗？'))return;try{await api('/api/access-guard/'+el('platform').value+'/clear',{method:'POST'});await checkLogin()}catch(error){el('loginStatus').textContent=error.message}}
async function startJob(){if(!window.confirm('已确认登录，现在开始采集？'))return;
el('status').textContent='采集状态：正在提交任务…';
try{await api('/api/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())});poll()}catch(error){el('status').textContent=error.message}}
async function stopJob(){if(!window.confirm('停止当前任务吗？已完成的历史 Excel 不受影响。'))return;try{await api('/api/stop',{method:'POST'});poll()}catch(error){el('status').textContent=error.message}}
function esc(v){return String(v??'').replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]))}
function duration(n){n=Math.max(0,Math.round(n||0));return n<60?`${n}秒`:`${Math.floor(n/60)}分${n%60}秒`}
function render(s){let p=s.progress||{}, names={idle:'尚未开始',running:'正在采集',stopping:'正在停止',stopped:'已停止',done:'采集完成',error:'采集失败'},pillNames={idle:'等待操作',running:'任务进行中',stopping:'正在停止',stopped:'已停止',done:'已完成',error:'需处理'};
let skippedMetrics=p.metric_missing_skipped?`另有 ${p.metric_missing_skipped} 条因平台未返回可核验指标而安全跳过，未写入结果。`:'';
let message=s.status==='idle'?'请确认登录，然后点击“开始采集”。':s.status==='running'?'程序正在执行；先读取主页卡片，再只对候选作品读取详情进行核验。':s.status==='stopping'?'正在结束当前步骤，请稍候。':s.status==='stopped'?'任务已停止；已存在的历史 Excel 不受影响。':s.status==='done'?(p.exported?`采集完成，共导出 ${p.exported} 条新结果，新增 ${p.history_marked||0} 条持久化标记。${p.media_missing?`其中 ${p.media_missing} 条未取得视频文件，下次仍可重试。`:''}${skippedMetrics}`:(p.history_skipped?`没有发现新内容，已跳过 ${p.history_skipped} 条历史采集内容。${skippedMetrics}`:`采集完成，但没有符合条件的新数据。${skippedMetrics}`)):`采集失败：${s.error||'请展开运行记录查看原因'}`;
let elapsed=s.started_at?Date.now()/1000-s.started_at:0, estimate=p.estimated_total_seconds||90+Number(el('limit').value||10)*75, remaining=Math.max(0,estimate-elapsed);
let timing=['running','stopping'].includes(s.status)?`<div class="timing">当前阶段：${esc(p.stage||'正在处理')}。已用 ${duration(elapsed)}，预计还需约 ${duration(remaining)}。时间为估算值，取决于合格视频长度和网络速度。</div>`:'';
let unfinished=(p.media_missing??0)+(p.transcribe_errors??0);
let triggerType=p.trigger_type||el('trigger').value,followerEnabled=p.follower_filter_enabled??(triggerType==='keyword'&&Boolean(el('fans').value));
let cardLabel=triggerType==='keyword'?'关键词结果卡片':'主页卡片',detailStep=followerEnabled?'03':'02',newStep=followerEnabled?'04':'03';
let authorFlow=followerEnabled?`<div class="flow-stage"><span class="flow-step">02</span><div class="flow-copy"><strong>博主粉丝资格</strong><small>同一博主仅核验一次</small></div><b class="flow-value">${p.creators_checked??0}</b></div><div class="flow-connector"><div class="flow-line"><span>↓</span></div><div class="flow-filters"><span class="flow-filter">粉丝不足博主 <b>-${p.followers_filtered??0}</b></span></div></div>`:'';
let dateDetailFiltered=p.date_detail_filtered??Math.max(0,(p.date_filtered??0)-(p.date_prefiltered??0));
el('statusPill').textContent=pillNames[s.status]||s.status;el('status').innerHTML=`<div class="status-lead"><b>采集状态：${names[s.status]||s.status}</b><div>${message}</div></div>${timing}<div class="filter-flow" aria-label="采集过滤流程">
<div class="flow-stage"><span class="flow-step">01</span><div class="flow-copy"><strong>${cardLabel}</strong><small>本次已读取</small></div><b class="flow-value">${p.found??0}</b></div>
<div class="flow-connector"><div class="flow-line"><span>↓</span></div><div class="flow-filters"><span class="flow-filter">历史已采集 <b>-${p.history_skipped??0}</b></span><span class="flow-filter">非视频 <b>-${p.non_video_filtered??0}</b></span><span class="flow-filter">点赞不足 <b>-${p.likes_filtered??0}</b></span><span class="flow-filter">日期预筛 <b>-${p.date_prefiltered??0}</b></span></div></div>${authorFlow}
<div class="flow-stage detail"><span class="flow-step">${detailStep}</span><div class="flow-copy"><strong>进入详情核验</strong><small>仅读取初筛后候选</small></div><b class="flow-value">${p.details_requested??0}</b></div>
<div class="flow-connector"><div class="flow-line"><span>↓</span></div><div class="flow-filters"><span class="flow-filter">日期复核不符 <b>-${dateDetailFiltered}</b></span><span class="flow-filter">指标缺失 <b>-${p.metric_missing_skipped??0}</b></span><span class="flow-filter">内容重复 <b>-${p.content_duplicates??0}</b></span></div></div>
<div class="flow-stage qualified"><span class="flow-step">${newStep}</span><div class="flow-copy"><strong>本次新内容</strong><small>通过全部筛选</small></div><b class="flow-value">${p.eligible??0}</b></div>
<div class="flow-connector"><div class="flow-line"><span>↓</span></div><div class="flow-filters"><span class="flow-filter">进入本地视频转写</span></div></div><div class="flow-final-label">最终处理结果</div><div class="flow-results"><div class="flow-result"><span>完成转写</span><b>${p.transcribed??0}</b></div><div class="flow-result"><span>未完成</span><b>${unfinished}</b></div></div></div>
<div class="metrics-explainer"><b>阅读方法：</b>数量按箭头方向向下过滤；橙色“-”数字表示在该阶段被排除或跳过的内容。</div>`;el('stopButton').style.display=['running','stopping'].includes(s.status)?'block':'none';el('stopButton').disabled=s.status==='stopping';
let rows=s.records||[];if(rows.length||s.status==='done'){let body=rows.map(r=>`<tr><td>${esc(r['采集标记'])}</td><td>${esc(r['博主账号']||r['账号'])}</td><td>${esc(r['标题'])}</td><td>${esc(r['发布时间'])}</td><td>${esc(r['视频转文字'])}</td><td>${esc(r['点赞数'])}</td><td>${esc(r['收藏数'])}</td><td><a href="${esc(r['原始链接'])}" target="_blank">查看原文</a></td></tr>`).join('');el('results').style.display='block';let button=s.status==='done'?'<a class="download" href="/api/download">下载完整 Excel</a>':'<a class="download" href="/api/download-current">下载当前已处理结果</a>';el('results').innerHTML=`<b>采集结果</b><div>${rows.length?`已处理 ${rows.length} 条；只有成功项会写入历史标记，未完成项下次可重试。`:'本次没有符合条件的新结果，Excel 中只有表头。'}</div>${rows.length?`<div class="scroll"><table><thead><tr><th>采集标记</th><th>博主账号</th><th>标题</th><th>发布时间</th><th>视频转文字或失败原因</th><th>点赞</th><th>收藏</th><th>链接</th></tr></thead><tbody>${body}</tbody></table></div>`:''}${button}`}else{el('results').style.display='none'}
let logs=(s.logs||[]).slice(-20).map(esc).join('\n');if(logs)el('status').insertAdjacentHTML('beforeend',`<details><summary>查看运行记录</summary><pre>${logs}</pre></details>`)}
function renderExports(){el('archiveCount').innerHTML=`${exportItems.length}<span>历史批次</span>`;if(!exportItems.length){el('exports').innerHTML='<div class="empty">暂无历史 Excel，完成首次采集后会显示在这里。</div>';return}
let visible=exportsExpanded?exportItems:exportItems.slice(0,3),body=visible.map((item,index)=>`<tr><td>${esc(item.collected_at_display)}${index===0?'<span class="recent-tag">最近</span>':''}</td><td>${esc(item.platform_name)}</td><td class="account-cell">${esc(item.account_display||'未记录账号')}${!item.accounts?.length&&item.creator_url?`<small>${esc(item.creator_url)}</small>`:''}</td><td>${item.row_count?`${item.row_count} 条`:'0 条（无新内容）'}</td><td class="file-name">${esc(item.filename)}</td><td><a class="download" href="/api/exports/${encodeURIComponent(item.filename)}">下载</a></td></tr>`).join('');
let toggle=exportItems.length>3?`<button class="history-toggle" aria-expanded="${exportsExpanded}" onclick="toggleExports()">${exportsExpanded?'收起历史记录':`查看其余 ${exportItems.length-3} 个批次`}<span class="arrow">⌄</span></button>`:'';el('exports').innerHTML=`<div class="scroll"><table><thead><tr><th>采集时间</th><th>平台</th><th>博主账号</th><th>结果数</th><th>文件</th><th>操作</th></tr></thead><tbody>${body}</tbody></table></div>${toggle}`}
function toggleExports(){exportsExpanded=!exportsExpanded;renderExports()}
async function loadExports(){let x=await fetch('/api/exports');if(!x.ok){el('exports').textContent='历史文件读取失败';return}let data=await x.json();exportItems=data.items||[];renderExports()}
async function poll(){let x=await fetch('/api/status'),s=await x.json();render(s);if(['running','stopping'].includes(s.status))setTimeout(poll,1500);else{if(s.status==='done')loadExports();pollLogin()}}
window.addEventListener('DOMContentLoaded',()=>{setDefaultDates();toggle();pollLogin();poll();loadExports()});
</script></body></html>"""

"""Small, model-independent OpenAPI tool gateway for scoped agent workspaces."""
import hashlib, hmac, os, subprocess, time, json, socket, ssl
import asyncio
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

ROOT = Path(os.getenv("WORKSPACE_ROOT", "/srv/agent-workspaces")).resolve()
ARTIFACTS = Path(os.getenv("ARTIFACT_ROOT", "/srv/agent-artifacts")).resolve()
API_KEY = os.getenv("AGENT_GATEWAY_KEY", "")
if len(API_KEY) < 32:
    raise RuntimeError("AGENT_GATEWAY_KEY must be set to at least 32 characters")
ROOT.mkdir(parents=True, exist_ok=True); ARTIFACTS.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="AI Node Agent Gateway", version="1.0.0", description="Scoped filesystem and shell tools for agent projects.")

MAX_COMMAND_CHARS = 20_000
MAX_WRITE_CHARS = 5_000_000
MAX_AUDIT_BYTES = 10 * 1024 * 1024

def audit(action: str, detail: dict | None = None):
    record = {"ts": time.time(), "action": action, "detail": detail or {}}
    try:
        path = ARTIFACTS / "agent-audit.jsonl"
        if path.exists() and path.stat().st_size >= MAX_AUDIT_BYTES:
            rotated = ARTIFACTS / "agent-audit.jsonl.1"
            rotated.unlink(missing_ok=True)
            path.replace(rotated)
        with path.open("a") as f: f.write(json.dumps(record, separators=(",", ":")) + "\n")
    except OSError: pass

def auth(x_agent_key: Optional[str], authorization: Optional[str]):
    supplied = x_agent_key or (authorization.removeprefix("Bearer ") if authorization else "")
    if not hmac.compare_digest(supplied, API_KEY): raise HTTPException(401, "invalid agent gateway key")

def safe(rel: str) -> Path:
    p = (ROOT / rel).resolve()
    if p != ROOT and ROOT not in p.parents: raise HTTPException(400, "path outside workspace root")
    return p

class PathReq(BaseModel):
    path: str = Field(..., description="Path relative to the agent workspace root")
class WriteReq(PathReq):
    content: str
    append: bool = False
class ShellReq(BaseModel):
    command: str
    project: str = "default"
    timeout_seconds: int = Field(120, ge=1, le=3600)

@app.get("/health", operation_id="agent_health")
def health(): return {"status":"ok", "workspace_root":str(ROOT), "artifact_root":str(ARTIFACTS)}

@app.get("/tools", operation_id="list_agent_tools")
def tools(): return {"tools":["fs_list","fs_read","fs_write","fs_mkdir","fs_delete","fs_hash","shell_exec","http_security_check","tcp_probe","dns_lookup","tls_certificate"]}

SERVICE_CHECKS = {
    "ollama": "http://ollama:11434/api/tags",
    "open-webui": "http://open-webui:8080/health",
    "comfyui": "http://comfyui:8188/system_stats",
    "embeddings": "http://embeddings:8080/health",
    "prometheus": "http://prometheus:9090/-/ready",
    "grafana": "http://grafana:3000/api/health",
    "uptime-kuma": "http://uptime-kuma:3001/",
    "agent-gateway": "http://127.0.0.1:8090/health",
}

def service_snapshot():
    out=[]
    for name,url in SERVICE_CHECKS.items():
        started=time.time()
        try:
            r=urlopen(Request(url,headers={"User-Agent":"ai-node-transparency/1.0"}),timeout=3)
            out.append({"service":name,"url":url,"status":"up","http_status":r.status,"latency_ms":round((time.time()-started)*1000,2)})
        except Exception as e:
            out.append({"service":name,"url":url,"status":"down","error":f"{type(e).__name__}: {e}","latency_ms":round((time.time()-started)*1000,2)})
    return {"timestamp":time.time(),"services":out}

@app.get("/transparency/services", operation_id="transparency_services")
def transparency_services(x_agent_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_agent_key, authorization); return service_snapshot()

@app.get("/transparency/audit", operation_id="transparency_audit")
def transparency_audit(limit: int = Query(100, ge=1, le=1000), x_agent_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_agent_key, authorization); p=ARTIFACTS/"agent-audit.jsonl"
    if not p.exists(): return {"events":[]}
    lines=p.read_text(errors="replace").splitlines()[-limit:]
    return {"events":[json.loads(x) for x in lines if x.strip()]}

@app.get("/transparency/events", operation_id="transparency_events")
async def transparency_events(x_agent_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_agent_key, authorization)
    async def stream():
        last=""
        for _ in range(120):
            snap=json.dumps(service_snapshot(),separators=(",",":"))
            if snap != last: yield f"event: services\\ndata: {snap}\\n\\n"; last=snap
            await asyncio.sleep(2)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.get("/transparency", response_class=HTMLResponse, include_in_schema=False)
def transparency_dashboard():
    return HTMLResponse("""<!doctype html><meta charset=utf-8><title>AI Node Transparency</title><style>body{font:15px system-ui;background:#101418;color:#e6edf3;max-width:1100px;margin:2rem auto;padding:0 1rem}table{width:100%;border-collapse:collapse}td,th{padding:.55rem;border-bottom:1px solid #30363d;text-align:left}.up{color:#3fb950}.down{color:#f85149}pre{white-space:pre-wrap;background:#161b22;padding:1rem;max-height:30rem;overflow:auto}button{padding:.5rem}</style><h1>AI Node Transparency</h1><p>Read-only live service health and agent activity. Token stays in this browser session.</p><input id=token type=password placeholder="Agent gateway token" size=42><button onclick=start()>Connect</button><h2>Services</h2><table><thead><tr><th>Service</th><th>Status</th><th>Latency</th><th>Endpoint</th></tr></thead><tbody id=services></tbody></table><h2>Recent agent events</h2><pre id=audit>Connect to load events.</pre><script>let h={};function start(){h={Authorization:'Bearer '+document.querySelector('#token').value};refresh();setInterval(refresh,5000)}async function refresh(){try{let s=await fetch('/transparency/services',{headers:h}).then(r=>r.json());services.innerHTML=s.services.map(x=>`<tr><td>${x.service}</td><td class=${x.status}>${x.status}</td><td>${x.latency_ms??'-'} ms</td><td>${x.url}</td></tr>`).join('');let a=await fetch('/transparency/audit?limit=100',{headers:h}).then(r=>r.json());audit.textContent=a.events.map(JSON.stringify).join('\\n')}catch(e){audit.textContent=e}}</script>""")

@app.get("/fs/list", operation_id="fs_list")
def fs_list(path: str = "", x_agent_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_agent_key, authorization); p=safe(path)
    if not p.exists(): raise HTTPException(404,"path not found")
    if not p.is_dir(): raise HTTPException(400,"not a directory")
    return {"path":path,"entries":[{"name":x.name,"type":"dir" if x.is_dir() else "file","size":x.stat().st_size if x.is_file() else None} for x in sorted(p.iterdir())]}

@app.get("/fs/read", operation_id="fs_read")
def fs_read(path: str, x_agent_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_agent_key, authorization); p=safe(path)
    if not p.is_file(): raise HTTPException(404,"file not found")
    if p.stat().st_size > 5_000_000: raise HTTPException(413,"file too large")
    try: content=p.read_text()
    except UnicodeDecodeError: raise HTTPException(415,"binary file; use artifact handling")
    return {"path":path,"content":content,"size":p.stat().st_size}

@app.post("/fs/write", operation_id="fs_write")
def fs_write(req: WriteReq, x_agent_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_agent_key, authorization)
    p=safe(req.path)
    existing_size = p.stat().st_size if req.append and p.exists() else 0
    if len(req.content) > MAX_WRITE_CHARS or existing_size + len(req.content.encode()) > MAX_WRITE_CHARS:
        raise HTTPException(413, "resulting file exceeds the 5,000,000-byte limit")
    audit("fs_write", {"path": req.path, "append": req.append}); p.parent.mkdir(parents=True,exist_ok=True)
    mode="a" if req.append else "w"; p.open(mode).write(req.content)
    return {"path":req.path,"bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}

@app.post("/fs/mkdir", operation_id="fs_mkdir")
def fs_mkdir(req: PathReq, x_agent_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_agent_key, authorization); p=safe(req.path); p.mkdir(parents=True,exist_ok=True); return {"path":req.path,"created":True}

@app.delete("/fs/delete", operation_id="fs_delete")
def fs_delete(path: str, x_agent_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_agent_key, authorization); p=safe(path)
    if not p.exists(): raise HTTPException(404,"path not found")
    if p.is_dir(): raise HTTPException(400,"directory deletion requires explicit project cleanup")
    p.unlink(); return {"path":path,"deleted":True}

@app.get("/fs/hash", operation_id="fs_hash")
def fs_hash(path: str, x_agent_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_agent_key, authorization); p=safe(path)
    return {"path":path,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}

@app.post("/shell/exec", operation_id="shell_exec")
def shell_exec(req: ShellReq, x_agent_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_agent_key, authorization)
    if len(req.command) > MAX_COMMAND_CHARS: raise HTTPException(413, "command exceeds 20,000 characters")
    audit("shell_exec", {"project": req.project, "command_length": len(req.command)}); wd=safe(req.project); wd.mkdir(parents=True,exist_ok=True)
    started=time.time()
    try:
        r=subprocess.run(["bash","-lc",req.command],cwd=wd,text=True,capture_output=True,timeout=req.timeout_seconds,env={**os.environ,"AGENT_PROJECT":req.project})
        return {"project":req.project,"command":req.command,"exit_code":r.returncode,"stdout":r.stdout[-20000:],"stderr":r.stderr[-20000:],"duration_seconds":round(time.time()-started,3)}
    except subprocess.TimeoutExpired as e:
        return {"project":req.project,"command":req.command,"exit_code":124,"stdout":(e.stdout or "")[-20000:],"stderr":(e.stderr or "")[-20000:],"timed_out":True,"duration_seconds":round(time.time()-started,3)}

class URLReq(BaseModel):
    url: str
    timeout_seconds: int = Field(10, ge=1, le=30)

def checked_url(url: str):
    u=urlparse(url)
    if u.scheme not in ("http", "https") or not u.netloc: raise HTTPException(400, "only http and https URLs are allowed")
    return u

@app.post("/security/http", operation_id="http_security_check")
def http_security_check(req: URLReq, x_agent_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_agent_key, authorization); u=checked_url(req.url); audit("http_security_check", {"url": req.url})
    try:
        r=urlopen(Request(req.url, method="GET", headers={"User-Agent":"ai-node-security-check/1.0"}), timeout=req.timeout_seconds)
        headers={k.lower():v for k,v in r.headers.items()}; wanted=["strict-transport-security","content-security-policy","x-content-type-options","x-frame-options","referrer-policy","permissions-policy"]
        return {"url":req.url,"status":r.status,"final_url":r.geturl(),"security_headers":{k:headers.get(k) for k in wanted},"missing_headers":[k for k in wanted if k not in headers],"server":headers.get("server"),"content_type":headers.get("content-type")}
    except Exception as e: raise HTTPException(502, f"request failed: {type(e).__name__}: {e}")

class TCPReq(BaseModel):
    host: str
    port: int = Field(..., ge=1, le=65535)
    timeout_seconds: int = Field(3, ge=1, le=10)

@app.post("/security/tcp", operation_id="tcp_probe")
def tcp_probe(req: TCPReq, x_agent_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_agent_key, authorization); audit("tcp_probe", {"host": req.host, "port": req.port})
    try:
        started=time.time(); s=socket.create_connection((req.host,req.port),timeout=req.timeout_seconds); s.close(); return {"host":req.host,"port":req.port,"reachable":True,"latency_ms":round((time.time()-started)*1000,2)}
    except OSError as e: return {"host":req.host,"port":req.port,"reachable":False,"error":str(e)}

@app.get("/security/dns", operation_id="dns_lookup")
def dns_lookup(host: str, x_agent_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_agent_key, authorization); audit("dns_lookup", {"host":host})
    try: return {"host":host,"addresses":sorted({x[4][0] for x in socket.getaddrinfo(host,None)})}
    except OSError as e: raise HTTPException(502, str(e))

@app.get("/security/tls", operation_id="tls_certificate")
def tls_certificate(host: str, port: int = 443, x_agent_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    auth(x_agent_key, authorization); audit("tls_certificate", {"host":host,"port":port})
    try:
        ctx=ssl.create_default_context(); started=time.time()
        with socket.create_connection((host,port),timeout=5) as raw:
            with ctx.wrap_socket(raw,server_hostname=host) as s:
                cert=s.getpeercert(); return {"host":host,"port":port,"protocol":s.version(),"cipher":s.cipher()[0],"subject":cert.get("subject"),"issuer":cert.get("issuer"),"not_before":cert.get("notBefore"),"not_after":cert.get("notAfter"),"latency_ms":round((time.time()-started)*1000,2)}
    except Exception as e: raise HTTPException(502, f"TLS check failed: {type(e).__name__}: {e}")

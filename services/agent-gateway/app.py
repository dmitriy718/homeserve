"""Small, model-independent OpenAPI tool gateway for scoped agent workspaces."""
import hashlib, os, shlex, subprocess, time, uuid, json, socket, ssl
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(os.getenv("WORKSPACE_ROOT", "/srv/agent-workspaces")).resolve()
ARTIFACTS = Path(os.getenv("ARTIFACT_ROOT", "/srv/agent-artifacts")).resolve()
API_KEY = os.getenv("AGENT_GATEWAY_KEY", "")
ROOT.mkdir(parents=True, exist_ok=True); ARTIFACTS.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="AI Node Agent Gateway", version="1.0.0", description="Scoped filesystem and shell tools for agent projects.")

def audit(action: str, detail: dict | None = None):
    record = {"ts": time.time(), "action": action, "detail": detail or {}}
    try:
        with (ARTIFACTS / "agent-audit.jsonl").open("a") as f: f.write(json.dumps(record, separators=(",", ":")) + "\n")
    except OSError: pass

def auth(x_agent_key: Optional[str], authorization: Optional[str]):
    supplied = x_agent_key or (authorization.removeprefix("Bearer ") if authorization else "")
    if API_KEY and supplied != API_KEY: raise HTTPException(401, "invalid agent gateway key")

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
    auth(x_agent_key, authorization); audit("fs_write", {"path": req.path, "append": req.append}); p=safe(req.path); p.parent.mkdir(parents=True,exist_ok=True)
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
    auth(x_agent_key, authorization); audit("shell_exec", {"project": req.project, "command_length": len(req.command)}); wd=safe(req.project); wd.mkdir(parents=True,exist_ok=True)
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

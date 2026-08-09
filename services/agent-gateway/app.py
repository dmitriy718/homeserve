"""Small, model-independent OpenAPI tool gateway for scoped agent workspaces."""
import hashlib, os, shlex, subprocess, time, uuid
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(os.getenv("WORKSPACE_ROOT", "/srv/agent-workspaces")).resolve()
ARTIFACTS = Path(os.getenv("ARTIFACT_ROOT", "/srv/agent-artifacts")).resolve()
API_KEY = os.getenv("AGENT_GATEWAY_KEY", "")
ROOT.mkdir(parents=True, exist_ok=True); ARTIFACTS.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="AI Node Agent Gateway", version="1.0.0", description="Scoped filesystem and shell tools for agent projects.")

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
def tools(): return {"tools":["fs_list","fs_read","fs_write","fs_mkdir","fs_delete","fs_hash","shell_exec"]}

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
    auth(x_agent_key, authorization); p=safe(req.path); p.parent.mkdir(parents=True,exist_ok=True)
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
    auth(x_agent_key, authorization); wd=safe(req.project); wd.mkdir(parents=True,exist_ok=True)
    started=time.time()
    try:
        r=subprocess.run(["bash","-lc",req.command],cwd=wd,text=True,capture_output=True,timeout=req.timeout_seconds,env={**os.environ,"AGENT_PROJECT":req.project})
        return {"project":req.project,"command":req.command,"exit_code":r.returncode,"stdout":r.stdout[-20000:],"stderr":r.stderr[-20000:],"duration_seconds":round(time.time()-started,3)}
    except subprocess.TimeoutExpired as e:
        return {"project":req.project,"command":req.command,"exit_code":124,"stdout":(e.stdout or "")[-20000:],"stderr":(e.stderr or "")[-20000:],"timed_out":True,"duration_seconds":round(time.time()-started,3)}

from __future__ import annotations
import hashlib, json, os, threading, time
from datetime import datetime, timezone
from pathlib import Path


def attach_raw_audit(provider, path: str | Path):
    """Record actual model request/response content without credentials."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    original = provider.complete
    lock = threading.Lock()
    def log(event):
        line=json.dumps(event,ensure_ascii=False,separators=(",",":"))+"\n"
        with lock:
            fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
            try: os.write(fd,line.encode("utf-8"))
            finally: os.close(fd)
    def complete(system,payload,max_tokens,temperature,seed):
        started=time.time()
        request={"system":system,"payload":payload,"max_output_tokens":max_tokens,"temperature":temperature,"seed":seed}
        event={"time_utc":datetime.now(timezone.utc).isoformat(),"started_epoch":started,"role":payload.get("role",""),"model":provider.model,"system_sha256":hashlib.sha256(system.encode()).hexdigest(),"payload_sha256":hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),"request":request}
        try:
            reply=original(system,payload,max_tokens,temperature,seed)
        except Exception as exc:
            event.update({"status":"failed","error_type":type(exc).__name__,"error":str(exc),"duration_seconds":time.time()-started})
            observed=getattr(exc,"observed_reply",None)
            if observed is not None: event["observed_usage"]={"input_tokens":observed.input_tokens,"output_tokens":observed.output_tokens,"attempts":observed.attempts}
            log(event)
            raise
        event.update({"status":"completed","response":reply.content,"input_tokens":reply.input_tokens,"output_tokens":reply.output_tokens,"http_attempts":reply.attempts,"estimated_usage":reply.estimated,"duration_seconds":time.time()-started})
        log(event)
        return reply
    provider.complete=complete
    return provider

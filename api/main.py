import os
import sys
import uuid
import threading
import time
from io import BytesIO
from typing import Dict, Any, Optional
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

import requests
import boto3
from botocore.exceptions import ClientError

# Load .env FIRST
from dotenv import load_dotenv
load_dotenv()

# Make repo root importable
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from wave import nano_banana_edit, wans2v, generate_qr_code
from quiz import get_random_questions, grade_answers

app = FastAPI(title="UAE National Day Video API", version="1.0.0")

# Config
AWS_REGION = os.getenv("AWS_REGION", "me-central-1")
S3_BUCKET = os.getenv("AWS_S3_BUCKET", "")
S3_PREFIX = os.getenv("AWS_S3_PREFIX", "uae-national-day").strip("/")
S3_PUBLIC_DOMAIN = os.getenv("AWS_S3_PUBLIC_DOMAIN", "").rstrip("/")

# NEW: Load credentials from .env
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

if not S3_BUCKET:
    raise RuntimeError("AWS_S3_BUCKET is required")

# UPDATED: AWS client with explicit credentials
s3 = boto3.client(
    "s3",
    region_name=AWS_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
)

# Debug: verify credentials
try:
    sts = boto3.client(
        "sts",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )
    identity = sts.get_caller_identity()
    print(f"✅ boto3 authenticated as: {identity['Arn']}")
except Exception as e:
    print(f"❌ boto3 credential error: {e}")

def _s3_key(*parts: str) -> str:
    safe = [p.strip("/").replace("..", "") for p in parts if p]
    return "/".join([S3_PREFIX] + safe) if S3_PREFIX else "/".join(safe)

def _s3_put_file(local_path: str, key: str, content_type: str) -> None:
    s3.upload_file(
        Filename=local_path,
        Bucket=S3_BUCKET,
        Key=key,
        ExtraArgs={"ContentType": content_type},
    )

def _s3_put_bytes(data: bytes, key: str, content_type: str) -> None:
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=data, ContentType=content_type)

def _s3_url_for_key(key: str, expires: int = 86400) -> str:
    if S3_PUBLIC_DOMAIN:
        return f"{S3_PUBLIC_DOMAIN}/{key}"
    return s3.generate_presigned_url(
        "get_object", Params={"Bucket": S3_BUCKET, "Key": key}, ExpiresIn=expires
    )

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Temp upload dir
UPLOAD_DIR = os.path.join(ROOT_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# In-memory jobs
JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()

def _run_pipeline(job_id: str, img_path: str, age_group: str, phone: Optional[str]):
    try:
        with JOBS_LOCK:
            JOBS[job_id] = {
                "status": "image",
                "video_url": None,
                "image_url": None,
                "error": None,
                "phone": phone,
                "started_at": time.time(),
            }

        # Upload original (optional audit)
        ext = Path(img_path).suffix.lower() or ".jpg"
        upload_key = _s3_key("uploads", f"{job_id}{ext}")
        _s3_put_file(img_path, upload_key, "image/jpeg" if ext in [".jpg", ".jpeg"] else "image/png")

        # Image edit
        edited_img_url = nano_banana_edit(img1=img_path, age_gap=age_group)
        if not edited_img_url:
            raise RuntimeError("Image generation failed")

        with JOBS_LOCK:
            JOBS[job_id]["status"] = "video"

        # Video generation
        video_url_remote = wans2v(img=edited_img_url, age_gap=age_group)
        if not video_url_remote:
            raise RuntimeError("Video generation failed")

        # Upload edited image to S3
        img_resp = requests.get(edited_img_url, timeout=60)
        img_resp.raise_for_status()
        img_bytes = img_resp.content
        image_key = _s3_key("images", f"{job_id}.jpeg")
        _s3_put_bytes(img_bytes, image_key, img_resp.headers.get("Content-Type", "image/jpeg"))

        # Upload final video to S3
        vid_resp = requests.get(video_url_remote, timeout=300)
        vid_resp.raise_for_status()
        vid_bytes = vid_resp.content
        video_key = _s3_key("videos", f"{job_id}.mp4")
        _s3_put_bytes(vid_bytes, video_key, "video/mp4")

        # URLs
        s3_image_url = _s3_url_for_key(image_key)
        s3_video_url = _s3_url_for_key(video_key)

        with JOBS_LOCK:
            JOBS[job_id]["status"] = "completed"
            JOBS[job_id]["image_url"] = s3_image_url
            JOBS[job_id]["video_url"] = s3_video_url
            JOBS[job_id]["completed_at"] = time.time()

    except Exception as e:
        with JOBS_LOCK:
            JOBS[job_id] = {
                "status": "failed",
                "video_url": None,
                "image_url": None,
                "error": f"{type(e).__name__}: {e}",
                "phone": phone,
                "failed_at": time.time(),
            }
    finally:
        # Clean temp
        try:
            if os.path.exists(img_path):
                os.remove(img_path)
        except Exception:
            pass

@app.post("/api/jobs")
async def create_job(
    image: UploadFile = File(..., description="JPEG/PNG, max size enforced"),
    age_group: str = Form(...),
    phone: Optional[str] = Form(None),
):
    if age_group not in {"Male", "Female", "Boy", "Girl"}:
        raise HTTPException(400, detail="Invalid age_group")
    if image.content_type not in {"image/jpeg", "image/png"}:
        raise HTTPException(400, detail="Only JPEG/PNG images are accepted")

    job_id = str(uuid.uuid4())
    ext = Path(image.filename).suffix or ".jpg"
    upload_path = os.path.join(UPLOAD_DIR, f"{job_id}{ext}")

    # Stream to disk with size cap
    read = 0
    chunk_size = 1024 * 1024
    try:
        with open(upload_path, "wb") as f:
            while True:
                chunk = await image.read(chunk_size)
                if not chunk:
                    break
                read += len(chunk)
                if read > MAX_UPLOAD_SIZE:
                    raise HTTPException(413, detail=f"File too large (max {MAX_UPLOAD_SIZE_MB}MB)")
                f.write(chunk)
    finally:
        await image.close()

    # Start background processing
    t = threading.Thread(target=_run_pipeline, args=(job_id, upload_path, age_group, phone), daemon=True)
    t.start()

    return {"job_id": job_id, "status": "queued"}

@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)

    if not job:
        return JSONResponse({"status": "queued"})

    resp = {"status": job["status"], "error": job.get("error")}
    if job["status"] == "completed":
        resp["video_url"] = job.get("video_url")
        resp["image_url"] = job.get("image_url")
        resp["qr_url"] = f"/api/jobs/{job_id}/qr"
    elif job["status"] == "image":
        resp["progress"] = "Editing image..."
    elif job["status"] == "video":
        resp["progress"] = "Generating video..."

    return resp

@app.get("/api/jobs/{job_id}/qr")
async def job_qr(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)

    if not job or job.get("status") != "completed" or not job.get("video_url"):
        raise HTTPException(404, detail="QR not available")

    # QR encodes the S3/CDN URL
    qr_img = generate_qr_code(job["video_url"])
    buf = BytesIO()
    qr_img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})

@app.get("/api/questions")
async def get_questions(count: int = 10, seed: Optional[str] = None):
    try:
        qs = get_random_questions(count=count, seed=seed)
        sanitized = [{"id": q["id"], "question": q["question"], "options": q["options"]} for q in qs]
        return {"questions": sanitized, "key": qs}
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@app.post("/api/jobs/{job_id}/answers")
async def submit_answers(job_id: str, payload: Dict[str, Any]):
    key = payload.get("key")
    answers = payload.get("answers")
    if not isinstance(key, list) or not isinstance(answers, list):
        raise HTTPException(400, detail="Invalid payload")
    return grade_answers(key, answers)

@app.get("/healthz")
async def healthz():
    try:
        s3.head_bucket(Bucket=S3_BUCKET)
        s3_status = "connected"
    except Exception as e:
        s3_status = f"error: {e}"
    return {
        "ok": True,
        "s3_bucket": S3_BUCKET,
        "s3_region": AWS_REGION,
        "s3_status": s3_status,
        "jobs_active": len([j for j in JOBS.values() if j["status"] in {"image", "video"}]),
        "prefix": S3_PREFIX,
        "cdn": S3_PUBLIC_DOMAIN or "presigned",
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

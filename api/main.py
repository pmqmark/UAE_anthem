import os
import sys
import uuid
import threading
import time
from io import BytesIO
from typing import Dict, Any, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# Make repo root importable
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from wave import qwen_edit, wans2v, save_photo, save_video, generate_qr_code  # noqa: E402
from quiz import get_random_questions, grade_answers  # noqa: E402

app = FastAPI(title="UAE National Day Video API", version="0.1.0")

# Read PUBLIC_BASE_URL from environment (e.g., https://api.example.com)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

# CORS (adjust origins as needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure result folders exist
os.makedirs(os.path.join(ROOT_DIR, "result", "videos"), exist_ok=True)
os.makedirs(os.path.join(ROOT_DIR, "result", "images"), exist_ok=True)
os.makedirs(os.path.join(ROOT_DIR, "result", "qr"), exist_ok=True)
os.makedirs(os.path.join(ROOT_DIR, "uploads"), exist_ok=True)

# Serve local media
MEDIA_ROOT = os.path.join(ROOT_DIR, "result")
app.mount("/media", StaticFiles(directory=MEDIA_ROOT), name="media")

# In-memory job registry (simple/private)
JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()


def _run_pipeline(job_id: str, img_path: str, age_group: str, phone: Optional[str]):
    try:
        with JOBS_LOCK:
            JOBS[job_id] = {
                "status": "image",
                "video_path": None,
                "error": None,
                "phone": phone,
            }

        edited_img = qwen_edit(img1=img_path, age_gap=age_group)
        if not edited_img:
            raise RuntimeError("Image generation failed")

        with JOBS_LOCK:
            JOBS[job_id]["status"] = "video"

        video_url = wans2v(img=edited_img, age_gap=age_group)
        if not video_url:
            raise RuntimeError("Video generation failed")

        # Persist locally under result/
        save_photo(url=edited_img, id=job_id)
        saved_path = save_video(url=video_url, id=job_id)
        if not saved_path:
            raise RuntimeError("Saving video failed")

        with JOBS_LOCK:
            JOBS[job_id]["status"] = "completed"
            JOBS[job_id]["video_path"] = saved_path
    except Exception as e:
        with JOBS_LOCK:
            JOBS[job_id] = {
                "status": "failed",
                "video_path": None,
                "error": str(e),
                "phone": phone,
            }


@app.post("/api/jobs")
async def create_job(
    image: UploadFile = File(...),
    age_group: str = Form(...),
    phone: Optional[str] = Form(None),
):
    if age_group not in {"Male", "Female", "Boy", "Girl"}:
        raise HTTPException(400, detail="Invalid age_group")

    # Save upload to local temp path
    if image.content_type not in {"image/jpeg", "image/png"}:
        raise HTTPException(400, detail="Only JPEG/PNG images are accepted")

    job_id = str(uuid.uuid4())
    upload_path = os.path.join(ROOT_DIR, "uploads", f"{job_id}_{image.filename}")
    with open(upload_path, "wb") as f:
        f.write(await image.read())

    # Start background thread
    t = threading.Thread(target=_run_pipeline, args=(job_id, upload_path, age_group, phone), daemon=True)
    t.start()

    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return JSONResponse({"status": "queued"})

    resp = {"status": job["status"], "error": job.get("error")}
    if job.get("status") == "completed" and job.get("video_path"):
        # Build absolute or relative URL based on PUBLIC_BASE_URL
        filename = os.path.basename(job["video_path"])  # e.g., {job_id}.mp4
        rel_url = f"/media/videos/{filename}"
        video_url = f"{PUBLIC_BASE_URL}{rel_url}" if PUBLIC_BASE_URL else rel_url
        
        resp["video_url"] = video_url
        resp["qr_url"] = f"/api/jobs/{job_id}/qr"
    return resp


@app.get("/api/jobs/{job_id}/qr")
async def job_qr(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job or job.get("status") != "completed" or not job.get("video_path"):
        raise HTTPException(404, detail="QR not available")

    # Build absolute video URL for QR code
    filename = os.path.basename(job["video_path"])  # {job_id}.mp4
    rel_url = f"/media/videos/{filename}"
    video_url = f"{PUBLIC_BASE_URL}{rel_url}" if PUBLIC_BASE_URL else rel_url

    # Generate QR image encoding the public URL
    qr_img = generate_qr_code(video_url)
    buf = BytesIO()
    qr_img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")


@app.get("/api/questions")
async def get_questions(count: int = 10, seed: Optional[str] = None):
    try:
        qs = get_random_questions(count=count, seed=seed)
        # Hide answers client-side; return a key so we can grade server-side
        sanitized = [
            {"id": q["id"], "question": q["question"], "options": q["options"]}
            for q in qs
        ]
        return {"questions": sanitized, "key": qs}
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@app.post("/api/jobs/{job_id}/answers")
async def submit_answers(job_id: str, payload: Dict[str, Any]):
    # payload: {"key": [questions with answers], "answers": [indices]}
    key = payload.get("key")
    answers = payload.get("answers")
    if not isinstance(key, list) or not isinstance(answers, list):
        raise HTTPException(400, detail="Invalid payload")

    result = grade_answers(key, answers)

    # Minimal local record for privacy
    os.makedirs(os.path.join(ROOT_DIR, "result", "quiz"), exist_ok=True)
    record_path = os.path.join(ROOT_DIR, "result", "quiz", f"{job_id}.json")
    with open(record_path, "w", encoding="utf-8") as f:
        f.write(
            (
                "{\n"
                f"  \"score\": {result['score']},\n"
                f"  \"correct\": {result['correct']},\n"
                f"  \"total\": {result['total']}\n"
                "}\n"
            )
        )

    return result


@app.get("/healthz")
async def healthz():
    return {"ok": True, "time": int(time.time())}

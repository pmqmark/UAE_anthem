import gradio as gr
import os
import threading
import time
import json
from typing import List, Dict, Any

from wave import qwen_edit, save_video, wans2v, save_photo, generate_qr_code
from quiz import get_random_questions, grade_answers



def flash_message():
    return gr.Info("🟢 Starting generation... Please wait!", duration=3)

# ---------------- Simple in-process job management ----------------
JOB_STATUS: Dict[str, Dict[str, Any]] = {}
_JOB_LOCK = threading.Lock()


def _run_pipeline(img: str, age_gap: str, phone: str):
    try:
        with _JOB_LOCK:
            JOB_STATUS[phone] = {"status": "image", "video_path": None, "error": None}

        edited_img = qwen_edit(img1=img, age_gap=age_gap)
        if not edited_img:
            raise RuntimeError("Image generation failed")

        with _JOB_LOCK:
            JOB_STATUS[phone]["status"] = "video"

        video_url = wans2v(img=edited_img, age_gap=age_gap)
        if not video_url:
            raise RuntimeError("Video generation failed")

        # Save locally
        save_photo(url=edited_img, id=phone)
        saved_path = save_video(url=video_url, id=phone)
        if not saved_path:
            raise RuntimeError("Saving video failed")

        with _JOB_LOCK:
            JOB_STATUS[phone]["status"] = "completed"
            JOB_STATUS[phone]["video_path"] = saved_path
    except Exception as e:
        with _JOB_LOCK:
            JOB_STATUS[phone] = {"status": "failed", "video_path": None, "error": str(e)}


def start_job(img: str, age_gap: str, phone: str):
    if not all([img, age_gap, phone]):
        raise gr.Error("All fields are required")

    # Start background processing
    t = threading.Thread(target=_run_pipeline, args=(img, age_gap, phone), daemon=True)
    t.start()

    # Prepare 10 random questions (from pool of 50)
    questions = get_random_questions(count=10, seed=phone)

    # Return state and UI updates: show quiz, populate radios
    radio_updates = []
    for q in questions:
        radio_updates.append(gr.update(choices=q["options"], value=None, label=q["question"]))

    # Visible quiz group
    quiz_visible = gr.update(visible=True)
    info_text = f"Job started for {phone}. Please answer the quiz while we generate your video."
    return phone, questions, quiz_visible, info_text, *radio_updates


def check_status(phone: str):
    if not phone:
        return None, None, gr.update(value="")

    with _JOB_LOCK:
        job = JOB_STATUS.get(phone)

    if not job:
        return None, None, gr.update(value="")

    status = job.get("status")
    if status == "completed" and job.get("video_path") and os.path.exists(job["video_path"]):
        vp = job["video_path"]
        qr = generate_qr_code(vp)
        return vp, qr, gr.update(value="✅ Video ready!")
    elif status == "failed":
        return None, None, gr.update(value=f"❌ {job.get('error')}")
    else:
        # In progress
        msg = "🎨 Editing image..." if status == "image" else "🎬 Creating video..."
        return None, None, gr.update(value=msg)


def submit_answers(phone: str, questions: List[Dict[str, Any]], answers: List[Any]):
    if not phone:
        raise gr.Error("Phone number missing")
    if not questions:
        raise gr.Error("Questions not loaded")

    # Normalize answers to indices
    chosen = []
    for i, q in enumerate(questions):
        sel = answers[i]
        if sel is None:
            chosen.append(None)
        else:
            # Convert selected option string to index
            try:
                idx = q["options"].index(sel)
            except ValueError:
                idx = None
            chosen.append(idx)

    result = grade_answers(questions, chosen)

    # Persist minimal result to local file for privacy-respecting recordkeeping
    os.makedirs("result/quiz", exist_ok=True)
    rec = {
        "phone": phone,
        "timestamp": int(time.time()),
        "score": result["score"],
        "correct": result["correct"],
        "total": result["total"],
    }
    with open(os.path.join("result/quiz", f"{phone}.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)

    summary = f"You scored {result['correct']} / {result['total']} (Score: {result['score']})."
    return gr.update(value=summary)


with gr.Blocks() as app:
    gr.Markdown("# Generate your video")

    phone_state = gr.State()
    questions_state = gr.State()

    with gr.Row():
        with gr.Column():
            agegroup = gr.Dropdown(
                choices=["Male", "Female", "Boy", "Girl"],
                label="Category",
                value="Boy"
            )
            input_img = gr.Image(label="Upload Photo", type="filepath")
            phone = gr.Textbox(
                label="Phone number",
                placeholder="Enter your Phone number here..."
            )
            generate_btn = gr.Button("Start & Show Quiz", variant="primary")
            status_text = gr.Markdown("⏱️ Processing starts after you click. Quiz appears below.")

            quiz_group = gr.Column(visible=False)
            with quiz_group:
                gr.Markdown("### UAE National Day Quiz (10 questions)")
                # Pre-create 10 radios to populate dynamically
                radios: List[gr.Radio] = []
                for i in range(10):
                    radios.append(gr.Radio(choices=[], label=f"Question {i+1}", interactive=True))
                submit_btn = gr.Button("Submit Answers")
                result_md = gr.Markdown("", label="Result")

        with gr.Column():
            output_video = gr.Video(label="Result")
            qr_code_output = gr.Image(label="📱 Scan to Download Video", type="pil")
            progress_md = gr.Markdown("")

    # Start job: returns phone_state, questions_state, show quiz, info, radios
    generate_btn.click(
        fn=start_job,
        inputs=[input_img, agegroup, phone],
        outputs=[phone_state, questions_state, quiz_group, status_text, *radios],
    )

    # Periodically check job status and update video/QR
    timer = gr.Timer(2.0)
    timer.tick(
        fn=check_status,
        inputs=[phone_state],
        outputs=[output_video, qr_code_output, progress_md],
    )

    # Submit quiz answers
    submit_btn.click(
        fn=lambda ph, qs, *ans: submit_answers(ph, qs, list(ans)),
        inputs=[phone_state, questions_state, *radios],
        outputs=[result_md],
    )



if __name__ == "__main__":
    cwd = os.path.dirname(os.path.abspath(__file__))
    app.launch(
        server_name="0.0.0.0",
        debug=True,
        show_error=True,
        allowed_paths=[cwd],
        server_port=7860,
        share=True
    )
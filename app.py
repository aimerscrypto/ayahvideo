from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
import uuid
import os
from generate_video import generate_verse_video, generate_range_video

app = FastAPI(title="Quran Video Generator")

jobs = {}

class GenerateRequest(BaseModel):
    surah: int
    verse: int

class GenerateRangeRequest(BaseModel):
    surah: int
    start_verse: int
    end_verse: int

def background_generate(job_id: str, surah: int, verse: int):
    try:
        output_file = generate_verse_video(surah, verse)
        if output_file and os.path.exists(output_file):
            jobs[job_id] = {"status": "done", "file": output_file}
        else:
            jobs[job_id] = {"status": "error", "message": "Output file not found."}
    except Exception as e:
        jobs[job_id] = {"status": "error", "message": str(e)}

def background_generate_range(job_id: str, surah: int, start_verse: int, end_verse: int):
    total = end_verse - start_verse + 1

    def progress_callback(verse_num, total_verses, verse):
        jobs[job_id] = {
            "status": "rendering",
            "message": f"Rendering verse {verse_num} of {total_verses} ({surah}:{verse})",
            "verse_num": verse_num,
            "total_verses": total_verses,
        }

    try:
        jobs[job_id] = {
            "status": "rendering",
            "message": f"Starting render of {total} verses...",
            "verse_num": 0,
            "total_verses": total,
        }
        output_file = generate_range_video(surah, start_verse, end_verse, progress_callback)
        if output_file and os.path.exists(output_file):
            jobs[job_id] = {"status": "done", "file": output_file}
        else:
            jobs[job_id] = {"status": "error", "message": "Output file not found."}
    except Exception as e:
        jobs[job_id] = {"status": "error", "message": str(e)}

@app.get("/", response_class=HTMLResponse)
async def read_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/generate")
async def generate_endpoint(req: GenerateRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending"}
    background_tasks.add_task(background_generate, job_id, req.surah, req.verse)
    return {"job_id": job_id}

@app.post("/generate-range")
async def generate_range_endpoint(req: GenerateRangeRequest, background_tasks: BackgroundTasks):
    if req.start_verse > req.end_verse:
        raise HTTPException(status_code=400, detail="start_verse must be <= end_verse")
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending"}
    background_tasks.add_task(background_generate_range, job_id, req.surah, req.start_verse, req.end_verse)
    return {"job_id": job_id}

@app.get("/status/{job_id}")
async def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]

@app.get("/download/{job_id}")
async def download_video(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    if job["status"] != "done":
        raise HTTPException(status_code=400, detail="Video not ready yet")
    file_path = job["file"]
    return FileResponse(file_path, media_type="video/mp4", filename=os.path.basename(file_path))

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
import uuid
import os
from datetime import datetime
import json
import requests
from generate_video import generate_verse_video, generate_range_video, generate_verse_video_to_dir

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Quran Video Generator")

jobs = {}

# Global tracker for bulk batch jobs.
# Structure: { batch_id: { "status", "total", "completed", "failed", "batch_dir", "chunks", "videos" } }
bulk_batches = {}

class DiscoverRequest(BaseModel):
    query: str

class GenerateRequest(BaseModel):
    surah: int
    verse: int
    orientation: str = 'horizontal'

class GenerateRangeRequest(BaseModel):
    surah: int
    start_verse: int
    end_verse: int
    orientation: str = 'horizontal'

class GenerateBulkRequest(BaseModel):
    surah: int
    start_verse: int
    end_verse: int
    verses_per_video: int
    orientation: str = 'horizontal'

def background_generate(job_id: str, surah: int, verse: int, orientation: str = 'horizontal'):
    def step_cb(step_str, pct):
        if job_id in jobs:
            jobs[job_id]["step"] = step_str
            jobs[job_id]["percentage"] = pct

    try:
        jobs[job_id] = {
            "status": "rendering", 
            "step": "Gathering verse text and audio...", 
            "percentage": 0
        }
        output_file = generate_verse_video(surah, verse, orientation=orientation, step_callback=step_cb)
        if output_file and os.path.exists(output_file):
            jobs[job_id] = {"status": "done", "file": output_file, "step": "Ready to download!", "percentage": 100}
        else:
            jobs[job_id] = {"status": "error", "message": "Output file not found."}
    except Exception as e:
        jobs[job_id] = {"status": "error", "message": str(e)}

def background_generate_range(job_id: str, surah: int, start_verse: int, end_verse: int, orientation: str = 'horizontal'):
    total = end_verse - start_verse + 1

    def progress_callback(verse_num, total_verses, verse, step_str="Rendering...", pct=0):
        jobs[job_id] = {
            "status": "rendering",
            "message": f"Rendering verse {verse_num} of {total_verses} ({surah}:{verse})",
            "verse_num": verse_num,
            "total_verses": total_verses,
            "step": f"Verse {verse_num}/{total_verses}: {step_str}",
            "percentage": pct
        }

    try:
        jobs[job_id] = {
            "status": "rendering",
            "message": f"Starting render of {total} verses...",
            "verse_num": 0,
            "total_verses": total,
            "step": "Initializing...",
            "percentage": 0
        }
        output_file = generate_range_video(surah, start_verse, end_verse, progress_callback, orientation=orientation)
        if output_file and os.path.exists(output_file):
            jobs[job_id] = {"status": "done", "file": output_file, "step": "Ready to download!", "percentage": 100}
        else:
            jobs[job_id] = {"status": "error", "message": "Output file not found."}
    except Exception as e:
        jobs[job_id] = {"status": "error", "message": str(e)}


def background_generate_bulk(batch_id: str, surah: int, start_verse: int, end_verse: int,
                              verses_per_video: int, orientation: str = 'horizontal'):
    """Background task that splits a verse range into chunks and renders each as a separate MP4."""

    # ── 1. Build the list of (chunk_start, chunk_end) pairs ──────────────────
    chunks = []
    v = start_verse
    while v <= end_verse:
        chunk_end = min(v + verses_per_video - 1, end_verse)
        chunks.append((v, chunk_end))
        v = chunk_end + 1

    # ── 2. Create a unique batch output folder ────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_dir = os.path.join(BASE_DIR, "output", f"bulk_batch_{timestamp}")
    os.makedirs(batch_dir, exist_ok=True)

    # ── 3. Initialise the batch status entry ──────────────────────────────────
    bulk_batches[batch_id] = {
        "status": "rendering",
        "total": len(chunks),
        "completed": 0,
        "failed": 0,
        "current_chunk": None,
        "batch_dir": batch_dir,
        "chunks": [{"start": s, "end": e, "status": "pending"} for s, e in chunks],
        "videos": [],
    }

    # ── 4. Process each chunk sequentially ───────────────────────────────────
    for idx, (chunk_start, chunk_end) in enumerate(chunks):
        bulk_batches[batch_id]["current_chunk"] = {"index": idx + 1, "start": chunk_start, "end": chunk_end}
        bulk_batches[batch_id]["chunks"][idx]["status"] = "rendering"

        def chunk_step_cb(step_str, pct, _idx=idx):
            bulk_batches[batch_id]["chunks"][_idx]["step"] = step_str
            bulk_batches[batch_id]["chunks"][_idx]["percentage"] = pct

        try:
            if chunk_start == chunk_end:
                # Single-verse chunk — render directly into batch_dir
                output_path = generate_verse_video_to_dir(
                    surah, chunk_start, batch_dir,
                    orientation=orientation, step_callback=chunk_step_cb
                )
            else:
                # Multi-verse chunk — generate each verse then merge them
                from generate_video import generate_range_video, fetch_surah_name
                import shutil, subprocess

                # Render individual verse videos into a temporary sub-folder
                chunk_temp_dir = os.path.join(batch_dir, f"_chunk_temp_{chunk_start}_{chunk_end}")
                os.makedirs(chunk_temp_dir, exist_ok=True)

                verse_files = []
                total_in_chunk = chunk_end - chunk_start + 1
                for vi, verse in enumerate(range(chunk_start, chunk_end + 1)):
                    def verse_step_cb(step_str, pct, _vi=vi, _idx=idx):
                        overall = int((_vi + pct / 100.0) / total_in_chunk * 100)
                        chunk_step_cb(f"Verse {_vi + 1}/{total_in_chunk}: {step_str}", overall)

                    vpath = generate_verse_video_to_dir(
                        surah, verse, chunk_temp_dir,
                        orientation=orientation, step_callback=verse_step_cb
                    )
                    verse_files.append(vpath)

                # FFmpeg-concat the individual verse videos
                surah_name = fetch_surah_name(surah)
                surah_name_clean = surah_name.replace(' ', '-')
                output_filename = f"{surah_name_clean}_{chunk_start}_{chunk_end}.mp4"
                output_path = os.path.join(batch_dir, output_filename)

                concat_path = os.path.join(chunk_temp_dir, "chunk_concat.txt")
                with open(concat_path, "w", encoding="utf-8") as f:
                    for vf in verse_files:
                        abs_path = os.path.abspath(vf).replace("\\", "/")
                        f.write(f"file '{abs_path}'\n")

                cmd = [
                    "ffmpeg", "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", concat_path,
                    "-c", "copy",
                    os.path.abspath(output_path)
                ]
                subprocess.check_call(cmd)
                shutil.rmtree(chunk_temp_dir, ignore_errors=True)

            bulk_batches[batch_id]["chunks"][idx]["status"] = "done"
            bulk_batches[batch_id]["chunks"][idx]["file"] = output_path
            bulk_batches[batch_id]["videos"].append(output_path)
            bulk_batches[batch_id]["completed"] += 1

        except Exception as e:
            print(f"[bulk] ERROR on chunk {chunk_start}-{chunk_end}: {e}")
            bulk_batches[batch_id]["chunks"][idx]["status"] = "error"
            bulk_batches[batch_id]["chunks"][idx]["error"] = str(e)
            bulk_batches[batch_id]["failed"] += 1

    # ── 5. Mark batch as finished ─────────────────────────────────────────────
    final_status = "done" if bulk_batches[batch_id]["failed"] == 0 else "done_with_errors"
    bulk_batches[batch_id]["status"] = final_status
    bulk_batches[batch_id]["current_chunk"] = None
    print(f"[bulk] Batch {batch_id} finished. Status: {final_status} "
          f"({bulk_batches[batch_id]['completed']}/{len(chunks)} completed)")

@app.get("/", response_class=HTMLResponse)
async def read_index():
    with open(os.path.join(BASE_DIR, "index.html"), "r", encoding="utf-8") as f:
        return f.read()

@app.get("/hero.mp4")
async def get_hero_video():
    return FileResponse(os.path.join(BASE_DIR, "hero.mp4"), media_type="video/mp4")

@app.get("/logo.png")
async def get_logo_image():
    return FileResponse(os.path.join(BASE_DIR, "logo.png"), media_type="image/png")

def query_llm(prompt: str) -> str:
    configs = []
    fw_key = os.environ.get("FIREWORKS_API_KEY")
    if fw_key:
        configs.append({
            "label": "Fireworks",
            "url": "https://api.fireworks.ai/inference/v1/chat/completions",
            "key": fw_key,
            "model": "accounts/fireworks/models/minimax-m3",
            "timeout": 30
        })
    or_key = os.environ.get("OPENROUTER_API_KEY")
    if or_key:
        configs.append({
            "label": "OpenRouter",
            "url": "https://openrouter.ai/api/v1/chat/completions",
            "key": or_key,
            "model": "google/gemma-3-27b-it:free",
            "timeout": 30
        })

    if not configs:
        print("No API keys found for Fireworks or OpenRouter.")
        raise RuntimeError("No configured LLM endpoints are available.")

    last_err = None
    for cfg in configs:
        print(f"Attempting discovery with {cfg['label']} ({cfg['model']})...")
        try:
            resp = requests.post(
                cfg["url"],
                headers={"Authorization": f"Bearer {cfg['key']}"},
                json={
                    "model": cfg["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 200
                },
                timeout=cfg["timeout"]
            )
            if resp.status_code == 200:
                choices = resp.json().get("choices") or []
                if choices:
                    content = choices[0].get("message", {}).get("content")
                    if content and content.strip():
                        return content
                    else:
                        print(f"Empty content from {cfg['label']}")
                else:
                    print(f"No choices returned from {cfg['label']}")
            else:
                print(f"{cfg['label']} returned status {resp.status_code}: {resp.text}")
                last_err = f"Status {resp.status_code}"
        except Exception as e:
            print(f"Error calling {cfg['label']}: {e}")
            last_err = str(e)
    raise RuntimeError(f"All LLM configurations failed. Last error: {last_err}")

def parse_llm_json(raw: str):
    raw = raw.strip()
    if raw.startswith("```json"):
        raw = raw[7:]
    elif raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()
    return json.loads(raw)

def validate_verse(surah: int, verse: int) -> bool:
    try:
        url = f"https://api.quran.com/api/v4/verses/by_key/{surah}:{verse}"
        resp = requests.get(url, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f"Quran API validation failed: {e}")
        return False

@app.post("/discover")
async def discover_verse(req: DiscoverRequest):
    prompt = f"""You are a Quran scholar. A user is searching for a Quran verse.

User query: "{req.query}"

Task: Identify the single most relevant verse in the Quran that matches this query.

Rules:
- Return ONLY a JSON object, no markdown, no explanation outside the JSON
- JSON format: {{"surah": <integer 1-114>, "verse": <valid integer>, "surah_name": "<english name>", "reason": "<one sentence why this verse matches>"}}
- surah and verse must be real, existing verse numbers
- Prefer well-known, clear verses over obscure ones
- reason must be in English, max 15 words"""

    try:
        raw_response = query_llm(prompt)
        parsed = None
        surah = None
        verse = None
        surah_name = None
        reason = None
        
        try:
            parsed = parse_llm_json(raw_response)
            surah = int(parsed["surah"])
            verse = int(parsed["verse"])
            surah_name = str(parsed["surah_name"])
            reason = str(parsed["reason"])
            
            if validate_verse(surah, verse):
                return {
                    "surah": surah,
                    "verse": verse,
                    "surah_name": surah_name,
                    "reason": reason
                }
            retry_msg = f"\n\nVerse {surah}:{verse} does not exist. Pick a different verse."
        except Exception as parse_err:
            print(f"First attempt parse/validate failed: {parse_err}")
            retry_msg = "\n\nPrevious response was invalid. Please return a valid JSON object matching the requested schema with real surah and verse numbers."

        # If it failed to parse or validate, retry once
        retry_prompt = prompt + retry_msg
        raw_response_retry = query_llm(retry_prompt)
        parsed_retry = parse_llm_json(raw_response_retry)
        surah_retry = int(parsed_retry["surah"])
        verse_retry = int(parsed_retry["verse"])
        surah_name_retry = str(parsed_retry["surah_name"])
        reason_retry = str(parsed_retry["reason"])
        
        if validate_verse(surah_retry, verse_retry):
            return {
                "surah": surah_retry,
                "verse": verse_retry,
                "surah_name": surah_name_retry,
                "reason": reason_retry
            }
            
    except Exception as e:
        print(f"Discover verse execution failed: {e}")

    raise HTTPException(
        status_code=422,
        detail="Could not identify a matching verse. Please try a different query."
    )

@app.post("/generate")
async def generate_endpoint(req: GenerateRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending"}
    background_tasks.add_task(background_generate, job_id, req.surah, req.verse, req.orientation)
    return {"job_id": job_id}

@app.post("/generate-range")
async def generate_range_endpoint(req: GenerateRangeRequest, background_tasks: BackgroundTasks):
    if req.start_verse > req.end_verse:
        raise HTTPException(status_code=400, detail="start_verse must be <= end_verse")
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending"}
    background_tasks.add_task(background_generate_range, job_id, req.surah, req.start_verse, req.end_verse, req.orientation)
    return {"job_id": job_id}

@app.post("/generate-bulk")
async def generate_bulk_endpoint(req: GenerateBulkRequest, background_tasks: BackgroundTasks):
    if req.start_verse > req.end_verse:
        raise HTTPException(status_code=400, detail="start_verse must be <= end_verse")
    if req.verses_per_video < 1:
        raise HTTPException(status_code=400, detail="verses_per_video must be >= 1")

    batch_id = str(uuid.uuid4())
    bulk_batches[batch_id] = {"status": "pending"}
    background_tasks.add_task(
        background_generate_bulk,
        batch_id, req.surah, req.start_verse, req.end_verse,
        req.verses_per_video, req.orientation
    )
    return {"batch_id": batch_id}

@app.get("/bulk-status/{batch_id}")
async def get_bulk_status(batch_id: str):
    if batch_id not in bulk_batches:
        raise HTTPException(status_code=404, detail="Bulk batch not found")
    return bulk_batches[batch_id]

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

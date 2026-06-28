# Quran Video Generator Codebase Context

This document contains all the source code files for the Quran Video Generator project. It is intended to be used as context for AI assistants.

## File Index
- [app.py](#apppy)
- [generate_video.py](#generate_videopy)
- [index.html](#indexhtml)
- [.gitignore](#gitignore)

---

## app.py
```python
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
import uuid
import os
from datetime import datetime
from generate_video import generate_verse_video, generate_range_video, generate_verse_video_to_dir

app = FastAPI(title="Quran Video Generator")

jobs = {}

# Global tracker for bulk batch jobs.
# Structure: { batch_id: { "status", "total", "completed", "failed", "batch_dir", "chunks", "videos" } }
bulk_batches = {}

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
    batch_dir = os.path.join("output", f"bulk_batch_{timestamp}")
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
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

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

```
---

## generate_video.py
```python
import os
import re
import sys
import time
import subprocess
import requests
import json
import shutil
import unicodedata
from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding='utf-8')

def download_fonts():
    poppins_url = "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Regular.ttf"
    if not os.path.exists("Poppins-Regular.ttf") or os.path.getsize("Poppins-Regular.ttf") < 10000:
        print("Downloading Poppins-Regular.ttf...")
        r = requests.get(poppins_url, allow_redirects=True)
        if r.status_code == 200:
            with open("Poppins-Regular.ttf", "wb") as f:
                f.write(r.content)
            print(f"Poppins downloaded. Size: {os.path.getsize('Poppins-Regular.ttf')} bytes")

    if not os.path.exists("UthmanicHafs.ttf") or os.path.getsize("UthmanicHafs.ttf") < 100000:
        urls = [
            "https://github.com/mustafa0x/qpc-fonts/raw/master/QCF_BSML.TTF",
            "https://www.noor-book.com/fonts/UthmanicHafs1Ver18.ttf"
        ]
        success = False
        for url in urls:
            print(f"Trying to download Uthmanic Hafs from {url}...")
            try:
                r = requests.get(url, allow_redirects=True, timeout=10)
                if r.status_code == 200 and len(r.content) > 10000:
                    with open("UthmanicHafs.ttf", "wb") as f:
                        f.write(r.content)
                    print(f"Success! UthmanicHafs.ttf downloaded from {url}. Size: {os.path.getsize('UthmanicHafs.ttf')} bytes")
                    success = True
                    break
            except Exception as e:
                print(f"Failed to download from {url}: {e}")

        if not success:
            print("All Uthmanic Hafs downloads failed. Falling back to Amiri-Regular.ttf")
            if os.path.exists("Amiri-Regular.ttf"):
                shutil.copy("Amiri-Regular.ttf", "UthmanicHafs.ttf")
                print("Copied Amiri-Regular.ttf as fallback.")

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
except ImportError:
    print("Installing arabic_reshaper and python-bidi...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "arabic-reshaper", "python-bidi"])
    import arabic_reshaper
    from bidi.algorithm import get_display

reshaper = arabic_reshaper.ArabicReshaper(configuration={
    'delete_harakat': False,
    'support_ligatures': True
})

def get_arabic_display(text):
    return get_display(reshaper.reshape(text))

def clean_english_text(text):
    text = re.sub(r'<[^>]+>', ' ', text)   # replace tags with space
    text = re.sub(r'\s+', ' ', text).strip()  # collapse all whitespace
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'\(\d+\)', '', text)
    text = re.sub(r'\d+', '', text)
    text = re.sub(r'[\u2011\u2012\u2013\u2014\u2015]', '-', text)
    text = text.replace('\u2018', "'").replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"')
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', text)  # camelCase fix
    text = re.sub(r'\b(no)(god|one|thing|where|body|how)\b', r'\1 \2', text)  # no+word joins
    text = text.replace('\u2011', '-')  # non-breaking hyphen
    text = text.replace('\u2012', '-')  # figure dash
    text = text.replace('\u2013', '-')  # en dash
    text = text.replace('\u2014', '-')  # em dash
    text = text.replace('\u2015', '-')  # horizontal bar
    # Fix double commas: ', ,' or ',,' → ','
    text = re.sub(r',\s*,', ',', text)
    # Fix floating periods: ' .' → '.'
    text = re.sub(r'\s+\.', '.', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def fetch_surah_name(surah):
    url = f"https://api.quran.com/api/v4/chapters/{surah}"
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json().get("chapter", {}).get("name_simple", f"Surah-{surah}")

def fetch_verse_data(surah, verse):
    print(f"Fetching words and translation for {surah}:{verse}...")
    base_url = "https://api.quran.com/api/v4"
    verse_key = f"{surah}:{verse}"

    # Words
    url_words = f"{base_url}/verses/by_key/{verse_key}?words=true&word_fields=text_uthmani"
    resp = requests.get(url_words).json()
    api_words = {}
    for w in resp.get("verse", {}).get("words", []):
        api_words[w["position"]] = w.get("text_uthmani", "")

    # Translation
    trans_url = f"{base_url}/quran/translations/20?chapter_number={surah}"
    t_resp = requests.get(trans_url)
    t_resp.raise_for_status()
    translations = t_resp.json().get("translations", [])
    english_translation = "N/A"
    index = verse - 1
    if 0 <= index < len(translations):
        raw_text = translations[index].get("text", "")
        english_translation = clean_english_text(raw_text)

    return api_words, english_translation

def fetch_verse_segments(surah, verse):
    print(f"Fetching word-level segments for {surah}:{verse}...")
    url = f"https://api.quran.com/api/v4/chapter_recitations/7/{surah}?segments=true"
    resp = requests.get(url)
    resp.raise_for_status()
    timestamps = resp.json().get("audio_file", {}).get("timestamps", [])

    verse_key = f"{surah}:{verse}"
    for ts in timestamps:
        if ts.get("verse_key") == verse_key:
            return ts.get("timestamp_from"), ts.get("timestamp_to"), ts.get("segments", [])

    return None, None, []

def download_verse_audio(surah, verse, dest_path):
    """Download the per-verse MP3 from everyayah.com (SSSAAA format) and save to dest_path."""
    filename = f"{str(surah).zfill(3)}{str(verse).zfill(3)}.mp3"
    url = f"https://everyayah.com/data/Alafasy_128kbps/{filename}"
    print(f"Downloading verse audio from: {url}")
    r = requests.get(url, allow_redirects=True, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Failed to download verse audio: HTTP {r.status_code} from {url}")
    with open(dest_path, "wb") as f:
        f.write(r.content)
    print(f"Verse audio saved: {dest_path} ({os.path.getsize(dest_path)} bytes)")

def get_llm_split(english_text, num_chunks, arabic_chunks=None, frames=None):
    def fallback_split(text, frames_list):
        print("Using rule-based fallback splitting (sentence-boundary + duration-weighted)...")
        # Split on sentence-ending punctuation
        sentences = re.split(r'(?<=[.?!])\s+|(?<=[.?!"])\s*', text.strip())
        sentences = [s for s in sentences if s.strip()]
        if not sentences:
            return [''] * len(frames_list)

        total_dur = sum(f['duration'] for f in frames_list)
        result = [''] * len(frames_list)
        total_words = len(text.split())
        sent_idx = 0

        for i, frame in enumerate(frames_list):
            weight = frame['duration'] / total_dur if total_dur > 0 else 1 / len(frames_list)
            target_words = int(weight * total_words)
            while sent_idx < len(sentences):
                result[i] = (result[i] + ' ' + sentences[sent_idx]).strip()
                sent_idx += 1
                if len(result[i].split()) >= target_words or sent_idx >= len(sentences):
                    break

        # dump any remaining sentences into last frame
        while sent_idx < len(sentences):
            result[-1] = (result[-1] + ' ' + sentences[sent_idx]).strip()
            sent_idx += 1

        return result

    def restore_spaces(original_text, split_lines):
        original_words = original_text.split()
        restored_lines = []
        word_idx = 0
        
        for line in split_lines:
            line_chars = len("".join(line.split()))
            if line_chars == 0:
                restored_lines.append("")
                continue
                
            restored_words = []
            chars_matched = 0
            
            while word_idx < len(original_words):
                w = original_words[word_idx]
                restored_words.append(w)
                chars_matched += len(w)
                word_idx += 1
                if chars_matched >= line_chars:
                    break
                    
            restored_lines.append(" ".join(restored_words))
            
        while word_idx < len(original_words):
            if not restored_lines:
                restored_lines.append("")
            restored_lines[-1] = (restored_lines[-1] + " " + original_words[word_idx]).strip()
            word_idx += 1
            
        return restored_lines

    # Build sub-frame list for the prompt
    if arabic_chunks and len(arabic_chunks) == num_chunks:
        segments_str = "\n".join(
            f"Sub-frame {i+1}: {arabic_chunks[i]}" for i in range(num_chunks)
        )
    else:
        segments_str = "\n".join(f"Sub-frame {i+1}: (Arabic text unavailable)" for i in range(num_chunks))

    prompt = f"""You are aligning an English Quran translation to Arabic sub-frames.

Arabic sub-frames ({num_chunks} total):
{segments_str}

English translation:
"{english_text}"

Rules:
1. Split the English into EXACTLY {num_chunks} parts
2. Each part must match the MEANING of its Arabic sub-frame — not English grammar
3. Some Arabic sub-frames may be mid-sentence — that is fine, give them the matching English fragment
4. Do NOT rewrite or paraphrase any words. You must preserve exact words and spaces from the original translation text. Do not combine, mash, or alter any English words at the split boundaries (e.g., never turn 'the religion' into 'thereligion').
5. Every word of the English must appear in exactly one part
6. Return ONLY a JSON array of {num_chunks} strings, nothing else
7. PRONOUN RULE — pronouns ("He", "They", "It", "We", "You", "She") must stay WITH their verb in the SAME part. Never end a part on a bare pronoun that belongs to the next verb.
8. COMPLETENESS RULE — never split a subject from its verb across two parts. "He guides" must appear together in one part, not "He" in one and "guides" in the next.
9. READABILITY RULE — prefer independently readable parts WHERE POSSIBLE, but never at the cost of bleeding words into a frame whose Arabic does not contain them. An incomplete English fragment that matches its Arabic chunk is CORRECT. A complete English sentence that steals words from the next frame is WRONG.
10. MAIN-VERB RULE — if a sentence spans two Arabic frames, assign the COMPLETE sentence to whichever frame contains the main verb.
11. ARABIC-FIRST OVERRIDE — Rule 9 is always subordinate to Rule 2. If the Arabic chunk is mid-sentence, give ONLY the English words that correspond to those exact Arabic words. Do not complete the thought. Do not make it readable at the expense of accuracy. The on-screen Arabic and English must correspond word-for-word in meaning.

Example of correct mid-sentence split:
Arabic: ["they are only", "in dissension"]
English split: ["they are only", "in dissension,"]

NOT this (wrong — splits at English grammar):
["but if they turn away,", "they are only in dissension,"]

Example of CORRECT pronoun handling:
Arabic: ["To Allah belongs the east and the west.", "He guides whom He wills to a straight path."]
English split: ["To Allah belongs the east and the west.", "He guides whom He wills to a straight path."]

NOT this (wrong — pronoun bleeds into wrong frame):
["To Allah belongs the east and the west. He", "guides whom He wills to a straight path."]"""

    MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"

    def parse_and_return(res_text, provider_label):
        # Guard: None or non-string content must not reach .strip()
        if not isinstance(res_text, str) or not res_text.strip():
            raise ValueError(f"Empty or non-string response from {provider_label}")
        res_text = res_text.strip()
        if res_text.startswith("```json"):
            res_text = res_text[7:-3]
        elif res_text.startswith("```"):
            res_text = res_text[3:-3]
        parts = json.loads(res_text.strip())
        if len(parts) == num_chunks:
            print(f"  [PROVIDER] {provider_label}")
            return restore_spaces(english_text, parts)
        else:
            print(f"  LLM returned {len(parts)} chunks instead of {num_chunks}. Padding/truncating...")
            while len(parts) < num_chunks: parts.append("")
            print(f"  [PROVIDER] {provider_label}")
            return restore_spaces(english_text, parts[:num_chunks])

    # ── 1. Build API configurations ──────────────────────────────────────────
    configs = []

    # Add OpenRouter configurations
    openrouter_keys = [
        ("OPENROUTER_API_KEY", os.environ.get("OPENROUTER_API_KEY")),
        ("OPENROUTER_API_KEY_2", os.environ.get("OPENROUTER_API_KEY_2")),
        ("OPENROUTER_API_KEY_3", os.environ.get("OPENROUTER_API_KEY_3")),
        ("OPENROUTER_API_KEY_4", os.environ.get("OPENROUTER_API_KEY_4"))
    ]
    for env_name, val in openrouter_keys:
        if val:
            configs.append({
                "label": f"OpenRouter ({env_name})",
                "url": "https://openrouter.ai/api/v1/chat/completions",
                "key": val,
                "model": MODEL
            })

    if configs:
        for cfg_idx, cfg in enumerate(configs):
            print(f"  Attempting {cfg['label']} with model: {cfg['model']} ({cfg_idx + 1}/{len(configs)})")
            try:
                response = requests.post(
                    cfg["url"],
                    headers={"Authorization": f"Bearer {cfg['key']}"},
                    json={
                        "model": cfg["model"],
                        "messages": [{"role": "user", "content": prompt}]
                    },
                    timeout=60
                )

                if response.status_code == 200:
                    resp_json = response.json()
                    choices   = resp_json.get("choices") or []
                    if choices:
                        # ── Safe content extraction ──────────────────
                        raw_content = choices[0].get("message", {}).get("content")
                        if not isinstance(raw_content, str) or not raw_content.strip():
                            print("    Model returned None/empty content. Moving to next config.")
                            continue
                        # ── Try to parse ─────────────────────────────
                        try:
                            result = parse_and_return(raw_content, f"{cfg['label']}/{cfg['model']}")
                            return result       # ← success path
                        except Exception as pe:
                            print(f"    Parse error: {pe}. Moving to next config.")
                            continue
                    else:
                        print("    Error: 'choices' missing or empty in response. Moving to next config.")
                else:
                    print(f"    {cfg['label']} returned status {response.status_code}. Moving to next config.")

            except Exception as e:
                print(f"    Error calling LLM ({cfg['label']}): {e}")

        print("All API configurations exhausted.")
    else:
        print("No OpenRouter API keys set — skipping LLM splitting.")

    # ── 2. All keys exhausted — raise error ───────────────────────────────────
    raise RuntimeError(
        "Video generation failed — all AI models unavailable, please try again later"
    )



def render_image(arabic_text, english_text, output_img, ar_font_path="UthmanicHafs.ttf", en_font_path="Poppins-Regular.ttf", surah_img=None, orientation='horizontal'):
    if orientation == 'vertical':
        W, H = 1080, 1920
        MAX_TEXT_W = 900
        ar_size_start = 60
        en_size_start = 38
    else:
        W, H = 1920, 1080
        MAX_TEXT_W = 1400
        ar_size_start = 55
        en_size_start = 38

    img = Image.new('RGB', (W, H), color='black')

    # Paste surah title image centered horizontally, 12% down from top
    if surah_img is not None:
        x = (W - surah_img.width) // 2
        y = int(H * 0.12)
        img.paste(surah_img, (x, y), mask=surah_img)

    draw = ImageDraw.Draw(img)

    display_arabic = get_arabic_display(arabic_text)

    ar_size = ar_size_start
    ar_font = ImageFont.truetype(ar_font_path, ar_size)
    while ar_font.getlength(display_arabic) > MAX_TEXT_W and ar_size > 20:
        ar_size -= 2
        ar_font = ImageFont.truetype(ar_font_path, ar_size)

    ar_width = ar_font.getlength(display_arabic)
    ar_bbox = ar_font.getbbox(display_arabic)
    ar_height = (ar_bbox[3] - ar_bbox[1]) + 20

    en_size = en_size_start
    en_font = ImageFont.truetype(en_font_path, en_size)

    def wrap_text_pixels(text, font, max_width):
        words = text.split()
        lines = []
        current_line = []
        for word in words:
            test_line = " ".join(current_line + [word]) if current_line else word
            if font.getlength(test_line) <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                else:
                    lines.append(word)
                    current_line = []
        if current_line:
            lines.append(" ".join(current_line))
        return lines

    wrapped_en = wrap_text_pixels(english_text, en_font, MAX_TEXT_W)
    while len(wrapped_en) > 3 and en_size > 28:
        en_size -= 2
        en_font = ImageFont.truetype(en_font_path, en_size)
        wrapped_en = wrap_text_pixels(english_text, en_font, MAX_TEXT_W)

    if len(wrapped_en) > 3:
        wrapped_en = wrapped_en[:3]
        last_line = wrapped_en[2]
        while en_font.getlength(last_line + "...") > MAX_TEXT_W and len(last_line) > 0:
            last_line = last_line[:-1]
        wrapped_en[2] = last_line.strip() + "..."

    line_height = 48
    gap_between_ar_en = 40

    if orientation == 'vertical':
        # Fixed vertical positions: Arabic at 43%, English starts at 54%
        ar_x = W // 2
        ar_y = int(H * 0.43)
        draw.text((ar_x, ar_y), display_arabic, font=ar_font, fill="white", anchor="mt")
        current_y = ar_y + ar_height + 30  # 30px gap, consistent every frame
        for line in wrapped_en:
            draw.text((W // 2, current_y), line, font=en_font, fill="white", anchor="mt")
            current_y += line_height
    else:
        num_lines = len(wrapped_en) if wrapped_en else 0
        english_block_height = num_lines * line_height
        total_height = ar_height + gap_between_ar_en + english_block_height

        start_y = (H - total_height) // 2
        start_y += 60

        ar_x = (W - ar_width) // 2
        # Bring Arabic down 35px closer to English
        draw.text((ar_x, start_y + 35), display_arabic, font=ar_font, fill="white")

        current_y = start_y + ar_height + gap_between_ar_en
        for line in wrapped_en:
            line_w = en_font.getlength(line)
            line_x = (W - line_w) // 2
            draw.text((line_x, current_y), line, font=en_font, fill="white")
            current_y += line_height

    img.save(output_img)

def generate_verse_video(surah, verse, orientation='horizontal', step_callback=None):
    if step_callback: step_callback("Gathering verse text and audio...", 0)
    surah_name = fetch_surah_name(surah)
    download_fonts()
    api_words, english_text = fetch_verse_data(surah, verse)
    verse_start_ms, verse_end_ms, segments = fetch_verse_segments(surah, verse)

    if verse_start_ms is None:
        raise ValueError(f"Could not find timestamps for {surah}:{verse}")

    # Aggregate word segments (timestamps are relative to verse start in QDC segments)
    word_segments = []
    for seg in segments:
        if len(seg) >= 3:
            word_idx, start_ms, end_ms = seg[0], seg[1], seg[2]
            if word_idx in api_words:
                word_segments.append({
                    "idx": word_idx,
                    "text": api_words[word_idx],
                    "start": start_ms,
                    "end": end_ms
                })

    aggregated_words = []
    current_word = None
    for ws in word_segments:
        if current_word is None:
            current_word = ws.copy()
        elif current_word["idx"] == ws["idx"]:
            current_word["end"] = ws["end"]
        else:
            aggregated_words.append(current_word)
            current_word = ws.copy()
    if current_word:
        aggregated_words.append(current_word)

    # Calculate screen-fitting chunks
    ar_font_path = "UthmanicHafs.ttf"
    chunk_ar_size = 60 if orientation == 'vertical' else 55
    chunk_max_width = 900 if orientation == 'vertical' else 1400
    font = ImageFont.truetype(ar_font_path, chunk_ar_size)
    max_width = chunk_max_width

    raw_chunks = []
    current_chunk = []
    current_width = 0

    for w in aggregated_words:
        w_width = font.getlength(w["text"] + " ")
        if current_width + w_width > max_width and current_chunk:
            raw_chunks.append(current_chunk)
            current_chunk = [w]
            current_width = w_width
        else:
            current_chunk.append(w)
            current_width += w_width

    if current_chunk:
        raw_chunks.append(current_chunk)

    print(f"Verse split into {len(raw_chunks)} screen-fitting chunks.")

    # ── Pause-based sub-splitting using Quranic stop markers ─────────────────
    PAUSE_MARKERS = '\u06DA\u06D7\u06D6\u06DB\u06DC\u06D9'  # ۚ ۗ ۖ ۛ ۜ ۙ

    def has_pause_marker(word_text):
        return any(char in PAUSE_MARKERS for char in word_text)

    def pause_split_chunk(word_list, chunk_end_ms):
        """Split at any word containing a Quranic pause marker.
        Returns list of (sub_words, frame_duration_s) tuples."""
        frames = []
        current = [word_list[0]]
        for j in range(1, len(word_list)):
            if has_pause_marker(word_list[j-1]["text"]):
                # split after the marked word; duration = next word start - current group start
                frame_dur_ms = word_list[j]["start"] - current[0]["start"]
                frames.append((current, frame_dur_ms / 1000.0))
                current = [word_list[j]]
            else:
                current.append(word_list[j])
        # last sub-frame: extend to chunk boundary
        last_dur_ms = chunk_end_ms - current[0]["start"]
        frames.append((current, last_dur_ms / 1000.0))
        return frames

    # Build final frames with pause splitting applied
    all_frames = []  # list of {arabic, word_count, duration}
    for i, raw_c in enumerate(raw_chunks):
        chunk_end_ms = raw_chunks[i+1][0]["start"] if i < len(raw_chunks)-1 else verse_end_ms
        sub_frames = pause_split_chunk(raw_c, chunk_end_ms)
        for sw, sf_dur in sub_frames:
            all_frames.append({
                "arabic": " ".join(w["text"] for w in sw),
                "word_count": len(sw),
                "duration": max(sf_dur, 0.1),
                "_raw_chunk_idx": i,
            })

    print(f"After pause splitting: {len(all_frames)} frames "
          f"(was {len(raw_chunks)} screen-width chunks, split on markers ۚۗۖۛۜ).")

    # ── Post-process: merge any single-word chunks into the previous chunk ────
    def merge_single_word_chunks(frames):
        # ── Pass 1: backward merge ────────────────────────────────────────────
        # Merge single-word frames into the previous frame, unless that frame
        # ends with a pause marker (boundary created intentionally by pause_split_chunk).
        merged = []
        for frame in frames:
            if frame["word_count"] == 1 and merged:
                prev = merged[-1]
                prev_ends_with_pause = any(char in PAUSE_MARKERS for char in prev["arabic"])
                if prev_ends_with_pause:
                    merged.append(frame)
                    continue
                prev["arabic"] = prev["arabic"] + " " + frame["arabic"]
                prev["word_count"] += frame["word_count"]
                prev["duration"] += frame["duration"]
            else:
                merged.append(frame)

        # ── Pass 2: forward merge ─────────────────────────────────────────────
        # Any single-word frame that was blocked from merging backward (because
        # its predecessor ends with a pause marker) is prepended into the NEXT
        # frame instead, so no word ever appears alone after a pause boundary.
        result = []
        i = 0
        while i < len(merged):
            frame = merged[i]
            prev_has_pause = (i > 0 and any(char in PAUSE_MARKERS for char in merged[i - 1]["arabic"]))
            if frame["word_count"] == 1 and prev_has_pause and i + 1 < len(merged):
                nxt = merged[i + 1]
                nxt["arabic"] = frame["arabic"] + " " + nxt["arabic"]
                nxt["word_count"] += frame["word_count"]
                nxt["duration"] += frame["duration"]
                i += 1
                continue
            result.append(frame)
            i += 1
        return result

    all_frames = merge_single_word_chunks(all_frames)
    print(f"After single-word merge: {len(all_frames)} frames.")

    # ── Fetch English splits — one part per pause-group frame ────────────────
    if step_callback: step_callback("Aligning words and translations...", 25)
    # LLM now sees the actual Arabic for each rendered frame, not the raw screen-width chunks.
    arabic_per_frame = [f["arabic"] for f in all_frames]
    english_per_frame = get_llm_split(english_text, len(all_frames), arabic_per_frame, frames=all_frames)

    # Fix dangling pronouns at frame boundaries
    DANGLING = {'He','She','It','They','We','You','I','A','An','The','And','But','Or'}
    for i in range(len(english_per_frame) - 1):
        words = english_per_frame[i].rstrip().split()
        if words and words[-1].rstrip('",.) ') in DANGLING:
            moved = words[-1]
            english_per_frame[i] = ' '.join(words[:-1]).rstrip()
            english_per_frame[i+1] = moved + ' ' + english_per_frame[i+1].lstrip()

    # Build final chunks list
    chunks = all_frames

    print("\n--- FRAME MAPPING ---")
    for i, c in enumerate(chunks):
        print(f"Frame {i}:")
        print(f"  Arabic:  {c['arabic']}")
        print(f"  English: {english_per_frame[i]}")
        print(f"  Duration: {c['duration']:.2f}s")
    print("---------------------\n")

    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    temp_dir = "temp_assets"
    os.makedirs(temp_dir, exist_ok=True)

    # Download per-verse audio
    temp_audio = os.path.join(temp_dir, "temp_verse_audio.mp3")
    download_verse_audio(surah, verse, temp_audio)

    # Fetch surah title image once before the rendering loop
    surah_img = None
    try:
        print(f"Fetching surah title image for surah {surah}...")
        from io import BytesIO
        resp = requests.get(f"http://api.qurancliphelper.com/titles/{surah}", timeout=10)
        resp.raise_for_status()
        surah_img = Image.open(BytesIO(resp.content)).convert("RGBA")
        target_w = 380
        ratio = target_w / surah_img.width
        surah_img = surah_img.resize((target_w, int(surah_img.height * ratio)), Image.LANCZOS)
        print(f"Surah title image loaded: {surah_img.size}")
    except Exception as e:
        print(f"Warning: Could not fetch surah title image: {e}. Continuing without it.")

    # Generate frame images and concat file
    print("Generating frames...")
    concat_file_path = os.path.join(temp_dir, "concat.txt")
    with open(concat_file_path, "w", encoding="utf-8") as f:
        for i, c in enumerate(chunks):
            if step_callback: step_callback("Creating video screens...", 50 + int((i/max(1, len(chunks)))*25))
            img_path = os.path.join(temp_dir, f"chunk_{i}.png")
            print(f"  Frame {i} Arabic → {c['arabic']}")
            render_image(c["arabic"], english_per_frame[i], img_path, ar_font_path, "Poppins-Regular.ttf", surah_img=surah_img, orientation=orientation)
            f.write(f"file '{os.path.basename(img_path)}'\n")
            f.write(f"duration {c['duration']}\n")

        # concat demuxer requires the last file repeated without a duration
        safe_last = f"chunk_{len(chunks)-1}.png"
        f.write(f"file '{safe_last}'\n")

    surah_name_clean = surah_name.replace('-', ' ').lower()
    output_filename = os.path.join(output_dir, f"surah {surah_name_clean} verse {verse}.mp4")

    # FFmpeg: concat images + per-verse audio
    print("Rendering final concatenated video...")
    if step_callback: step_callback("Polishing and saving final video...", 75)
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", "concat.txt",
        "-i", "temp_verse_audio.mp3",
        "-vf", "fps=30",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        "-shortest",
        f"../{output_filename}"
    ]

    try:
        subprocess.check_call(cmd, cwd=temp_dir, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        print(f"Successfully rendered: {output_filename}")
        total_duration = (verse_end_ms - verse_start_ms) / 1000.0
        print(f"Total Video Duration (from segments): {total_duration:.2f}s")
        success = True
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg error: {e}")
        success = False

    # Cleanup temp folder and any stray root-level temp files
    shutil.rmtree(temp_dir, ignore_errors=True)
    for stray in ["concat.txt", "temp_verse.mp3", "temp_verse_audio.mp3"]:
        if os.path.exists(stray):
            os.remove(stray)

    if success:
        return output_filename
    else:
        raise RuntimeError("Video generation failed during FFmpeg encoding.")

def generate_verse_video_to_dir(surah, verse, output_dir, orientation='horizontal', step_callback=None):
    """
    Renders a single verse video exactly like generate_verse_video(), but saves
    the final MP4 into *output_dir* with the clean filename pattern:
        <SurahName>_<verse>.mp4   (e.g. Al-Baqarah_5.mp4)
    Returns the full path to the saved MP4.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Re-use the existing pipeline; it saves to the default 'output/' folder.
    raw_path = generate_verse_video(surah, verse, orientation=orientation, step_callback=step_callback)

    # Build a clean destination name
    surah_name = fetch_surah_name(surah)
    # Replace spaces/dashes with hyphens for a clean filename
    surah_name_clean = surah_name.replace(' ', '-')
    dest_name = f"{surah_name_clean}_{verse}.mp4"
    dest_path = os.path.join(output_dir, dest_name)

    shutil.move(raw_path, dest_path)
    print(f"[bulk] Moved '{raw_path}' → '{dest_path}'")
    return dest_path


def generate_range_video(surah, start_verse, end_verse, progress_callback=None, orientation='horizontal'):
    """Render each verse in [start_verse, end_verse] individually then concatenate into one MP4."""
    surah_name = fetch_surah_name(surah)
    download_fonts()
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    range_temp_dir = os.path.join(output_dir, f"range_temp_{surah}_{start_verse}_{end_verse}")
    os.makedirs(range_temp_dir, exist_ok=True)

    verse_files = []
    total_verses = end_verse - start_verse + 1

    for i, verse in enumerate(range(start_verse, end_verse + 1)):
        verse_num = i + 1
        
        def verse_step_cb(step_str, pct):
            overall_pct = int(((i + (pct / 100.0)) / total_verses) * 100)
            if progress_callback:
                progress_callback(verse_num, total_verses, verse, step_str, overall_pct)

        if progress_callback:
            progress_callback(verse_num, total_verses, verse, "Starting...", int((i / total_verses) * 100))
        print(f"\n=== Rendering verse {surah}:{verse} ({verse_num}/{total_verses}) ===")
        try:
            verse_output = generate_verse_video(surah, verse, orientation=orientation, step_callback=verse_step_cb)
            verse_files.append(verse_output)
        except Exception as e:
            print(f"ERROR rendering verse {surah}:{verse}: {e}")
            raise

    # Build FFmpeg concat list
    concat_path = os.path.join(range_temp_dir, "range_concat.txt")
    with open(concat_path, "w", encoding="utf-8") as f:
        for vf in verse_files:
            abs_path = os.path.abspath(vf).replace("\\", "/")
            f.write(f"file '{abs_path}'\n")

    surah_name_clean = surah_name.replace('-', ' ').lower()
    final_output = os.path.join(output_dir, f"surah {surah_name_clean} verse {start_verse}-{end_verse}.mp4")
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_path,
        "-c", "copy",
        final_output
    ]
    print(f"\n=== Concatenating {total_verses} verse videos into {final_output} ===")
    subprocess.check_call(cmd)
    print(f"Range video complete: {final_output}")

    # Cleanup: temp concat dir and individual verse MP4s
    shutil.rmtree(range_temp_dir, ignore_errors=True)
    for vf in verse_files:
        if os.path.exists(vf):
            os.remove(vf)
            print(f"Deleted temp verse file: {vf}")

    return final_output

if __name__ == "__main__":
    print("Generating vertical video...")
    generate_verse_video(2, 255, 'vertical')


```
---

## index.html
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Quran Studio — Video Generator</title>
  <meta name="description" content="Generate beautiful Quran verse videos with Arabic text and English translation, synced to recitation audio.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=Amiri:wght@400;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg:        #0a0a0a;
      --card-bg:   #111111;
      --gold:      #c9a84c;
      --gold-dim:  #a07828;
      --gold-glow: rgba(201,168,76,0.18);
      --border:    rgba(201,168,76,0.15);
      --text:      #f0ead6;
      --muted:     #7a7060;
      --input-bg:  rgba(0,0,0,0.45);
      --green:     #2ecc71;
      --red:       #e74c3c;
      --amber:     #f39c12;
      --transition: 0.22s ease;
    }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      background: var(--bg);
      color: var(--text);
      font-family: 'Inter', sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 32px 16px 64px;
      position: relative;
      overflow-x: hidden;
    }

    /* ── Islamic geometric watermark ─────────────────────────── */
    body::before {
      content: '';
      position: fixed;
      inset: 0;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cdefs%3E%3Cpattern id='geo' x='0' y='0' width='120' height='120' patternUnits='userSpaceOnUse'%3E%3Cg fill='none' stroke='%23c9a84c' stroke-width='0.4' opacity='0.07'%3E%3Cpolygon points='60,10 110,35 110,85 60,110 10,85 10,35'/%3E%3Cpolygon points='60,30 90,45 90,75 60,90 30,75 30,45'/%3E%3Cline x1='60' y1='10' x2='60' y2='30'/%3E%3Cline x1='110' y1='35' x2='90' y2='45'/%3E%3Cline x1='110' y1='85' x2='90' y2='75'/%3E%3Cline x1='60' y1='110' x2='60' y2='90'/%3E%3Cline x1='10' y1='85' x2='30' y2='75'/%3E%3Cline x1='10' y1='35' x2='30' y2='45'/%3E%3Ccircle cx='60' cy='60' r='10'/%3E%3C/g%3E%3C/pattern%3E%3C/defs%3E%3Crect width='100%25' height='100%25' fill='url(%23geo)'/%3E%3C/svg%3E");
      pointer-events: none;
      z-index: 0;
    }

    /* ── Header ──────────────────────────────────────────────── */
    .header {
      text-align: center;
      margin-bottom: 28px;
      position: relative;
      z-index: 1;
    }
    .app-name {
      font-size: 2rem;
      font-weight: 300;
      letter-spacing: 0.2em;
      color: var(--gold);
      text-transform: uppercase;
    }
    .app-name span { font-weight: 600; }
    .arabic-subtitle {
      font-family: 'Amiri', serif;
      font-size: 1.1rem;
      color: var(--muted);
      margin-top: 6px;
      direction: rtl;
    }
    .header-divider {
      width: 60px;
      height: 1px;
      background: linear-gradient(90deg, transparent, var(--gold), transparent);
      margin: 14px auto 0;
    }

    /* ── Tab Nav ─────────────────────────────────────────────── */
    .tab-nav {
      position: relative;
      z-index: 1;
      display: flex;
      gap: 0;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 5px;
      margin-bottom: 18px;
      width: 100%;
      max-width: 480px;
    }
    .tab-btn {
      flex: 1;
      padding: 10px 16px;
      background: transparent;
      border: none;
      border-radius: 10px;
      color: var(--muted);
      font-family: 'Inter', sans-serif;
      font-size: 0.82rem;
      font-weight: 500;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      cursor: pointer;
      transition: background var(--transition), color var(--transition), box-shadow var(--transition);
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
    }
    .tab-btn:hover { color: var(--gold-dim); }
    .tab-btn.active {
      background: linear-gradient(135deg, rgba(160,120,40,0.25), var(--gold-glow));
      color: var(--gold);
      box-shadow: 0 0 14px rgba(201,168,76,0.18);
    }

    /* ── Card ────────────────────────────────────────────────── */
    .card {
      position: relative;
      z-index: 1;
      width: 100%;
      max-width: 480px;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 20px;
      box-shadow:
        0 0 0 1px rgba(201,168,76,0.05),
        0 24px 60px rgba(0,0,0,0.7),
        0 0 40px var(--gold-glow);
      overflow: hidden;
    }

    /* Tab panels */
    .tab-panel { display: none; }
    .tab-panel.active { display: block; }

    .card-body { padding: 28px 28px 24px; }

    /* ── Section headings inside card ────────────────────────── */
    .section-label {
      font-size: 0.68rem;
      font-weight: 600;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--gold);
      opacity: 0.6;
      margin-bottom: 16px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .section-label::after {
      content: '';
      flex: 1;
      height: 1px;
      background: var(--border);
    }

    /* ── Inputs ──────────────────────────────────────────────── */
    .input-group { margin-bottom: 18px; }
    .input-row { display: flex; gap: 14px; }
    .input-row .input-group { flex: 1; }

    label {
      display: block;
      font-size: 0.74rem;
      font-weight: 500;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 8px;
    }

    input[type="number"],
    select {
      width: 100%;
      padding: 11px 14px;
      background: var(--input-bg);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 9px;
      color: var(--text);
      font-family: 'Inter', sans-serif;
      font-size: 1rem;
      transition: var(--transition);
      -moz-appearance: textfield;
      appearance: none;
      -webkit-appearance: none;
    }
    select {
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='%237a7060' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 12px center;
      padding-right: 36px;
      cursor: pointer;
    }
    select option {
      background: #1a1a1a;
      color: var(--text);
    }
    input[type="number"]::-webkit-inner-spin-button,
    input[type="number"]::-webkit-outer-spin-button { -webkit-appearance: none; }
    input[type="number"]:focus,
    select:focus {
      outline: none;
      border-color: var(--gold);
      box-shadow: 0 0 0 3px rgba(201,168,76,0.12);
    }

    .surah-hint {
      margin-top: 6px;
      min-height: 18px;
      font-size: 0.78rem;
      color: var(--gold);
      font-style: italic;
      opacity: 0;
      transition: var(--transition);
    }
    .surah-hint.show { opacity: 1; }

    /* ── Generate button ─────────────────────────────────────── */
    .btn-generate {
      width: 100%;
      margin-top: 8px;
      padding: 13px 20px;
      background: linear-gradient(135deg, var(--gold-dim), var(--gold));
      border: none;
      border-radius: 9px;
      color: #0a0a0a;
      font-family: 'Inter', sans-serif;
      font-size: 0.9rem;
      font-weight: 600;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      transition: transform var(--transition), box-shadow var(--transition), opacity var(--transition);
    }
    .btn-generate:hover:not(:disabled) {
      transform: translateY(-2px);
      box-shadow: 0 8px 28px rgba(201,168,76,0.4);
    }
    .btn-generate:disabled { opacity: 0.4; cursor: not-allowed; transform: none; box-shadow: none; }

    .btn-spinner {
      width: 16px; height: 16px;
      border: 2px solid rgba(0,0,0,0.25);
      border-top-color: #0a0a0a;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      display: none;
    }
    .btn-generate.loading .btn-spinner { display: block; }
    .btn-generate.loading .btn-label  { opacity: 0.7; }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* ── Single-video Status area ─────────────────────────────── */
    .status-area { margin-top: 20px; display: none; flex-direction: column; gap: 12px; }
    .status-area.visible { display: flex; }

    .status-row { display: flex; align-items: center; gap: 10px; }
    .status-dot {
      width: 8px; height: 8px;
      border-radius: 50%;
      background: var(--gold);
      animation: pulse 1.4s ease-in-out infinite;
      flex-shrink: 0;
    }
    .status-dot.done  { background: var(--green); animation: none; }
    .status-dot.error { background: var(--red);   animation: none; }
    @keyframes pulse {
      0%,100% { opacity:1; transform:scale(1); }
      50%      { opacity:.4; transform:scale(.75); }
    }
    .status-msg { font-size: 0.88rem; color: #bbb; flex: 1; }
    .status-msg.error { color: var(--red); }

    .progress-wrap {
      width: 100%; height: 3px;
      background: rgba(255,255,255,0.06);
      border-radius: 99px; overflow: hidden;
    }
    .progress-bar {
      height: 100%; width: 0%;
      background: linear-gradient(90deg, var(--gold-dim), var(--gold));
      border-radius: 99px;
      transition: width 0.6s ease-out;
    }

    /* ── Download button ─────────────────────────────────────── */
    .btn-download {
      width: 100%;
      padding: 12px 20px;
      background: transparent;
      border: 1px solid var(--green);
      border-radius: 9px;
      color: var(--green);
      font-family: 'Inter', sans-serif;
      font-size: 0.85rem;
      font-weight: 600;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      cursor: pointer;
      display: none;
      align-items: center;
      justify-content: center;
      gap: 8px;
      transition: background var(--transition), box-shadow var(--transition), transform var(--transition);
    }
    .btn-download.visible { display: flex; animation: fadeUp 0.35s ease; }
    .btn-download:hover {
      background: rgba(46,204,113,0.08);
      box-shadow: 0 0 20px rgba(46,204,113,0.2);
      transform: translateY(-1px);
    }
    @keyframes fadeUp {
      from { opacity:0; transform:translateY(8px); }
      to   { opacity:1; transform:translateY(0); }
    }

    /* ── Orientation toggle ──────────────────────────────────── */
    .orientation-toggle {
      display: flex;
      gap: 10px;
      margin-bottom: 18px;
    }
    .btn-orient {
      flex: 1;
      padding: 10px 12px;
      background: var(--input-bg);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 9px;
      color: var(--muted);
      font-family: 'Inter', sans-serif;
      font-size: 0.8rem;
      font-weight: 500;
      letter-spacing: 0.04em;
      cursor: pointer;
      transition: border-color var(--transition), color var(--transition), box-shadow var(--transition), background var(--transition);
      text-align: center;
    }
    .btn-orient:hover {
      border-color: var(--gold-dim);
      color: var(--gold-dim);
    }
    .btn-orient.active {
      border-color: var(--gold);
      color: var(--gold);
      background: var(--gold-glow);
      box-shadow: 0 0 12px rgba(201,168,76,0.2);
    }

    /* ── Verses-per-video helper text ────────────────────────── */
    .field-hint {
      margin-top: 6px;
      font-size: 0.75rem;
      color: var(--muted);
      font-style: italic;
      line-height: 1.4;
    }

    /* ── Batch Progress Dashboard ────────────────────────────── */
    .batch-dashboard {
      margin-top: 24px;
      display: none;
      flex-direction: column;
      gap: 0;
      animation: fadeUp 0.3s ease;
    }
    .batch-dashboard.visible { display: flex; }

    .batch-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 14px;
    }
    .batch-title {
      font-size: 0.72rem;
      font-weight: 600;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--gold);
      opacity: 0.7;
    }
    .batch-counter {
      font-size: 0.75rem;
      color: var(--muted);
    }
    .batch-counter strong { color: var(--gold); }

    /* Overall batch progress bar */
    .batch-overall-wrap {
      margin-bottom: 16px;
    }
    .batch-overall-label {
      display: flex;
      justify-content: space-between;
      font-size: 0.72rem;
      color: var(--muted);
      margin-bottom: 6px;
    }
    .batch-progress-wrap {
      width: 100%; height: 4px;
      background: rgba(255,255,255,0.06);
      border-radius: 99px; overflow: hidden;
    }
    .batch-progress-bar {
      height: 100%; width: 0%;
      background: linear-gradient(90deg, var(--gold-dim), var(--gold));
      border-radius: 99px;
      transition: width 0.7s ease-out;
    }

    /* Video chunk list */
    .chunk-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
      max-height: 360px;
      overflow-y: auto;
      padding-right: 2px;
    }
    .chunk-list::-webkit-scrollbar { width: 4px; }
    .chunk-list::-webkit-scrollbar-track { background: transparent; }
    .chunk-list::-webkit-scrollbar-thumb { background: rgba(201,168,76,0.2); border-radius: 99px; }

    .chunk-item {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 11px 14px;
      background: rgba(0,0,0,0.3);
      border: 1px solid rgba(255,255,255,0.05);
      border-radius: 10px;
      transition: border-color 0.3s ease, background 0.3s ease;
    }
    .chunk-item.is-rendering {
      border-color: rgba(201,168,76,0.25);
      background: rgba(201,168,76,0.04);
    }
    .chunk-item.is-done {
      border-color: rgba(46,204,113,0.2);
      background: rgba(46,204,113,0.04);
    }
    .chunk-item.is-error {
      border-color: rgba(231,76,60,0.25);
      background: rgba(231,76,60,0.04);
    }

    .chunk-icon {
      width: 28px; height: 28px;
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      flex-shrink: 0;
      font-size: 0.75rem;
    }
    .chunk-icon.pending  { background: rgba(255,255,255,0.05); color: var(--muted); }
    .chunk-icon.rendering {
      background: rgba(201,168,76,0.12);
      border: 1.5px solid rgba(201,168,76,0.4);
    }
    .chunk-icon.rendering .chunk-spin {
      width: 10px; height: 10px;
      border: 1.5px solid rgba(201,168,76,0.3);
      border-top-color: var(--gold);
      border-radius: 50%;
      animation: spin 0.7s linear infinite;
    }
    .chunk-icon.done    { background: rgba(46,204,113,0.15); color: var(--green); font-size: 0.9rem; }
    .chunk-icon.error   { background: rgba(231,76,60,0.15);  color: var(--red);   font-size: 0.9rem; }

    .chunk-info { flex: 1; min-width: 0; }
    .chunk-name {
      font-size: 0.84rem;
      font-weight: 500;
      color: var(--text);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .chunk-status-text {
      font-size: 0.73rem;
      color: var(--muted);
      margin-top: 2px;
    }
    .chunk-status-text.rendering { color: var(--gold); opacity: 0.8; }
    .chunk-status-text.done   { color: var(--green); opacity: 0.75; }
    .chunk-status-text.error  { color: var(--red); opacity: 0.85; }

    .chunk-badge {
      font-size: 0.65rem;
      font-weight: 600;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 3px 8px;
      border-radius: 99px;
      flex-shrink: 0;
    }
    .chunk-badge.pending   { background: rgba(255,255,255,0.05); color: var(--muted); }
    .chunk-badge.rendering { background: rgba(201,168,76,0.15); color: var(--gold); }
    .chunk-badge.done      { background: rgba(46,204,113,0.15); color: var(--green); }
    .chunk-badge.error     { background: rgba(231,76,60,0.15);  color: var(--red); }

    /* Batch done / error banner */
    .batch-result {
      margin-top: 16px;
      padding: 13px 16px;
      border-radius: 10px;
      font-size: 0.85rem;
      font-weight: 500;
      display: none;
      align-items: center;
      gap: 10px;
      animation: fadeUp 0.4s ease;
    }
    .batch-result.show { display: flex; }
    .batch-result.success {
      background: rgba(46,204,113,0.08);
      border: 1px solid rgba(46,204,113,0.25);
      color: var(--green);
    }
    .batch-result.partial {
      background: rgba(243,156,18,0.08);
      border: 1px solid rgba(243,156,18,0.25);
      color: var(--amber);
    }
    .batch-result.fail {
      background: rgba(231,76,60,0.08);
      border: 1px solid rgba(231,76,60,0.2);
      color: var(--red);
    }

    /* ── Footer ──────────────────────────────────────────────── */
    .card-divider { height: 1px; background: var(--border); margin: 0 28px; }
    .card-footer {
      padding: 12px 24px;
      font-size: 0.69rem;
      color: #3a3428;
      text-align: center;
      letter-spacing: 0.04em;
      line-height: 1.6;
    }

    @media (max-width: 480px) {
      .card-body  { padding: 22px 18px 18px; }
      .app-name   { font-size: 1.5rem; }
      .tab-btn    { font-size: 0.74rem; padding: 9px 10px; }
    }
  </style>
</head>
<body>

  <header class="header">
    <h1 class="app-name">Quran <span>Studio</span></h1>
    <p class="arabic-subtitle">مولد مقاطع القرآن</p>
    <div class="header-divider"></div>
  </header>

  <!-- ── Mode tabs ──────────────────────────────────────────── -->
  <nav class="tab-nav" role="tablist" aria-label="Mode">
    <button id="tab-single" class="tab-btn active" role="tab" aria-selected="true"
            onclick="switchTab('single')">
      🎬 Single Verse
    </button>
    <button id="tab-bulk" class="tab-btn" role="tab" aria-selected="false"
            onclick="switchTab('bulk')">
      📦 Bulk Creator
    </button>
  </nav>

  <main class="card" role="main">

    <!-- ══════════════════════════════════════════════════════════
         TAB 1 — Single Verse
    ══════════════════════════════════════════════════════════ -->
    <div id="panel-single" class="tab-panel active">
      <div class="card-body">

        <!-- Surah -->
        <div class="input-group">
          <label for="inp-surah">Surah Number <span style="color:#2a2018">(1–114)</span></label>
          <input type="number" id="inp-surah" value="2" min="1" max="114"
                 autocomplete="off" oninput="updateSurahHint()">
          <div id="surah-hint" class="surah-hint show">Al-Baqarah</div>
        </div>

        <!-- Start / End verse -->
        <div class="input-row">
          <div class="input-group">
            <label for="inp-start">Start Verse</label>
            <input type="number" id="inp-start" value="255" min="1" autocomplete="off">
          </div>
          <div class="input-group">
            <label for="inp-end">End Verse</label>
            <input type="number" id="inp-end" value="255" min="1" autocomplete="off">
          </div>
        </div>

        <!-- Orientation toggle -->
        <div>
          <label>Orientation</label>
          <div class="orientation-toggle" id="orient-toggle">
            <button id="btn-horizontal" class="btn-orient active" onclick="setOrientation('horizontal')">🖥️ Horizontal (16:9)</button>
            <button id="btn-vertical"   class="btn-orient"        onclick="setOrientation('vertical')"  >📱 Vertical (9:16)</button>
          </div>
        </div>

        <!-- Button -->
        <button id="gen-btn" class="btn-generate" onclick="startGenerate()">
          <div class="btn-spinner"></div>
          <span class="btn-label">Generate Video</span>
        </button>

        <!-- Status -->
        <div id="status-area" class="status-area">
          <div class="status-row">
            <div id="status-dot" class="status-dot"></div>
            <div id="status-msg" class="status-msg">Initializing…</div>
          </div>
          <div class="progress-wrap" id="progress-wrap" style="display:none">
            <div id="progress-bar" class="progress-bar"></div>
          </div>
          <button id="dl-btn" class="btn-download" onclick="downloadVideo()">↓ Download MP4</button>
        </div>

      </div>

      <div class="card-divider"></div>
      <div class="card-footer">
        Recitation: Sheikh Mishary Alafasy &nbsp;·&nbsp; Translation: Saheeh International<br>
        If start = end, generates a single verse video
      </div>
    </div><!-- /panel-single -->


    <!-- ══════════════════════════════════════════════════════════
         TAB 2 — Bulk Creator
    ══════════════════════════════════════════════════════════ -->
    <div id="panel-bulk" class="tab-panel">
      <div class="card-body">

        <p class="section-label">Set Up Your Batch</p>

        <!-- Surah dropdown -->
        <div class="input-group">
          <label for="bulk-surah">Which Surah?</label>
          <select id="bulk-surah" onchange="updateBulkSurahHint()"></select>
          <div id="bulk-surah-hint" class="surah-hint show">Al-Baqarah</div>
        </div>

        <!-- Verse range -->
        <div class="input-row">
          <div class="input-group">
            <label for="bulk-start">From Verse</label>
            <input type="number" id="bulk-start" value="1" min="1" autocomplete="off">
          </div>
          <div class="input-group">
            <label for="bulk-end">To Verse</label>
            <input type="number" id="bulk-end" value="10" min="1" autocomplete="off">
          </div>
        </div>

        <!-- Verses per video -->
        <div class="input-group">
          <label for="bulk-vpv">How many verses in each video?</label>
          <input type="number" id="bulk-vpv" value="1" min="1" autocomplete="off">
          <p class="field-hint" id="bulk-vpv-hint">Each video will contain 1 verse.</p>
        </div>

        <!-- Orientation -->
        <div>
          <label>Orientation</label>
          <div class="orientation-toggle">
            <button id="bulk-btn-h" class="btn-orient active" onclick="setBulkOrientation('horizontal')">🖥️ Horizontal (16:9)</button>
            <button id="bulk-btn-v" class="btn-orient"        onclick="setBulkOrientation('vertical')"  >📱 Vertical (9:16)</button>
          </div>
        </div>

        <!-- Big gold button -->
        <button id="bulk-gen-btn" class="btn-generate" onclick="startBulkGenerate()">
          <div class="btn-spinner"></div>
          <span class="btn-label">✦ Generate Bulk Videos</span>
        </button>

        <!-- ── Batch Progress Dashboard ── -->
        <div id="batch-dashboard" class="batch-dashboard">

          <div class="batch-header">
            <span class="batch-title">Batch Progress</span>
            <span class="batch-counter" id="batch-counter">—</span>
          </div>

          <div class="batch-overall-wrap">
            <div class="batch-overall-label">
              <span id="batch-overall-label-text">Getting started…</span>
              <span id="batch-pct-label">0%</span>
            </div>
            <div class="batch-progress-wrap">
              <div id="batch-progress-bar" class="batch-progress-bar"></div>
            </div>
          </div>

          <div class="chunk-list" id="chunk-list"></div>

          <div id="batch-result" class="batch-result"></div>

        </div><!-- /batch-dashboard -->

      </div>

      <div class="card-divider"></div>
      <div class="card-footer">
        Videos are saved inside a timestamped folder in your <strong style="color:#3a3428">output/</strong> directory.<br>
        Recitation: Sheikh Mishary Alafasy &nbsp;·&nbsp; Translation: Saheeh International
      </div>
    </div><!-- /panel-bulk -->

  </main><!-- /card -->

<script>
/* ═══════════════════════════════════════════════════════════════
   SURAH DATA
═══════════════════════════════════════════════════════════════ */
const SURAHS = {
  1:"Al-Fatihah",2:"Al-Baqarah",3:"Ali 'Imran",4:"An-Nisa",5:"Al-Ma'idah",
  6:"Al-An'am",7:"Al-A'raf",8:"Al-Anfal",9:"At-Tawbah",10:"Yunus",
  11:"Hud",12:"Yusuf",13:"Ar-Ra'd",14:"Ibrahim",15:"Al-Hijr",
  16:"An-Nahl",17:"Al-Isra",18:"Al-Kahf",19:"Maryam",20:"Ta-Ha",
  21:"Al-Anbya",22:"Al-Hajj",23:"Al-Mu'minun",24:"An-Nur",25:"Al-Furqan",
  26:"Ash-Shu'ara",27:"An-Naml",28:"Al-Qasas",29:"Al-'Ankabut",30:"Ar-Rum",
  31:"Luqman",32:"As-Sajdah",33:"Al-Ahzab",34:"Saba",35:"Fatir",
  36:"Ya-Sin",37:"As-Saffat",38:"Sad",39:"Az-Zumar",40:"Ghafir",
  41:"Fussilat",42:"Ash-Shura",43:"Az-Zukhruf",44:"Ad-Dukhan",45:"Al-Jathiyah",
  46:"Al-Ahqaf",47:"Muhammad",48:"Al-Fath",49:"Al-Hujurat",50:"Qaf",
  51:"Adh-Dhariyat",52:"At-Tur",53:"An-Najm",54:"Al-Qamar",55:"Ar-Rahman",
  56:"Al-Waqi'ah",57:"Al-Hadid",58:"Al-Mujadila",59:"Al-Hashr",60:"Al-Mumtahanah",
  61:"As-Saf",62:"Al-Jumu'ah",63:"Al-Munafiqun",64:"At-Taghabun",65:"At-Talaq",
  66:"At-Tahrim",67:"Al-Mulk",68:"Al-Qalam",69:"Al-Haqqah",70:"Al-Ma'arij",
  71:"Nuh",72:"Al-Jinn",73:"Al-Muzzammil",74:"Al-Muddaththir",75:"Al-Qiyamah",
  76:"Al-Insan",77:"Al-Mursalat",78:"An-Naba",79:"An-Nazi'at",80:"'Abasa",
  81:"At-Takwir",82:"Al-Infitar",83:"Al-Mutaffifin",84:"Al-Inshiqaq",85:"Al-Buruj",
  86:"At-Tariq",87:"Al-A'la",88:"Al-Ghashiyah",89:"Al-Fajr",90:"Al-Balad",
  91:"Ash-Shams",92:"Al-Layl",93:"Ad-Duha",94:"Ash-Sharh",95:"At-Tin",
  96:"Al-'Alaq",97:"Al-Qadr",98:"Al-Bayyinah",99:"Az-Zalzalah",100:"Al-'Adiyat",
  101:"Al-Qari'ah",102:"At-Takathur",103:"Al-'Asr",104:"Al-Humazah",105:"Al-Fil",
  106:"Quraysh",107:"Al-Ma'un",108:"Al-Kawthar",109:"Al-Kafirun",110:"An-Nasr",
  111:"Al-Masad",112:"Al-Ikhlas",113:"Al-Falaq",114:"An-Nas"
};

/* ═══════════════════════════════════════════════════════════════
   TAB SWITCHING
═══════════════════════════════════════════════════════════════ */
function switchTab(tab) {
  ['single','bulk'].forEach(t => {
    document.getElementById(`tab-${t}`).classList.toggle('active', t === tab);
    document.getElementById(`panel-${t}`).classList.toggle('active', t === tab);
    document.getElementById(`tab-${t}`).setAttribute('aria-selected', t === tab);
  });
}

/* ═══════════════════════════════════════════════════════════════
   SINGLE VIDEO — existing logic (unchanged)
═══════════════════════════════════════════════════════════════ */
let jobId = null;
let pollTimer = null;
let fakeProgressTimer = null;
let realPercentage = 0;
let visualPercentage = 0;
let lastSurah = 2, lastStart = 255, lastEnd = 255;
let selectedOrientation = 'horizontal';

function setOrientation(val) {
  selectedOrientation = val;
  document.getElementById('btn-horizontal').classList.toggle('active', val === 'horizontal');
  document.getElementById('btn-vertical').classList.toggle('active', val === 'vertical');
}

function updateSurahHint() {
  const n    = parseInt(document.getElementById('inp-surah').value, 10);
  const hint = document.getElementById('surah-hint');
  const name = SURAHS[n];
  hint.textContent = name || '';
  hint.classList.toggle('show', !!name);
}

async function startGenerate() {
  const surah = +document.getElementById('inp-surah').value;
  const start = +document.getElementById('inp-start').value;
  const end   = +document.getElementById('inp-end').value;
  if (!surah || !start || !end) return;
  if (start > end) { alert('Start verse must be ≤ end verse.'); return; }

  lastSurah = surah; lastStart = start; lastEnd = end;

  if (pollTimer) clearInterval(pollTimer);
  if (fakeProgressTimer) clearInterval(fakeProgressTimer);
  jobId = null;
  realPercentage = 0;
  visualPercentage = 0;
  document.getElementById('status-area').classList.add('visible');
  document.getElementById('status-dot').className = 'status-dot';
  document.getElementById('status-msg').className  = 'status-msg';
  document.getElementById('status-msg').textContent = 'Initializing…';
  document.getElementById('dl-btn').classList.remove('visible');
  document.getElementById('progress-wrap').style.display = 'block';
  document.getElementById('progress-bar').style.width = '0%';
  document.getElementById('gen-btn').disabled = true;
  document.getElementById('gen-btn').classList.add('loading');

  fakeProgressTimer = setInterval(() => {
    let targetCap = Math.min(99, realPercentage + 24);
    if (visualPercentage < targetCap) {
      visualPercentage += 0.2;
      document.getElementById('progress-bar').style.width = visualPercentage + '%';
    }
  }, 50);

  const isRange = start !== end;

  try {
    let res;
    if (isRange) {
      res = await fetch('/generate-range', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ surah, start_verse: start, end_verse: end, orientation: selectedOrientation })
      });
    } else {
      res = await fetch('/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ surah, verse: start, orientation: selectedOrientation })
      });
    }
    const data = await res.json();
    if (!data.job_id) throw new Error('No job_id returned');
    jobId = data.job_id;
    pollTimer = setInterval(pollStatus, 2000);
  } catch (err) {
    showError('Connection error — is the server running?');
    document.getElementById('gen-btn').disabled = false;
    document.getElementById('gen-btn').classList.remove('loading');
  }
}

async function pollStatus() {
  if (!jobId) return;
  try {
    const res  = await fetch(`/status/${jobId}`);
    const data = await res.json();
    const msg  = document.getElementById('status-msg');

    if (data.status === 'pending') {
      msg.textContent = 'Queued — starting shortly…';
      realPercentage = 0;
    } else if (data.status === 'rendering') {
      msg.textContent = data.step || data.message || 'Rendering…';
      if (data.percentage !== undefined) {
        realPercentage = data.percentage;
        if (visualPercentage < realPercentage) visualPercentage = realPercentage;
      } else if (data.total_verses > 0) {
        realPercentage = Math.round((data.verse_num / data.total_verses) * 100);
        if (visualPercentage < realPercentage) visualPercentage = realPercentage;
      }
    } else if (data.status === 'done') {
      clearInterval(pollTimer);
      if (fakeProgressTimer) clearInterval(fakeProgressTimer);
      msg.textContent = data.step || '✓ Render complete';
      document.getElementById('status-dot').className = 'status-dot done';
      document.getElementById('gen-btn').disabled = false;
      document.getElementById('gen-btn').classList.remove('loading');
      visualPercentage = 100;
      document.getElementById('progress-bar').style.width = '100%';

      const name = SURAHS[lastSurah] || `Surah ${lastSurah}`;
      const label = lastStart === lastEnd
        ? `↓  ${name} — Verse ${lastStart}.mp4`
        : `↓  ${name} — Verses ${lastStart}–${lastEnd}.mp4`;
      const dlBtn = document.getElementById('dl-btn');
      dlBtn.textContent = label;
      dlBtn.classList.add('visible');
    } else if (data.status === 'error') {
      clearInterval(pollTimer);
      if (fakeProgressTimer) clearInterval(fakeProgressTimer);
      showError(data.message || 'Render failed');
      document.getElementById('gen-btn').disabled = false;
      document.getElementById('gen-btn').classList.remove('loading');
    }
  } catch (_) {}
}

function downloadVideo() {
  if (!jobId) return;
  const a = document.createElement('a');
  a.href = `/download/${jobId}`;
  a.download = '';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

function showError(text) {
  document.getElementById('status-area').classList.add('visible');
  const msg = document.getElementById('status-msg');
  msg.className = 'status-msg error';
  msg.textContent = text;
  document.getElementById('status-dot').className = 'status-dot error';
}

/* ═══════════════════════════════════════════════════════════════
   BULK CREATOR
═══════════════════════════════════════════════════════════════ */
let bulkOrientation = 'horizontal';
let batchId         = null;
let bulkPollTimer   = null;
let bulkChunkCount  = 0; // how many chunk rows we've built in the DOM

/* Populate surah dropdown */
(function buildSurahDropdown() {
  const sel = document.getElementById('bulk-surah');
  for (let i = 1; i <= 114; i++) {
    const opt = document.createElement('option');
    opt.value = i;
    opt.textContent = `${i}. ${SURAHS[i]}`;
    if (i === 2) opt.selected = true;
    sel.appendChild(opt);
  }
})();

/* Live hint — verses-per-video */
document.getElementById('bulk-vpv').addEventListener('input', updateVpvHint);
function updateVpvHint() {
  const vpv   = +document.getElementById('bulk-vpv').value || 1;
  const hint  = document.getElementById('bulk-vpv-hint');
  hint.textContent = vpv === 1
    ? 'Each video will contain 1 verse.'
    : `Each video will contain ${vpv} verses.`;
}

function updateBulkSurahHint() {
  const n    = +document.getElementById('bulk-surah').value;
  const hint = document.getElementById('bulk-surah-hint');
  hint.textContent = SURAHS[n] || '';
  hint.classList.toggle('show', !!SURAHS[n]);
}

function setBulkOrientation(val) {
  bulkOrientation = val;
  document.getElementById('bulk-btn-h').classList.toggle('active', val === 'horizontal');
  document.getElementById('bulk-btn-v').classList.toggle('active', val === 'vertical');
}

/* ── Pre-build chunk rows from a chunks array ── */
function buildChunkRows(chunks, surahName) {
  const list = document.getElementById('chunk-list');
  list.innerHTML = '';
  bulkChunkCount = chunks.length;
  chunks.forEach((c, i) => {
    const videoNum  = i + 1;
    const verseLabel = c.start === c.end ? `Verse ${c.start}` : `Verses ${c.start}–${c.end}`;
    const row = document.createElement('div');
    row.className = 'chunk-item';
    row.id = `chunk-row-${i}`;
    row.innerHTML = `
      <div class="chunk-icon pending" id="chunk-icon-${i}">
        <span id="chunk-icon-inner-${i}">·</span>
      </div>
      <div class="chunk-info">
        <div class="chunk-name">Video ${videoNum} — ${verseLabel}</div>
        <div class="chunk-status-text" id="chunk-status-${i}">Waiting in line…</div>
      </div>
      <span class="chunk-badge pending" id="chunk-badge-${i}">Queued</span>
    `;
    list.appendChild(row);
  });
}

/* ── Update one chunk row from backend chunk data ── */
function updateChunkRow(i, chunk) {
  const row    = document.getElementById(`chunk-row-${i}`);
  const icon   = document.getElementById(`chunk-icon-${i}`);
  const inner  = document.getElementById(`chunk-icon-inner-${i}`);
  const status = document.getElementById(`chunk-status-${i}`);
  const badge  = document.getElementById(`chunk-badge-${i}`);
  if (!row) return;

  const s = chunk.status;

  // Row highlight
  row.classList.remove('is-rendering','is-done','is-error');
  if (s === 'rendering') row.classList.add('is-rendering');
  else if (s === 'done')  row.classList.add('is-done');
  else if (s === 'error') row.classList.add('is-error');

  // Icon
  icon.className = `chunk-icon ${s === 'pending' ? 'pending' : s}`;
  if (s === 'pending')   { inner.textContent = '·'; inner.className = ''; }
  else if (s === 'rendering') {
    inner.outerHTML = `<div class="chunk-spin" id="chunk-icon-inner-${i}"></div>`;
  }
  else if (s === 'done')  { document.getElementById(`chunk-icon-inner-${i}`).outerHTML = `<span id="chunk-icon-inner-${i}">✓</span>`; }
  else if (s === 'error') { document.getElementById(`chunk-icon-inner-${i}`).outerHTML = `<span id="chunk-icon-inner-${i}">✕</span>`; }

  // Status text
  status.className = `chunk-status-text ${s}`;
  if (s === 'pending')   status.textContent = 'Waiting in line…';
  else if (s === 'rendering') {
    const stepText = chunk.step ? chunk.step : 'Creating…';
    const pct = chunk.percentage !== undefined ? ` (${chunk.percentage}%)` : '';
    status.textContent = stepText + pct;
  }
  else if (s === 'done')  status.textContent = 'Completed ✓';
  else if (s === 'error') status.textContent = chunk.error ? `Error: ${chunk.error.slice(0,60)}` : 'Failed';

  // Badge
  badge.className = `chunk-badge ${s}`;
  const BADGE_LABELS = { pending:'Queued', rendering:'Creating…', done:'Done', error:'Failed' };
  badge.textContent = BADGE_LABELS[s] || s;
}

/* ── Update overall progress ── */
function updateBatchOverall(data) {
  const total     = data.total     || bulkChunkCount || 1;
  const completed = data.completed || 0;
  const failed    = data.failed    || 0;
  const done      = completed + failed;
  const pct       = Math.round((done / total) * 100);

  document.getElementById('batch-counter').innerHTML =
    `<strong>${completed}</strong> / ${total} done`;
  document.getElementById('batch-pct-label').textContent = pct + '%';
  document.getElementById('batch-progress-bar').style.width = pct + '%';

  if (data.status === 'rendering' && data.current_chunk) {
    const cc = data.current_chunk;
    const verseLabel = cc.start === cc.end ? `verse ${cc.start}` : `verses ${cc.start}–${cc.end}`;
    document.getElementById('batch-overall-label-text').textContent =
      `Working on video ${cc.index} of ${total} (${verseLabel})…`;
  } else if (data.status === 'done' || data.status === 'done_with_errors') {
    document.getElementById('batch-overall-label-text').textContent =
      data.status === 'done' ? 'All videos completed!' : `Finished with ${failed} error(s).`;
  }
}

/* ── Show final result banner ── */
function showBatchResult(data) {
  const el    = document.getElementById('batch-result');
  const total = data.total || 1;
  const fail  = data.failed || 0;
  const done  = data.completed || 0;

  el.classList.remove('success','partial','fail');
  el.classList.add('show');

  if (fail === 0) {
    el.className = 'batch-result show success';
    el.innerHTML = `<span>🎉</span> All ${done} video${done > 1 ? 's' : ''} generated successfully! Check your <strong>output/bulk_batch_…</strong> folder.`;
  } else if (done > 0) {
    el.className = 'batch-result show partial';
    el.innerHTML = `<span>⚠️</span> ${done} video${done > 1 ? 's' : ''} completed, ${fail} failed. Check your <strong>output/bulk_batch_…</strong> folder for the successful ones.`;
  } else {
    el.className = 'batch-result show fail';
    el.innerHTML = `<span>❌</span> All ${fail} video${fail > 1 ? 's' : ''} failed to generate. Please check the server logs.`;
  }
}

/* ── Poll bulk status ── */
async function pollBulkStatus() {
  if (!batchId) return;
  try {
    const res  = await fetch(`/bulk-status/${batchId}`);
    const data = await res.json();

    updateBatchOverall(data);

    // Update each chunk row
    if (data.chunks) {
      data.chunks.forEach((c, i) => updateChunkRow(i, c));
    }

    // Terminal states
    if (data.status === 'done' || data.status === 'done_with_errors') {
      clearInterval(bulkPollTimer);
      bulkPollTimer = null;
      showBatchResult(data);
      document.getElementById('bulk-gen-btn').disabled = false;
      document.getElementById('bulk-gen-btn').classList.remove('loading');
    }
  } catch (_) {}
}

/* ── Kick off bulk generation ── */
async function startBulkGenerate() {
  const surah = +document.getElementById('bulk-surah').value;
  const start = +document.getElementById('bulk-start').value;
  const end   = +document.getElementById('bulk-end').value;
  const vpv   = +document.getElementById('bulk-vpv').value || 1;
  const surahName = SURAHS[surah] || `Surah ${surah}`;

  if (!surah || !start || !end) { alert('Please fill in all fields.'); return; }
  if (start > end) { alert('From Verse must be ≤ To Verse.'); return; }
  if (vpv < 1)     { alert('Verses per video must be at least 1.'); return; }

  // Stop previous poll if any
  if (bulkPollTimer) { clearInterval(bulkPollTimer); bulkPollTimer = null; }
  batchId = null;

  // Pre-compute chunk list so we can draw rows immediately
  const preChunks = [];
  for (let v = start; v <= end; ) {
    const chunkEnd = Math.min(v + vpv - 1, end);
    preChunks.push({ start: v, end: chunkEnd, status: 'pending' });
    v = chunkEnd + 1;
  }

  // Reset dashboard
  const dashboard = document.getElementById('batch-dashboard');
  dashboard.classList.add('visible');
  document.getElementById('batch-result').classList.remove('show');
  document.getElementById('batch-progress-bar').style.width = '0%';
  document.getElementById('batch-pct-label').textContent = '0%';
  document.getElementById('batch-counter').innerHTML = `<strong>0</strong> / ${preChunks.length} done`;
  document.getElementById('batch-overall-label-text').textContent = 'Getting started…';
  buildChunkRows(preChunks, surahName);

  // Disable button
  document.getElementById('bulk-gen-btn').disabled = true;
  document.getElementById('bulk-gen-btn').classList.add('loading');

  // POST to backend
  try {
    const res = await fetch('/generate-bulk', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        surah,
        start_verse: start,
        end_verse: end,
        verses_per_video: vpv,
        orientation: bulkOrientation
      })
    });
    const data = await res.json();
    if (!data.batch_id) throw new Error('No batch_id returned');
    batchId = data.batch_id;
    bulkPollTimer = setInterval(pollBulkStatus, 2000);
  } catch (err) {
    document.getElementById('batch-result').className = 'batch-result show fail';
    document.getElementById('batch-result').innerHTML =
      `<span>❌</span> Could not connect to the server. Is it running?`;
    document.getElementById('bulk-gen-btn').disabled = false;
    document.getElementById('bulk-gen-btn').classList.remove('loading');
  }
}
</script>
</body>
</html>

```
---

## .gitignore
```
# Environment & secrets
.env
*.env

# Python
__pycache__/
*.pyc
*.pyo
.venv/
venv/

# Audio files (large)
*.mp3
*.wav

# Output videos
output/

# Temp files
temp_assets/
temp_verse_audio.mp3
concat.txt


# OS files
.DS_Store
Thumbs.db

```
---

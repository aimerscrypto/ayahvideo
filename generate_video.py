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

def fix_fusions(text):
    """Insert spaces before common prepositions/articles/pronouns that get fused by the LLM."""
    patterns = [
        (r'(?<=[a-z])(to)(the|a|an|him|her|it|us|them|you|me)\b', r'\1 \2'),
        (r'(?<=[a-z])(of)(the|a|an|him|her|it|us|them|you|me)\b', r'\1 \2'),
        (r'(?<=[a-z])(in)(the|a|an|him|her|it|us|them|you|me)\b', r'\1 \2'),
        (r'(?<=[a-z])(on)(the|a|an|him|her|it|us|them|you|me)\b', r'\1 \2'),
        (r'(?<=[a-z])(upon)(whom|which|them|him|her|it|us|you)\b', r'\1 \2'),
        (r'(?<=[a-z])(those)(who|whom|which|that)\b', r'\1 \2'),
        (r'(?<=[a-z])(with)(him|her|it|us|them|you|me|whom)\b', r'\1 \2'),
    ]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return re.sub(r' +', ' ', text).strip()

def clean_english_text(text):
    text = re.sub(r'<[^>]+>', ' ', text)   # replace tags with space
    text = re.sub(r'\s+', ' ', text).strip()  # collapse all whitespace (incl. newlines) immediately so no downstream fusion
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
    text = fix_fusions(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

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

def get_llm_split(english_text, num_chunks, arabic_chunks=None):
    def fallback_split(text, chunks):
        print("Using rule-based fallback splitting...")
        sentences = re.split(r'(?<=[.,;])\s+', text.strip())
        sentences = [s for s in sentences if s]
        if not sentences:
            return [""] * chunks
        result = []
        k, m = divmod(len(sentences), chunks)
        idx = 0
        for i in range(chunks):
            bucket_size = k + 1 if i < m else k
            if bucket_size == 0 and len(sentences) < chunks and idx < len(sentences):
                bucket_size = 1
            if idx < len(sentences):
                result.append(" ".join(sentences[idx : idx+bucket_size]))
                idx += bucket_size
            else:
                result.append("")
        return result

    # Build segment list for the prompt
    if arabic_chunks and len(arabic_chunks) == num_chunks:
        segments_str = "\n".join(
            f"Segment {i+1}: {arabic_chunks[i]}" for i in range(num_chunks)
        )
    else:
        segments_str = "\n".join(f"Segment {i+1}: (Arabic text unavailable)" for i in range(num_chunks))

    prompt = f"""I have a Quran verse split into {num_chunks} screen segments. Here are the Arabic words in each segment:
{segments_str}

Full English translation: "{english_text}"

Split the English translation into exactly {num_chunks} parts where each part matches the meaning of its corresponding Arabic segment. You must use the EXACT words from the translation provided. Do not paraphrase, rephrase, or change any words. Only split the text into {num_chunks} parts at natural boundaries. Return ONLY a JSON array of {num_chunks} strings. No markdown, no code blocks, no explanation."""

    OPENROUTER_MODELS = [
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "deepseek/deepseek-r1:free",
        "openrouter/auto",
    ]

    def fix_llm_part(p):
        p = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', p)  # camelCase fix
        p = re.sub(r'\b(no)(god|one|thing|where|body|how)\b', r'\1 \2', p)  # no+word joins
        p = p.replace('\u2011', '-')  # non-breaking hyphen
        p = p.replace('\u2012', '-')  # figure dash
        p = p.replace('\u2013', '-')  # en dash
        p = p.replace('\u2014', '-')  # em dash
        p = p.replace('\u2015', '-')  # horizontal bar
        p = fix_fusions(p)
        p = re.sub(r'\s+', ' ', p).strip()
        return p

    def parse_and_return(res_text, provider_label):
        if res_text.startswith("```json"):
            res_text = res_text[7:-3]
        elif res_text.startswith("```"):
            res_text = res_text[3:-3]
        parts = json.loads(res_text.strip())
        parts = [fix_llm_part(p) for p in parts]
        if len(parts) == num_chunks:
            print(f"  [PROVIDER] {provider_label}")
            return parts
        else:
            print(f"  LLM returned {len(parts)} chunks instead of {num_chunks}. Padding/truncating...")
            while len(parts) < num_chunks: parts.append("")
            print(f"  [PROVIDER] {provider_label}")
            return parts[:num_chunks]

    # ── 1. Try OpenRouter models ──────────────────────────────────────────────
    keys = [
        os.environ.get("OPENROUTER_API_KEY"),
        os.environ.get("OPENROUTER_API_KEY_2"),
        os.environ.get("OPENROUTER_API_KEY_3")
    ]
    valid_keys = [k for k in keys if k]

    if valid_keys:
        for model_idx, model in enumerate(OPENROUTER_MODELS):
            print(f"Trying model {model_idx + 1}/{len(OPENROUTER_MODELS)}: {model}")
            
            for key_idx, current_key in enumerate(valid_keys):
                got_429 = False
                
                for attempt in range(3):
                    try:
                        response = requests.post(
                            "https://openrouter.ai/api/v1/chat/completions",
                            headers={"Authorization": f"Bearer {current_key}"},
                            json={
                                "model": model,
                                "messages": [{"role": "user", "content": prompt}]
                            },
                            timeout=60
                        )

                        if response.status_code == 429:
                            print(f"    Rate limited (429) on {model} with key {key_idx + 1}. Moving to next key.")
                            got_429 = True
                            break  # skip to next key

                        if response.status_code == 200:
                            resp_json = response.json()
                            if "choices" in resp_json and len(resp_json["choices"]) > 0:
                                res_text = resp_json["choices"][0]["message"]["content"].strip()
                                try:
                                    return parse_and_return(res_text, f"OpenRouter/{model}")
                                except Exception as pe:
                                    print(f"    Parse error: {pe}")
                            else:
                                print("    Error: 'choices' missing from response.")
                        else:
                            print(f"    OpenRouter returned status {response.status_code}")

                    except Exception as e:
                        print(f"    Error calling LLM: {e}")

                    if attempt < 2:
                        print("    Waiting 5 seconds before retrying...")
                        time.sleep(5)
                
                if got_429:
                    continue  # try next key
                else:
                    break  # if it wasn't a 429, we move to the next model, not the next key.

        print("All OpenRouter models exhausted.")
    else:
        print("No OPENROUTER_API_KEY variables set — skipping OpenRouter.")

    # ── 2. Rule-based fallback ────────────────────────────────────────────────
    print("[PROVIDER] rule-based fallback")
    return fallback_split(english_text, num_chunks)



def render_image(arabic_text, english_text, output_img, ar_font_path="UthmanicHafs.ttf", en_font_path="Poppins-Regular.ttf"):
    W, H = 1920, 1080
    img = Image.new('RGB', (W, H), color='black')
    draw = ImageDraw.Draw(img)

    display_arabic = get_arabic_display(arabic_text)

    ar_size = 55
    ar_font = ImageFont.truetype(ar_font_path, ar_size)
    while ar_font.getlength(display_arabic) > 1400 and ar_size > 20:
        ar_size -= 2
        ar_font = ImageFont.truetype(ar_font_path, ar_size)

    ar_width = ar_font.getlength(display_arabic)
    ar_bbox = ar_font.getbbox(display_arabic)
    ar_height = (ar_bbox[3] - ar_bbox[1]) + 20

    en_size = 38
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

    wrapped_en = wrap_text_pixels(english_text, en_font, 1400)
    while len(wrapped_en) > 3 and en_size > 28:
        en_size -= 2
        en_font = ImageFont.truetype(en_font_path, en_size)
        wrapped_en = wrap_text_pixels(english_text, en_font, 1400)

    if len(wrapped_en) > 3:
        wrapped_en = wrapped_en[:3]
        last_line = wrapped_en[2]
        while en_font.getlength(last_line + "...") > 1400 and len(last_line) > 0:
            last_line = last_line[:-1]
        wrapped_en[2] = last_line.strip() + "..."

    line_height = 48
    gap_between_ar_en = 40

    num_lines = len(wrapped_en) if wrapped_en else 0
    english_block_height = num_lines * line_height
    total_height = ar_height + gap_between_ar_en + english_block_height

    start_y = (1080 - total_height) // 2
    start_y += 60

    ar_x = (W - ar_width) // 2
    draw.text((ar_x, start_y), display_arabic, font=ar_font, fill="white")

    current_y = start_y + ar_height + gap_between_ar_en
    for line in wrapped_en:
        line_w = en_font.getlength(line)
        line_x = (W - line_w) // 2
        draw.text((line_x, current_y), line, font=en_font, fill="white")
        current_y += line_height

    img.save(output_img)

def generate_verse_video(surah, verse):
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
    font = ImageFont.truetype(ar_font_path, 55)
    max_width = 1400

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

    # Calculate chunk durations using absolute timestamps relative to verse start
    # segments store absolute ms positions within the surah; subtract verse_start_ms to get relative offsets
    chunks = []
    for i, c in enumerate(raw_chunks):
        # Start of this chunk relative to verse start
        chunk_start_abs = c[0]["start"] if i > 0 else verse_start_ms
        # End = start of next chunk's first word (or end of verse for last chunk)
        chunk_end_abs = raw_chunks[i+1][0]["start"] if i < len(raw_chunks)-1 else verse_end_ms
        duration_s = (chunk_end_abs - chunk_start_abs) / 1000.0

        arabic_str = " ".join([w["text"] for w in c])
        chunks.append({
            "arabic": arabic_str,
            "duration": duration_s
        })

    # Fetch English splits — pass Arabic words per chunk for better alignment
    arabic_chunks = [c["arabic"] for c in chunks]
    english_parts = get_llm_split(english_text, len(chunks), arabic_chunks)

    print("\n--- CHUNK MAPPING ---")
    for i, c in enumerate(chunks):
        print(f"Chunk {i}:")
        print(f"  Arabic:  {c['arabic']}")
        print(f"  English: {english_parts[i]}")
        print(f"  Duration: {c['duration']:.2f}s")
    print("---------------------\n")

    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    temp_dir = "temp_assets"
    os.makedirs(temp_dir, exist_ok=True)

    # Download per-verse audio
    temp_audio = os.path.join(temp_dir, "temp_verse_audio.mp3")
    download_verse_audio(surah, verse, temp_audio)

    # Generate frame images and concat file
    print("Generating frames...")
    concat_file_path = os.path.join(temp_dir, "concat.txt")
    with open(concat_file_path, "w", encoding="utf-8") as f:
        for i, c in enumerate(chunks):
            img_path = os.path.join(temp_dir, f"chunk_{i}.png")
            render_image(c["arabic"], english_parts[i], img_path, ar_font_path, "Poppins-Regular.ttf")
            f.write(f"file '{os.path.basename(img_path)}'\n")
            f.write(f"duration {c['duration']}\n")

        # concat demuxer requires the last file repeated without a duration
        safe_last = f"chunk_{len(chunks)-1}.png"
        f.write(f"file '{safe_last}'\n")

    output_filename = os.path.join(output_dir, f"verse_{surah}_{verse}.mp4")

    # FFmpeg: concat images + per-verse audio
    print("Rendering final concatenated video...")
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

def generate_range_video(surah, start_verse, end_verse, progress_callback=None):
    """Render each verse in [start_verse, end_verse] individually then concatenate into one MP4."""
    download_fonts()
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    range_temp_dir = os.path.join(output_dir, f"range_temp_{surah}_{start_verse}_{end_verse}")
    os.makedirs(range_temp_dir, exist_ok=True)

    verse_files = []
    total_verses = end_verse - start_verse + 1

    for i, verse in enumerate(range(start_verse, end_verse + 1)):
        verse_num = i + 1
        if progress_callback:
            progress_callback(verse_num, total_verses, verse)
        print(f"\n=== Rendering verse {surah}:{verse} ({verse_num}/{total_verses}) ===")
        try:
            verse_output = generate_verse_video(surah, verse)
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

    final_output = os.path.join(output_dir, f"range_{surah}_{start_verse}_{end_verse}.mp4")
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
    generate_verse_video(2, 255)


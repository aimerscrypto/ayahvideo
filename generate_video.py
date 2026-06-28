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


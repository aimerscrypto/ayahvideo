# Ayah Video

> Turn Quranic verses into stunning short videos in seconds

[![Live Demo](https://img.shields.io/badge/Live%20Demo-ayahvideo.app-blueviolet?style=for-the-badge&logo=vercel)](https://ayahvideo.app)
[![Tech Stack](https://img.shields.io/badge/Stack-FastAPI%20%7C%20FFmpeg%20%7C%20Fireworks-blue?style=for-the-badge)](#tech-stack)

**Ayah Video** is a production-grade SaaS engine designed to dynamically transform sacred Quranic verses into highly engaging, cinematic short-form videos. Engineered for speed and precision, it utilizes AI to match user intent with contextually rich verses, applies meticulous layout engines to render Harakat-perfect Arabic calligraphy, and aligns precise audio recitations for seamless playback.

---

## ✨ Features

*   **🧠 AI-Powered Verse Discovery:** Describe any theme, feeling, or emotion (e.g., "patience during hardship" or "gratitude"), and the engine selects the perfect matching Ayah.
*   **✍️ Calibrated Arabic Rendering:** Pixel-perfect rendering of Arabic text with full Harakat and translations, dynamically wrapped to preserve calligraphic elegance using Amiri fonts.
*   **🎙️ Synchronized Recitation Audio:** Features audio synchronization with high-quality recitations (Sheikh Alafasy) down to the millisecond.
*   **🎬 Cinematic Video Synthesis:** Blends audio, text layers, and dynamic shadows over cinematic background loops using hardware-accelerated processing.
*   **⚡ High-Throughput Bulk Generation:** Scalable processing queues designed to generate batches of videos concurrently.
*   **📥 Instant High-Definition Downloads:** Get optimized MP4 exports ready for distribution on TikTok, Instagram Reels, or YouTube Shorts immediately.

---

## 🛠️ How It Works

```mermaid
graph LR
    A[User Theme/Emotion] --> B[AI Verse Discovery]
    B --> C[Calligraphy & Text Layout]
    C --> D[Audio Alignment Engine]
    D --> E[FFmpeg Synthesis]
    E --> F[HD MP4 Exported]
```

1.  **Input:** User describes a theme, emotion, or specific surah/ayah.
2.  **Analyze & Fetch:** AI discovers the most contextually relevant verse and retrieves authentic Arabic text, translation, and recitation audio.
3.  **Layout:** The rendering pipeline wraps the Arabic script, maintaining Harakat structure.
4.  **Sync:** Timecodes are mapped to match the audio recitation exactly.
5.  **Compile:** The engine overlay-renders text onto high-definition background loops, exporting web-optimized MP4 files.

---

## 💻 Tech Stack

*   **Backend Framework:** [FastAPI](https://fastapi.tiangolo.com/) — High-performance, asynchronous web server.
*   **Media Processing:** [FFmpeg](https://ffmpeg.org/) & [Pillow](https://python-pillow.org/) — Hardware-accelerated video synthesis, layer blending, and text rasterization.
*   **Artificial Intelligence:** [Fireworks AI](https://fireworks.ai/) (`minimax-m3` on AMD MI300X accelerators) — Ultra-low latency LLM inference for verse matching.
*   **Storage & CDN:** [Cloudflare R2](https://www.cloudflare.com/developer-platform/products/r2/) — S3-compatible, zero-egress cost object storage.
*   **Hosting:** [Railway](https://railway.app/) — Containerized auto-scaling deployment.

---

## ⚙️ Environment Variables

Configure the following environment variables in your `.env` file. Refer to [.env.example](file:///c:/Users/NAC/Desktop/projects/quran%20automation/.env.example) for baseline values:

| Variable Name | Required | Description | Default / Example |
| :--- | :--- | :--- | :--- |
| `FIREWORKS_API_KEY` | **Yes** | API key for Fireworks AI. Used for verse discovery and alignment models. | `your_fireworks_api_key_here` |
| `OPENROUTER_API_KEY` | **Yes** | Primary API Key for OpenRouter. Used for verse splitting and translation alignment. | `your_openrouter_api_key_here` |
| `OPENROUTER_API_KEY_2` | No | Secondary backup key for OpenRouter to prevent rate limits. | `your_openrouter_api_key_2_here` |
| `OPENROUTER_API_KEY_3` | No | Tertiary backup key for OpenRouter. | `your_openrouter_api_key_3_here` |
| `OPENROUTER_API_KEY_4` | No | Quaternary backup key for OpenRouter. | `your_openrouter_api_key_4_here` |
| `BG_VIDEO_URL` | No | Custom background video loop URL (must be direct MP4). | `https://pub-0a47df772c2d4d2e838dad7de6d2b237.r2.dev/bg.mp4` |

---

## 🚀 Local Setup

Follow these steps to run the development environment locally:

### 1. Clone the Repository
```bash
git clone https://github.com/your-username/ayah-video.git
cd quran-automation
```

### 2. Configure Environment Variables
Copy the template `.env.example` file and populate it with your API keys:
```bash
cp .env.example .env
```

### 3. Install Dependencies
Ensure you have `FFmpeg` installed on your host system. Then install Python dependencies:
```bash
pip install -r requirements.txt
```

### 4. Run the Application
Start the local FastAPI development server:
```bash
uvicorn app:app --reload
```
Once started, open [http://localhost:8000](http://localhost:8000) in your browser.

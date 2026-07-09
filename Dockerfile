FROM python:3.11-slim

# Install system dependencies (ffmpeg, curl for downloading fonts, and clean up apt cache)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download fonts at build time to prevent dynamic runtime downloads
# 1. Poppins-Regular.ttf
RUN curl -L -o Poppins-Regular.ttf "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Regular.ttf"

# 2. UthmanicHafs.ttf (Try the primary URL; fallback to the secondary URL if the primary fails)
RUN curl -L -f -o UthmanicHafs.ttf "https://github.com/mustafa0x/qpc-fonts/raw/master/QCF_BSML.TTF" || \
    curl -L -f -o UthmanicHafs.ttf "https://www.noor-book.com/fonts/UthmanicHafs1Ver18.ttf"

# Copy the rest of the application code
COPY . .

# Ensure output/ and temp_assets/ directories exist
RUN mkdir -p output temp_assets

# Expose port 8000
EXPOSE 8000

# Start command
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.11-slim

# Install system dependencies (ffmpeg and clean up apt cache)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libraqm0 \
    libfribidi0 \
    libharfbuzz0b \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy fonts from repository
COPY Poppins-Regular.ttf UthmanicHafs.ttf ./

# Copy the rest of the application code
COPY . .

# Ensure output/ and temp_assets/ directories exist
RUN mkdir -p output temp_assets

# Expose port 8000
EXPOSE 8000

# Start command
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

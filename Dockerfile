FROM python:3.9-slim-bullseye

# Set timezone to KST (Korea Standard Time)
ENV TZ=Asia/Seoul
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# Install system dependencies if needed (for Pillow/Fonts)
RUN apt-get update && apt-get install -y \
    libjpeg-dev \
    zlib1g-dev \
    fonts-nanum \
    libxrender1 \
    libxext6 \
    libfontconfig1 \
    wget \
    xfonts-75dpi \
    xfonts-base \
    && rm -rf /var/lib/apt/lists/*

# Install official wkhtmltopdf (patched qt) for headless support
RUN wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-2/wkhtmltox_0.12.6.1-2.bullseye_amd64.deb \
    && apt-get update && apt-get install -y ./wkhtmltox_0.12.6.1-2.bullseye_amd64.deb \
    && rm wkhtmltox_0.12.6.1-2.bullseye_amd64.deb

# Verify installation
RUN wkhtmltopdf --version

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories for persistence
RUN mkdir -p instance logs static/uploads

# Expose port
EXPOSE 5000

# Run with Gunicorn
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "--access-logfile", "-", "--error-logfile", "-", "app:app"]

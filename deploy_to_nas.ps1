$dest = "Z:\docker\library_checkin"
if (!(Test-Path $dest)) {
    Write-Error "Destination $dest not found. Is the Z: drive mounted?"
    exit 1
}

# Create necessary directories if missing (fixes boot loop)
if (!(Test-Path "$dest\logs")) {
    New-Item -ItemType Directory -Path "$dest\logs" -Force | Out-Null
    Write-Host "Created missing logs directory." -ForegroundColor Green
}
if (!(Test-Path "$dest\instance")) {
    New-Item -ItemType Directory -Path "$dest\instance" -Force | Out-Null
    Write-Host "Created instance directory."
}

# Copy files (Excluding heavy/dangerous items)
# Note: Excluding 'instance' prevents overwriting production DB with local DB
Write-Host "Copying files to $dest..."
Copy-Item ".\*" "$dest\" -Recurse -Force -Exclude ".git",".venv","__pycache__","*.pyc","instance","logs","screenshots*","*.spec","deploy_to_nas.ps1"

Write-Host "Deployment completed successfully." -ForegroundColor Green

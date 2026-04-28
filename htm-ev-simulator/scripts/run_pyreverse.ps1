# Regenerate PlantUML from pyreverse (classes + packages) and render SVG.
# Requires: py -3, pip install pylint, Java for PlantUML jar.
# Run from repository root: htm-ev-simulator

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$env:PYTHONPATH = (Join-Path $Root "src")
$Out = Join-Path $Root "out\pyreverse"
New-Item -ItemType Directory -Force -Path $Out | Out-Null

Write-Host "Running pyreverse..."
py -3 -m pylint.pyreverse.main -o puml -p htm_ev_simulator -d $Out backend frontend

$JarDir = Join-Path $Root "tools"
$Jar = Join-Path $JarDir "plantuml.jar"
if (-not (Test-Path $Jar)) {
    New-Item -ItemType Directory -Force -Path $JarDir | Out-Null
    $url = "https://github.com/plantuml/plantuml/releases/download/v1.2024.8/plantuml-1.2024.8.jar"
    Write-Host "Downloading PlantUML jar..."
    Invoke-WebRequest -Uri $url -OutFile $Jar -UseBasicParsing
}

Write-Host "Rendering SVG..."
java -jar $Jar -tsvg (Join-Path $Out "*.puml")
Write-Host "Done. Outputs under $Out"

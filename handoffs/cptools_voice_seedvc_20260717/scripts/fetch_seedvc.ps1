param(
  [string]$Destination = "external\seed-vc",
  [string]$Repository = "https://github.com/Plachtaa/seed-vc.git",
  [string]$Commit = "51383ef"
)

$ErrorActionPreference = "Stop"

if (Test-Path $Destination) {
  $items = Get-ChildItem -Force $Destination
  if ($items.Count -gt 0) {
    throw "Destination already exists and is not empty: $Destination"
  }
} else {
  New-Item -ItemType Directory -Force (Split-Path $Destination) | Out-Null
}

git clone $Repository $Destination
Push-Location $Destination
try {
  git checkout $Commit
} finally {
  Pop-Location
}

Write-Host "Seed-VC source is ready at $Destination"


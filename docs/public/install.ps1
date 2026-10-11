# Install (or update) stoetzms-pdf.exe on Windows:
#
#     powershell -Command "& {Invoke-WebRequest -Uri 'https://pdf.stoetz.ms/install.ps1' -UseBasicParsing | Invoke-Expression}"
#
# Installs into %LOCALAPPDATA%\stoetzms-pdf and adds it to the user's PATH.
# Set VERSION to install a release other than "latest".

$ErrorActionPreference = "Stop"

$installDir = "$env:LOCALAPPDATA\stoetzms-pdf"
$version = if ($env:VERSION) { $env:VERSION } else { "latest" }
$name = "stoetzms-pdf-windows-x64"
$archive = "$env:TEMP\$name.zip"

# Download and unpack
Invoke-WebRequest -Uri "https://github.com/milesstoetzner/stoetzms-pdf/releases/download/$version/$name.zip" -OutFile $archive -UseBasicParsing
if (Test-Path -Path $installDir) {
    Remove-Item -Recurse -Force $installDir
}
Expand-Archive -Path $archive -DestinationPath $env:TEMP -Force
Move-Item "$env:TEMP\$name" $installDir
Remove-Item $archive

# Add the install directory to the user's PATH
$userPath = [System.Environment]::GetEnvironmentVariable("PATH", [System.EnvironmentVariableTarget]::User)
if (-not ($userPath -split ";" | Where-Object { $_ -eq $installDir })) {
    [System.Environment]::SetEnvironmentVariable("PATH", "$userPath;$installDir", [System.EnvironmentVariableTarget]::User)
    Write-Host "Added $installDir to PATH; open a new terminal to use stoetzms-pdf"
}

& "$installDir\stoetzms-pdf.exe" --version

# Install sketchup-link Plugin on Windows VM

This doc captures the exact procedure for installing the `sketchup-link` Ruby SketchUp plugin on the Windows 11 VM running in Docker. Follow these steps in order.

## Prerequisites

- Docker VM is running (`docker compose -f shared/project/ext/sketchup-link/integration/compose.yml up -d`)
- VM is fully booted (check at `http://127.0.0.1:8006` or `docker compose -f shared/project/ext/sketchup-link/integration/compose.yml logs windows`)
- The `.rbz` package is built (`make package` at repo root, or `cd shared/project/ext/sketchup-link && bundle exec ruby package.rb`)

## RDP Connection

The default credentials for `dockurr/windows` are:

|Field|Value|
|---|---|
|Username|`Docker`|
|Password|`admin`|
|Host|`127.0.0.1`|
|Port|`3389`|

### Connect with drive mapping
The RDP client (`agent-rdp`) must map a local directory so the host's `integration/shared/` folder (relative to the plugin project root) appears inside the VM.

```bash
agent-rdp connect --host 127.0.0.1 -u Docker -p admin \
  --enable-win-automation \
  --drive /home/jasonkraus/Repos/sketchup-link/shared/project/ext/sketchup-link/integration/shared:Shared \
  --timeout 60000
```

The path to `agent-rdp` on this system:

```
/home/jasonkraus/.npm/_npx/40914459cb15cd11/node_modules/@agent-rdp/linux-x64/bin/agent-rdp
```

## Plugin Installation

### 1. Extract the RBZ

The `.rbz` file is a ZIP archive. Extract it so individual files can be copied:

```bash
cd shared/project/ext/sketchup-link/integration/shared/
unzip -o ../../dist/sketchup-link-1.0.0.rbz -d sketchup-link-extracted
```

The critical files for SketchUp are:

- `sketchup-link-extracted/sketchup_link.rb` — extension loader
- `sketchup-link-extracted/sketchup_link/` — plugin source directory

### 2. Access the Shared folder inside Windows

The `--drive` mapping from RDP creates a `Shared` folder on the Windows desktop at:

```
C:\Users\Docker\Desktop\Shared
```

This is a **separate path** from the `dockurr/windows` container's `/shared` volume (which also appears in `C:\Users\Docker\Desktop\Shared`). Both map to the host's `integration/shared/` directory (under the plugin project root).
**Important:** Files written to the host's `integration/shared/` directory are only visible inside the Windows VM after an RDP reconnection. If you write files to `integration/shared/` while the RDP session is active, they may not appear until you disconnect and reconnect.

### 3. Copy plugin files

Open a **Command Prompt** (not PowerShell) and navigate to the Shared directory:

```cmd
cd /d C:\Users\Docker\Desktop\Shared
```

Create the Extensions directory and copy the files. Using a batch file is the most reliable approach because keyboard typing in RDP is slow and error-prone for long commands.

**Option A — Create and run a batch file on the host:**

Write `shared/install.bat`:

```bat
@echo off
set EXT=C:\Users\Docker\AppData\Roaming\SketchUp\SketchUp 2025\SketchUp\Extensions
set SRC=C:\Users\Docker\Desktop\Shared\sketchup-link-extracted
mkdir "%EXT%\sketchup_link" 2>nul
xcopy "%SRC%\sketchup_link" "%EXT%\sketchup_link" /E /I /Y /Q
copy "%SRC%\sketchup_link.rb" "%EXT%" /Y
echo Plugin installed successfully
```

Then run it from cmd:

```cmd
install
```

**Option B — Use clipboard paste for a single command:**

Set the clipboard from the host, then paste in the cmd window:

```bash
agent-rdp clipboard set 'xcopy "C:\Users\Docker\Desktop\Shared\sketchup-link-extracted\sketchup_link" "C:\Users\Docker\AppData\Roaming\SketchUp\SketchUp 2025\SketchUp\Extensions\sketchup_link" /E /I /Y'
agent-rdp keyboard press "ctrl+v"
agent-rdp keyboard press enter
```

Repeat for the `sketchup_link.rb` file.

### 4. Verify installation

```cmd
dir "C:\Users\Docker\AppData\Roaming\SketchUp\SketchUp 2025\SketchUp\Extensions\"
```

Expected output:

```
05/04/2026  07:17 AM    <DIR>  .
05/04/2026  07:09 AM    <DIR>  ..
05/04/2026  07:17 AM    <DIR>  sketchup_link
03/28/2026  09:42 PM         450 sketchup_link.rb
```

## Launching SketchUp

SketchUp can be launched in several ways:

### From command line

```cmd
"C:\Program Files\SketchUp\SketchUp 2025\SketchUp.exe"
```

### Via UI Automation

```bash
agent-rdp automate run "C:\Program Files\SketchUp\SketchUp 2025\SketchUp.exe"
```

### Via desktop shortcut

```bash
agent-rdp automate click "@e246" -d
```

(Element ref may vary — reference `ListItem "SketchUp 2025"` from the desktop list.)

## Known Issues

### SketchUp fails to launch in VM

The QEMU/KVM VM may not have sufficient GPU acceleration for SketchUp. Look for:

- Process starts and exits immediately (use `automate run` to get a PID, then `tasklist` to verify)
- No window appears even after 30+ second wait
- Taskbar shows no SketchUp icon
- Accessibility tree has no "SketchUp" window element

The plugin files are correctly placed regardless — they will be loaded when SketchUp starts in an environment with working GPU support.

### RDP-mapped drive appears empty

If `\\tsclient\Shared` or the mapped T: drive shows "File Not Found":

1. Disconnect and reconnect the RDP session: `agent-rdp disconnect && agent-rdp connect ...`
2. Use the Docker volume path instead: `C:\Users\Docker\Desktop\Shared`
3. Files written to the mounted directory are only captured at RDP connect time

### PowerShell execution policy blocks scripts

```powershell
# Running scripts is disabled on this system
```

Use cmd.exe (not PowerShell) for batch files, or pass inline commands via `powershell -c "..."`.

### Long commands are unreliable via keyboard typing

The `agent-rdp keyboard type` command has a timeout (~10s) and may truncate or mangle long commands. Workarounds:

- **Clipboard paste** — `agent-rdp clipboard set "..."` → `agent-rdp keyboard press "ctrl+v"`
- **Batch files** — Write a `.bat` script to the shared directory and execute it
- **Short PowerShell** — Use `powershell -c "cp ... -r"` with wildcards and `$env:APPDATA` to keep commands short
- **Base64-encoded commands** — Encode a PowerShell script as Base64 and use `powershell -EncodedCommand <base64>`

## Cleanup

`agent-rdp disconnect`

The extracted `integration/shared/sketchup-link-extracted/` directory and `integration/shared/scripts/install.bat` can be removed:

```bash
rm -rf shared/project/ext/sketchup-link/integration/shared/sketchup-link-extracted shared/project/ext/sketchup-link/integration/shared/scripts/install.bat shared/project/ext/sketchup-link/integration/shared/scripts/install.ps1
```
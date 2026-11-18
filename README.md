# LiveFeed

Capture **Windows 11 Live Captions** and show that text in a Chrome/Edge extension modal. The system caption bar stays running but is hidden while capture is on.

This project only includes the caption-capture path from HelpME. Interview answering, llama.cpp, retrieval, Qt, and session history were not carried over.

## How capture works

Windows already turns meeting/system audio into text. LiveFeed does not record audio and does not run OCR.

1. **Start** launches `LiveCaptions.exe` when it is not already running (`Win+Ctrl+L` also works).
2. The process is started in a new process group and broken out of the parent job, so closing LiveFeed does not kill the system caption bar.
3. Capture waits until the `LiveCaptionsDesktopWindow` (or the “Live Captions” window / `LiveCaptions.exe` PID) is attachable.
4. After attach, the system bar is cloaked, made fully transparent, and moved off-screen. `ShowWindow(SW_HIDE)` is not used — that drops the window from UI Automation and capture stops. The poll loop re-applies the hide if Windows puts the bar back.
5. A worker thread binds UI Automation once and polls about every 80 ms.
6. Text is taken from `CaptionsTextBlock` / `CaptionTextBlock` / `CaptionText`, then from Text/Document/Edit controls if those IDs are missing.
7. Settings chrome and placeholder strings are ignored.
8. Only a changed line is emitted. After the bar stays empty for a short hold, an empty line is emitted so the next identical sentence is a new utterance.
9. **Stop** signals the worker, restores the system bar, and waits a bounded time. The worker is a daemon, so a stuck native UIA call cannot freeze the UI. Live Captions itself is left open.

The rolling caption window is then merged into a session transcript so the modal does not blindly concatenate overlapping slices.

## Run the LiveFeed app

Double-click `Start LiveFeed.bat` (or `LiveFeed.pyw`) in this folder.

```powershell
cd F:\Work\LiveFeed
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e .
python -m livefeed
```

Use **Start** / **Stop** in that desktop window. The app listens on `http://127.0.0.1:17865` so the extension can connect. **Stop** or closing the app restores the Windows Live Captions bar.

```powershell
python -m livefeed --check
python -m livefeed --restore-captions
```

While capturing, the system Live Captions bar is hidden on purpose. Configure its gear menu once (Win+Ctrl+L) so it captions system/app audio.

## Load the extension

1. Open `edge://extensions` or `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked** and select `F:\Work\LiveFeed\extension`
4. Reload the extension after updates

The extension has no Start/Stop. It connects to the app automatically. If the popup says Offline, click **Connect**. Then press **Start** in the LiveFeed app.

## HelpME can be removed

HelpME was used only as a reference. LiveFeed now owns the complete Live Captions flow that HelpME used for transcription:

| HelpME piece | LiveFeed equivalent | Needed for capture? |
| --- | --- | --- |
| `app/audio/win_live_captions.py` | `livefeed/captions.py`, `livefeed/reader.py` | Yes |
| Live Captions launch / PID / window attach | `launch_live_captions`, `wait_for_caption_window` | Yes |
| UI Automation text read + chrome filters | `extract_caption`, `clean_caption` | Yes |
| Poll / empty-bar boundary / bounded stop | `LiveCaptionReader` | Yes |
| Rolling-window transcript merge | `livefeed/transcript.py` | Yes (display) |
| Settings “Test Live Captions” | `POST /start` + extension Start | Yes |
| Session start/stop listening | Caption hub + extension Start/Stop | Yes |
| LLM, Qt UI, retrieval, interview turns | not ported | No |

After you confirm LiveFeed Start/Stop shows captions, delete the `HelpME` folder. Do not copy files out of it; this tree is the replacement.

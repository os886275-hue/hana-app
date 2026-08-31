# Hana — web app

Type Arabic text, hear it spoken by a MetaHuman avatar in Unreal, streamed live
into a browser window.

```
text  ->  VoiceTut TTS  ->  WAV  ->  Unreal Speech2Face solve  ->  Level Sequence
                                                                        |
                                    browser  <--- WebRTC ---  Pixel Streaming
```

---

## Read this before you start

**This app cannot run on its own.** It is a front end. The machine it runs on
must also be running Unreal Editor with the avatar project, because the face
animation is solved by **MetaHuman Animator**, whose modules
(`MetaHumanPerformance`, `MetaHumanSpeech2Face`, `MetaHumanPipeline`) are all
`Type=Editor`. They are stripped from a packaged build, so there is no way to
ship this as a self-contained `.exe`.

What Pixel Streaming buys you is that *viewers* need nothing but a browser —
Unreal runs on one machine and everyone else connects to it.

### Required on the host machine

| Requirement | Notes |
|---|---|
| Windows | the launcher and paths are Windows-specific |
| NVIDIA GPU | TTS runs on CUDA; CPU works but is very slow |
| Unreal Engine 5.6 | with the **MetaHuman** (MetaHuman Animator) plugin |
| The `MyProject 5.6` avatar project | not in this repo — it is tens of GB |
| Node.js 22.x | for the Pixel Streaming signalling server |
| Microsoft Edge | the launcher opens it in `--app` mode |
| HuggingFace token | the VoiceTut TTS model is gated |

---

## Setup

### 1. Python

```bat
python -m venv venv
venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cu130
venv\Scripts\pip install -r requirements.txt
```

Install the CUDA torch wheel **first** — `requirements.txt` deliberately does
not pin a CUDA build, since the right one depends on the target GPU/driver.

### 2. Configure

```bat
copy .env.example .env
```

Then edit `.env`: add your `HF_TOKEN` and set `UNREAL_AUDIO_DIR` to a folder the
Unreal editor on this machine can read.

### 3. Pixel Streaming signalling server

Not vendored here — fetch it from Epic:

```bat
curl -L -o ps.zip https://github.com/EpicGamesExt/PixelStreamingInfrastructure/archive/refs/heads/UE5.6.zip
tar -xf ps.zip
cd PixelStreamingInfrastructure-UE5.6
npm install
npm run build --ws
cd SignallingWebServer
```

Edit `config.json` before first run — the shipped file has a `http_root`
baked in from Epic's build machine (`D:\PixelStreamingInfrastructure\...`)
that will not exist:

```json
"http_root": "<absolute path to>/SignallingWebServer/www",
"homepage": "index.html",
"player_port": "80"
```

Keep `player_port` at **80**. The prebuilt frontend hardcodes
`ss:"ws://localhost:80"`, so serving on any other port gives a blank page with
`WebSocket connection to 'ws://localhost/' failed` in the console. If you must
use another port, load the page as `?ss=ws://localhost:<port>`.

Then:

```bat
node dist\index.js
```

### 4. Unreal

1. Open the project
2. Project Settings → Plugins → Remote Control → **Auto Start Web Server** on
   (the app talks to `127.0.0.1:30010`)
3. Enable **Pixel Streaming** from the toolbar
4. Press **Play** — and leave it playing

---

## Run

```bat
Hana_Web.bat
```

Starts the app on `http://127.0.0.1:5001` and opens Edge in app mode (no tabs,
no address bar). Type, press Enter or **Speak**.

Others on the network can use `http://<host-ip>:5001`.

---

## Things that will catch you out

**Press Play first, then open the app.** Unreal's Pixel Streaming streamer
restarts on every Play/Stop. A browser that negotiated WebRTC against a dead
streamer keeps its websocket open and shows black forever with no error. That
is what the **Reconnect** button is for.

**A live stream does not mean Play is running.** When PIE is stopped, Pixel
Streaming quietly falls back to streaming the *editor viewport*, so you still
see a picture — but the avatar will look wrong, because outside PIE the
character's components have no `leader_pose_component` and each mesh sits in
its own reference pose.

**Click once inside the video before the first Speak**, or the audio stays
muted by browser autoplay policy and it looks like the sound is broken.

**First Speak takes ~30s** while the TTS model loads. It stays warm after that.

**Do not judge lip sync over RDP.** RDP sends audio and video on separate
channels with different latencies, so any offset you perceive is transport, not
the pipeline. Measure it by rendering the Level Sequence offline with Movie
Render Queue instead, then set `UNREAL_AUDIO_LATENCY_COMPENSATION` from that.

---

## What is not in this repo

- The Unreal project and the MetaHuman assets (far too large)
- The signalling server (fetched from Epic — see above)
- The TTS model weights (pulled from HuggingFace on first run)
- The rest of the original pipeline — STT, RAG, the local LLM, Audio2Face and
  the Arabic forced aligner. This app is text-in only.

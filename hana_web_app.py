"""Hana: text box + live avatar in one page, opened as a chrome-less window.

    .\\venv\\Scripts\\python.exe hana_web_app.py

Serves a small page on http://127.0.0.1:5001 that puts a text bar above an
iframe of Epic's Pixel Streaming player, and exposes /speak which runs the
existing TTS -> Unreal pipeline.

Why a browser rather than an embedded webview: this machine has a WebView2
registry entry but no actual runtime installed (the versioned folder under
Program Files (x86)\\Microsoft\\EdgeWebView\\Application is empty), so pywebview
silently falls back to the Internet Explorer control, which has no WebRTC.
Edge itself renders the stream fine, so Hana_Web.bat launches Edge in --app
mode: no tabs, no address bar, looks like a native window.

Needs, on this machine:
  * Unreal editor open on avatar1/MyProject 5.6 and IN PLAY
  * the Pixel Streaming signalling server running (serves http://localhost)
"""
import os
import threading

from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.getenv("UNREAL_AUDIO_DIR", r"F:\or\avatar1\audio")
STREAM_URL = os.getenv("PIXEL_STREAM_URL", "http://localhost/")
PORT = int(os.getenv("HANA_APP_PORT", "5001"))

app = Flask(__name__)

_tts = None
_tts_lock = threading.Lock()


def _load_tts():
    """Load the TTS model once and keep it -- it takes ~30s to initialise."""
    global _tts
    with _tts_lock:
        if _tts is None:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "tts_service", os.path.join(HERE, "services", "tts_service.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            svc = mod.TTSService()
            svc.initialize()
            _tts = svc
    return _tts


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Hana</title>
<style>
 html,body{margin:0;height:100%;background:#14171c;color:#e8e8e8;
           font-family:'Segoe UI',sans-serif;display:flex;flex-direction:column}
 #bar{display:flex;gap:8px;padding:9px;background:#1c2027;align-items:center;
      border-bottom:1px solid #2a2f38}
 #text{flex:1;padding:9px 11px;font-size:15px;border-radius:6px;
       border:1px solid #333a45;background:#0f1216;color:#eee}
 select,button{padding:9px 14px;font-size:14px;border-radius:6px;
               border:1px solid #333a45;background:#252b34;color:#eee;cursor:pointer}
 button:disabled{opacity:.5;cursor:default}
 #status{padding:4px 12px;font-size:12px;color:#8b93a1;background:#1c2027}
 #stream{flex:1;border:0;width:100%;background:#000}
</style></head><body>
 <div id="bar">
   <input id="text" placeholder="Type what she should say..." value="مرحبا، كيف حالك؟">
   <select id="avatar"><option>BP_avatar1</option><option>BP_Hana</option></select>
   <button id="go">Speak</button>
   <button id="reconnect" title="Unreal's streamer restarts on every Play/Stop; a player negotiated against a dead streamer just shows black">Reconnect</button>
 </div>
 <div id="status">Click the video once to enable audio, then type and hit Speak.</div>
 <iframe id="stream" src="__STREAM__" allow="autoplay; fullscreen"></iframe>
<script>
 const btn=document.getElementById('go'), txt=document.getElementById('text'),
       st=document.getElementById('status');
 async function speak(){
   const t=txt.value.trim(); if(!t) return;
   btn.disabled=true; st.textContent='synthesising... (first run loads the model, ~30s)';
   try{
     const r=await fetch('/speak',{method:'POST',headers:{'Content-Type':'application/json'},
       body:JSON.stringify({text:t,avatar:document.getElementById('avatar').value})});
     const j=await r.json();
     st.textContent = j.ok ? 'speaking' : ('failed: ' + (j.error||'see console'));
   }catch(e){ st.textContent='error: '+e; }
   finally{ btn.disabled=false; }
 }
 btn.onclick=speak;
 txt.addEventListener('keydown',e=>{ if(e.key==='Enter') speak(); });
 // Unreal's Pixel Streaming streamer drops and re-registers every time PIE
 // starts or stops. Players negotiated against the old streamer keep their
 // websocket but never get video again -- reloading the iframe re-negotiates.
 document.getElementById('reconnect').onclick=()=>{
   const f=document.getElementById('stream');
   st.textContent='reconnecting to the stream...';
   f.src=f.src;
 };
</script></body></html>"""


@app.get("/")
def index():
    return PAGE.replace("__STREAM__", STREAM_URL)


@app.post("/speak")
def speak():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    avatar = data.get("avatar") or "BP_avatar1"
    if not text:
        return jsonify(ok=False, error="nothing to say")
    try:
        svc = _load_tts()
        wav = svc.synthesize_raw(text)
        if wav is None:
            return jsonify(ok=False, error="TTS returned nothing")

        import soundfile as sf
        os.makedirs(AUDIO_DIR, exist_ok=True)
        path = os.path.join(AUDIO_DIR, "live_tts.wav")
        sf.write(path, wav, svc.sample_rate)

        from services.unreal_bridge import animate_hana_from_wav
        ok = animate_hana_from_wav(path, name="LiveTTS", avatar=avatar,
                                   caption=text, timings=None)
        return jsonify(ok=bool(ok),
                       error=None if ok else "Unreal solve/play failed -- is it in Play?")
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return jsonify(ok=False, error="%s: %s" % (type(exc).__name__, exc))


if __name__ == "__main__":
    print("Hana app on http://127.0.0.1:%d  (streaming from %s)" % (PORT, STREAM_URL))
    app.run(host="127.0.0.1", port=PORT, threaded=True)

import os
import io
import base64
import torch
import numpy as np
import soundfile as sf


class TTSService:
    def __init__(
        self,
        model_repo="mohammedaly22/VoiceTut-TTS",
        device="cuda" if torch.cuda.is_available() else "cpu",
        sample_rate=24000
    ):
        self.model_repo = model_repo
        self.device = device
        self.sample_rate = sample_rate
        self.model = None

    def initialize(self):
        """Initializes the VoiceTut TTS model."""
        if self.model is not None:
            return

        print("Initializing VoiceTut-TTS model in-process (this may take a moment)...")
        from voicetut_tts import VoiceTutTTS
        self.model = VoiceTutTTS.from_pretrained(
            self.model_repo,
            device=self.device
        )
        print("VoiceTut-TTS model loaded successfully.")

        # Extract true sample rate if available
        if hasattr(self.model, 'sample_rate'):
            self.sample_rate = self.model.sample_rate
        elif hasattr(self.model, 'config') and hasattr(self.model.config, 'sample_rate'):
            self.sample_rate = self.model.config.sample_rate

        print(f"TTS Service initialized (sample_rate={self.sample_rate}).")

    def synthesize_raw(self, text: str) -> np.ndarray:
        """Synthesizes speech from text and returns a raw float32 numpy waveform array.
        This is the primary method used by the A2F bridge pipeline."""
        if not text or not text.strip() or self.model is None:
            return None

        print("TTS generating audio in-process...")
        try:
            with torch.no_grad():
                wav_tensor = self.model.synthesize(text, language="ar", speaker="Esraa")

            # Ensure it's a 1D numpy float32 array
            if isinstance(wav_tensor, torch.Tensor):
                wav_np = wav_tensor.detach().cpu().squeeze().numpy().astype(np.float32)
            else:
                wav_np = np.array(wav_tensor, dtype=np.float32).squeeze()

            return wav_np

        except Exception as e:
            print(f"Error generating TTS: {e}")
            import traceback
            traceback.print_exc()
            return None

    def synthesize(self, text: str) -> str:
        """Synthesizes speech and returns a base64-encoded WAV string (legacy method)."""
        wav_np = self.synthesize_raw(text)
        if wav_np is None:
            return ""

        try:
            buf = io.BytesIO()
            sf.write(buf, wav_np, self.sample_rate, format='WAV')
            audio_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
            return audio_base64
        except Exception as e:
            print(f"Error encoding TTS to base64: {e}")
            return ""

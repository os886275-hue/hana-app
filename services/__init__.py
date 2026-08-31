"""Only the two services hana_web_app needs.

The full pipeline's __init__ also imported STT, RAG, Audio2Face, the Arabic
aligner and the LiveLink sender. None of those are used by this app, and
importing them would drag in torch/chromadb/grpc paths that are not in
requirements.txt -- so this package deliberately exposes just these two.
"""
from .tts_service import TTSService
from .unreal_bridge import animate_hana_from_wav

__all__ = ["TTSService", "animate_hana_from_wav"]

"""edge-tts 封装：文本 → mp3。"""

from __future__ import annotations

import asyncio
from pathlib import Path


def synthesize(
    text: str,
    out_path: str | Path,
    *,
    voice: str = "zh-CN-YunxiNeural",
    rate: str = "+0%",
) -> Path:
    """同步合成；需要已安装 edge-tts（pip install -e '.[speak]'）。"""
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("empty TTS text")
    dest = Path(out_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_synthesize_async(cleaned, dest, voice=voice, rate=rate))
    return dest


async def _synthesize_async(
    text: str,
    dest: Path,
    *,
    voice: str,
    rate: str,
) -> None:
    try:
        import edge_tts
    except ImportError as exc:
        raise ImportError(
            "edge-tts is required for TTS. Install with: pip install -e '.[speak]'"
        ) from exc
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
    await communicate.save(str(dest))

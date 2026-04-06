"""Tencent Cloud Voice Options for TTS."""

TENCENT_VOICE_OPTIONS = [
    # 精品音色 - 适合日常聊天
    {"id": "101001", "name": "智瑜", "description": "情感女声", "gender": "female", "category": "premium"},
    {"id": "101004", "name": "智云", "description": "通用男声", "gender": "male", "category": "premium"},
    {"id": "101026", "name": "智希", "description": "通用女声", "gender": "female", "category": "premium"},
    {"id": "101030", "name": "智柯", "description": "通用男声", "gender": "male", "category": "premium"},
    # 大模型音色 - 更自然
    {"id": "501004", "name": "月华", "description": "聊天女声", "gender": "female", "category": "large_model"},
    {"id": "501005", "name": "飞镜", "description": "聊天男声", "gender": "male", "category": "large_model"},
    # 超自然大模型音色 - 最自然
    {"id": "502001", "name": "智小柔", "description": "聊天女声", "gender": "female", "category": "ultra"},
    {"id": "502006", "name": "智小悟", "description": "聊天男声", "gender": "male", "category": "ultra"},
]

DEFAULT_VOICE_ID = "101001"  # 智瑜 - 情感女声


def get_voice_name(voice_id: str) -> str:
    """Get voice name by ID."""
    for voice in TENCENT_VOICE_OPTIONS:
        if voice["id"] == voice_id:
            return f"{voice['name']} ({voice['description']})"
    return f"自定义音色 ({voice_id})"


def get_voice_info(voice_id: str) -> dict | None:
    """Get voice info by ID."""
    for voice in TENCENT_VOICE_OPTIONS:
        if voice["id"] == voice_id:
            return voice
    return None

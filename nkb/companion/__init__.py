"""可追溯的本地伴侣记忆与显式 DeepSeek 调用。导入包不会联网或读取密钥。"""
from .client import CompanionError, DeepSeekClient
from .memory import build_context, get_profile, history, record_turn, remember, save_profile, turn_id
from .ingestion import connected_session_id, ingest_event
from .persona import (PersonaConflict, accept_persona, get_persona, import_persona,
                      learn_from_dialogue, persona_state, propose_persona, reject_persona,
                      review_candidate, rollback_persona, set_persona_enabled, set_persona_learning)

__all__ = ["build_context", "get_profile", "save_profile", "remember", "record_turn", "history",
           "turn_id", "DeepSeekClient", "CompanionError", "ingest_event", "connected_session_id",
           "persona_state", "get_persona", "import_persona", "propose_persona", "accept_persona",
           "reject_persona", "review_candidate", "rollback_persona", "set_persona_enabled",
           "set_persona_learning", "learn_from_dialogue", "PersonaConflict"]

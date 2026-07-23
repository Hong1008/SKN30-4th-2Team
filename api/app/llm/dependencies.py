"""FastAPI에서 재사용할 LLM 의존성을 정의한다."""

from typing import Annotated

from fastapi import Depends
from langchain_core.language_models.chat_models import BaseChatModel

from app.config import SettingsDep
from app.llm.factory import create_chat_model
from app.llm.types import ReasoningMode


def get_chat_model(settings: SettingsDep) -> BaseChatModel:
    """선택 provider의 기본 non-reasoning chat model을 반환한다."""
    return create_chat_model(settings, ReasoningMode.OFF)


ChatModelDep = Annotated[BaseChatModel, Depends(get_chat_model)]
"""FastAPI 라우터와 서비스에서 재사용하는 chat model 의존성."""

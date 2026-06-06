from typing import Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str = Field(..., description="消息角色: system, user, assistant")
    content: str = Field(..., min_length=1, description="消息内容")


class ChatCompletionRequest(BaseModel):
    model: str = Field(..., min_length=1, max_length=100, description="模型名称")
    messages: list[ChatMessage] = Field(..., min_length=1, description="对话消息列表")
    max_tokens: Optional[int] = Field(None, ge=1, le=128000, description="最大生成 token 数")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="采样温度")


class ChatCompletionChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str = "stop"


class ChatCompletionUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage

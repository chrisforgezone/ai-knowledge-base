"""统一 LLM 模型调用客户端。

支持 DeepSeek、Qwen、MiniMax、OpenAI 四家 OpenAI-Compatible 接口
以及 Anthropic Messages API，通过 ProviderConfig 从 .env / 系统环境变量
读取配置实现无缝切换。
"""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any, Literal

import httpx
from dotenv import load_dotenv
from loguru import logger
from pydantic import BaseModel
from pydantic.dataclasses import dataclass

try:
    from .exceptions import (
        LLMAuthenticationError,
        LLMBadRequestError,
        LLMClientError,
        LLMConnectionError,
        LLMMaxRetriesExceededError,
        LLMRateLimitError,
    )
except ImportError:
    from exceptions import (  # type: ignore[import-not-found,no-redef]
        LLMAuthenticationError,
        LLMBadRequestError,
        LLMClientError,
        LLMConnectionError,
        LLMMaxRetriesExceededError,
        LLMRateLimitError,
    )

load_dotenv()


class ProviderName(StrEnum):
    """LLM 提供商名称枚举。"""
    DEEPSEEK = "deepseek"
    QWEN = "qwen"
    MINIMAX = "minimax"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


@dataclass
class Message:
    """聊天消息。"""
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class Usage:
    """Token 用量统计。"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ChatRequest:
    """聊天请求参数。"""
    messages: list[Message]
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    stream: bool = False


@dataclass
class ChatResponse:
    """聊天响应。"""
    content: str
    usage: Usage | None = None
    finish_reason: str | None = None


# ---- 内置 Provider 默认配置 ----

_PROVIDER_DEFAULTS: dict[ProviderName, dict[str, str]] = {
    ProviderName.DEEPSEEK: {"base_url": "https://api.deepseek.com/v1",
                            "model": "deepseek-chat"},
    ProviderName.QWEN: {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                        "model": "qwen-plus"},
    ProviderName.MINIMAX: {"base_url": "https://api.minimax.chat/v1",
                           "model": "abab6.5s-chat"},
    ProviderName.OPENAI: {"base_url": "https://api.openai.com/v1",
                          "model": "gpt-4o"},
    ProviderName.ANTHROPIC: {"base_url": "https://api.anthropic.com/v1",
                             "model": "claude-sonnet-4-20250514"},
}


class ProviderConfig(BaseModel):
    """LLM 提供商配置，从环境变量读取。

    Attributes:
        name: 提供商名称。
        api_key: API Key。
        base_url: API 基地址。
        default_model: 默认模型名称。
        timeout: HTTP 超时时间（秒）。
    """

    name: ProviderName
    api_key: str
    base_url: str
    default_model: str
    timeout: float = 60.0

    @classmethod
    def from_provider_name(cls, name: str | ProviderName) -> ProviderConfig:
        """从环境变量加载指定提供商的配置。

        按 {NAME}_API_KEY / {NAME}_BASE_URL / {NAME}_MODEL 读取环境变量，
        未设置时回退到 _PROVIDER_DEFAULTS 中的内置默认值。

        Args:
            name: 提供商名称（如 ``"deepseek"``）或 ``ProviderName`` 枚举值。

        Returns:
            填充好配置的 ProviderConfig 实例。

        Raises:
            LLMClientError: 缺少必需的环境变量 ``{NAME}_API_KEY`` 时抛出。
        """
        if isinstance(name, str):
            name = ProviderName(name.lower())
        prefix = name.name
        defaults = _PROVIDER_DEFAULTS[name]
        api_key = os.getenv(f"{prefix}_API_KEY", "")
        if not api_key:
            raise LLMClientError(
                f"缺少 API Key，请设置环境变量 {prefix}_API_KEY")
        return cls(
            name=name,
            api_key=api_key,
            base_url=os.getenv(f"{prefix}_BASE_URL", defaults["base_url"]),
            default_model=os.getenv(f"{prefix}_MODEL", defaults["model"]),
        )


class LLMProvider(ABC):
    """LLM 提供商抽象基类。

    子类需实现 ``chat``、``achat`` 以及四个构建/解析 hook。
    提供 ``quick_chat`` 和 ``chat_retry`` 两个开箱即用的模板方法。
    """

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    # -- 抽象方法 -------------------------------------------------------

    @abstractmethod
    def chat(self, request: ChatRequest) -> ChatResponse:
        """同步发送聊天请求。

        Args:
            request: ChatRequest 对象。

        Returns:
            ChatResponse 包含模型回复、用量统计和结束原因。
        """

    @abstractmethod
    async def achat(self, request: ChatRequest) -> ChatResponse:
        """异步发送聊天请求。

        Args:
            request: ChatRequest 对象。

        Returns:
            ChatResponse。
        """

    @abstractmethod
    def _build_http_payload(self, request: ChatRequest) -> dict[str, Any]: ...

    @abstractmethod
    def _parse_http_response(self, data: dict[str, Any]) -> ChatResponse: ...

    @abstractmethod
    def _get_headers(self) -> dict[str, str]: ...

    @abstractmethod
    def _get_chat_endpoint(self) -> str: ...

    # -- 模板方法 -------------------------------------------------------

    def quick_chat(
        self, prompt: str, *, system: str | None = None, **kwargs: Any,
    ) -> ChatResponse:
        """便捷单轮对话——一句话调用大模型。

        自动构建单条 user 消息（可选 system 消息），并调用 ``self.chat``。

        Args:
            prompt: 用户消息内容。
            system: 系统提示词，可选。
            **kwargs: 传递给 ``ChatRequest`` 的额外参数
                      （如 temperature, max_tokens, model 等）。

        Returns:
            ChatResponse。
        """
        messages: list[Message] = [Message(role="user", content=prompt)]
        if system:
            messages.insert(0, Message(role="system", content=system))
        kwargs.setdefault("model", self.config.default_model)
        kwargs.setdefault("messages", messages)
        return self.chat(ChatRequest(**kwargs))

    def chat_retry(
        self, request: ChatRequest, *, retries: int = 3,
        base_delay: float = 1.0,
    ) -> ChatResponse:
        """带指数退避重试的同步聊天调用。

        可重试场景: 网络错误、超时、5xx、429 限流。
        不可重试: 4xx 客户端错误（直接抛出）。

        Args:
            request: ChatRequest 对象。
            retries: 最大重试次数（额外尝试次数，默认 3）。最多发起 1+3 次请求。
            base_delay: 退避基数秒，第 i 次重试延迟 = ``base_delay * 2^i``。

        Returns:
            ChatResponse。

        Raises:
            LLMMaxRetriesExceededError: retries 耗尽后抛出，
                                        其 ``__cause__`` 为最后一次异常。
            LLMAuthenticationError: 鉴权失败，不做重试。
            LLMBadRequestError: 请求参数错误，不做重试。
        """
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                if attempt > 0:
                    logger.info("第 {} 次重试 LLM 调用", attempt)
                return self.chat(request)
            except Exception as exc:
                last_exc = exc
                if not self._should_retry(exc):
                    raise
                if attempt >= retries:
                    break
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "LLM 调用失败 (attempt {}/{}), {:.1f}s 后重试: {}",
                    attempt + 1, retries + 1, delay, exc,
                )
                time.sleep(delay)
        raise LLMMaxRetriesExceededError(
            f"LLM 调用在 {retries} 次重试后仍然失败"
        ) from last_exc

    @staticmethod
    def _should_retry(exc: Exception) -> bool:
        """判断异常是否应该触发重试。

        可重试: ``httpx.NetworkError``、``httpx.TimeoutException``、
                 ``LLMRateLimitError``（429）、``LLMConnectionError``（5xx）。
        不可重试: ``LLMAuthenticationError``（401/403）、
                   ``LLMBadRequestError`` 等其它异常。
        """
        if isinstance(exc, (httpx.NetworkError, httpx.TimeoutException)):
            return True
        if isinstance(exc, (LLMRateLimitError, LLMConnectionError)):
            return True
        return False

    def _raise_for_status(self, response: httpx.Response) -> None:
        """将 HTTP 状态码映射为语义化自定义异常。

        Args:
            response: httpx.Response 对象。

        Raises:
            LLMRateLimitError: 429 限流。
            LLMAuthenticationError: 401 或 403。
            LLMBadRequestError: 其它 4xx。
            LLMConnectionError: 5xx 服务端错误。
        """
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code == 429:
                raise LLMRateLimitError("API 限流 (429)") from exc
            if code in (401, 403):
                raise LLMAuthenticationError(
                    f"鉴权失败 ({code})") from exc
            if 400 <= code < 500:
                raise LLMBadRequestError(
                    f"请求错误 ({code}): {exc.response.text}") from exc
            raise LLMConnectionError(f"服务端错误 ({code})") from exc


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI Chat Completions 兼容接口提供商。

    适用于所有提供 ``/chat/completions`` 端点 + Bearer Token 鉴权的服务，
    包括 OpenAI、DeepSeek、Qwen（DashScope）、MiniMax。
    """

    def _get_chat_endpoint(self) -> str:
        return "/chat/completions"

    def _get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def _build_http_payload(self, request: ChatRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": m.role, "content": m.content}
                for m in request.messages
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.top_p != 1.0:
            payload["top_p"] = request.top_p
        if request.stream:
            payload["stream"] = True
        return payload

    def _parse_http_response(self, data: dict[str, Any]) -> ChatResponse:
        choice = data["choices"][0]
        u = data.get("usage", {})
        return ChatResponse(
            content=choice["message"]["content"],
            usage=Usage(
                prompt_tokens=u.get("prompt_tokens", 0),
                completion_tokens=u.get("completion_tokens", 0),
                total_tokens=u.get("total_tokens", 0),
            ),
            finish_reason=choice.get("finish_reason"),
        )

    def chat(self, request: ChatRequest) -> ChatResponse:
        url = f"{self.config.base_url}{self._get_chat_endpoint()}"
        payload = self._build_http_payload(request)
        headers = self._get_headers()
        logger.debug("POST {} model={}", url, request.model)
        with httpx.Client(timeout=self.config.timeout) as client:
            response = client.post(url, json=payload, headers=headers)
        self._raise_for_status(response)
        return self._parse_http_response(response.json())

    async def achat(self, request: ChatRequest) -> ChatResponse:
        url = f"{self.config.base_url}{self._get_chat_endpoint()}"
        payload = self._build_http_payload(request)
        headers = self._get_headers()
        logger.debug("POST {} model={}", url, request.model)
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
        self._raise_for_status(response)
        return self._parse_http_response(response.json())


class AnthropicProvider(LLMProvider):
    """Anthropic Messages API 提供商。

    内部自动完成 OpenAI 消息格式 ↔ Anthropic 消息格式的双向转换：
    请求时将 system 消息提取到顶层、响应时将 ``content[0].text``
    和 ``usage.{input,output}_tokens`` 映射为统一 ChatResponse。
    """

    def _get_chat_endpoint(self) -> str:
        return "/messages"

    def _get_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def _build_http_payload(self, request: ChatRequest) -> dict[str, Any]:
        system_parts: list[str] = []
        messages: list[dict[str, str]] = []
        for m in request.messages:
            if m.role == "system":
                system_parts.append(m.content)
            else:
                messages.append({"role": m.role, "content": m.content})
        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "messages": messages,
        }
        if system_parts:
            payload["system"] = "\n".join(system_parts)
        if request.temperature != 0.7:
            payload["temperature"] = request.temperature
        if request.top_p != 1.0:
            payload["top_p"] = request.top_p
        if request.stream:
            payload["stream"] = True
        return payload

    def _parse_http_response(self, data: dict[str, Any]) -> ChatResponse:
        text = ""
        for block in data.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                break
        u = data.get("usage", {})
        pt = u.get("input_tokens", 0)
        ct = u.get("output_tokens", 0)
        return ChatResponse(
            content=text,
            usage=Usage(prompt_tokens=pt, completion_tokens=ct,
                        total_tokens=pt + ct),
            finish_reason=data.get("stop_reason"),
        )

    def chat(self, request: ChatRequest) -> ChatResponse:
        url = f"{self.config.base_url}{self._get_chat_endpoint()}"
        payload = self._build_http_payload(request)
        headers = self._get_headers()
        logger.debug("POST {} model={}", url, request.model)
        with httpx.Client(timeout=self.config.timeout) as client:
            response = client.post(url, json=payload, headers=headers)
        self._raise_for_status(response)
        return self._parse_http_response(response.json())

    async def achat(self, request: ChatRequest) -> ChatResponse:
        url = f"{self.config.base_url}{self._get_chat_endpoint()}"
        payload = self._build_http_payload(request)
        headers = self._get_headers()
        logger.debug("POST {} model={}", url, request.model)
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
        self._raise_for_status(response)
        return self._parse_http_response(response.json())


# ---------------------------------------------------------------------------
# CLI 测试入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("LLM 模型客户端 测试")
    logger.info("=" * 50)

    # 1 —— DeepSeek quick_chat
    try:
        cfg = ProviderConfig.from_provider_name(ProviderName.DEEPSEEK)
        ds = OpenAICompatibleProvider(cfg)
        resp = ds.quick_chat("用一句话介绍什么是 AI Agent。")
        u = resp.usage or Usage()
        logger.info(
            "DeepSeek quick_chat: content={!r}, "
            "tokens(prompt={}, completion={}, total={}), finish={}",
            resp.content[:100], u.prompt_tokens,
            u.completion_tokens, u.total_tokens, resp.finish_reason,
        )
    except Exception as exc:
        logger.error("DeepSeek quick_chat 测试失败: {}", exc)

    # 2 —— chat_retry（重试逻辑）
    try:
        cfg = ProviderConfig.from_provider_name(ProviderName.DEEPSEEK)
        ds = OpenAICompatibleProvider(cfg)
        req = ChatRequest(
            messages=[Message(role="user", content="1+1等于几？")],
            model=cfg.default_model, temperature=0.0,
        )
        resp = ds.chat_retry(req, retries=3, base_delay=1.0)
        logger.info("chat_retry 成功: {!r}", resp.content[:80])
    except Exception as exc:
        logger.error("chat_retry 测试失败: {}", exc)

    # 3 —— Anthropic（仅当 .env 配置了 ANTHROPIC_API_KEY 时测）
    try:
        acfg = ProviderConfig.from_provider_name(ProviderName.ANTHROPIC)
        ani = AnthropicProvider(acfg)
        resp = ani.quick_chat(
            "Say hello in one sentence.", system="Be concise."
        )
        logger.info("Anthropic: {!r}", resp.content[:80])
    except LLMClientError as exc:
        logger.warning("Anthropic 测试跳过（未配置或连接失败）: {}", exc)
    except Exception as exc:
        logger.error("Anthropic 测试异常: {}", exc)

    logger.info("=" * 50)
    logger.info("测试完成")

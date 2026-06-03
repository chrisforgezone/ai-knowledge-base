"""统一 LLM 客户端 — 工厂模式封装多模型调用

支持 DeepSeek、Qwen、OpenAI、Anthropic，通过环境变量切换。
返回统一格式：LLMResponse dataclass（content + Usage 用量统计）
"""

from __future__ import annotations

import os
import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── 数据结构 ──────────────────────────────────────────────────


@dataclass
class Usage:
    """Token 用量统计"""
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class LLMResponse:
    """统一的 LLM 响应格式"""
    content: str
    usage: Usage = field(default_factory=Usage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "usage": self.usage.to_dict(),
        }


# ── 成本估算（每 1K tokens 价格，单位 USD） ──────────────────

PRICING: dict[str, dict[str, float]] = {
    "deepseek-v4-pro": {"input": 0.00027, "output": 0.0011},
    "qwen-plus": {"input": 0.002, "output": 0.006},
    "gpt-4.5": {"input": 0.00015, "output": 0.0006},
    "claude-sonnet-4-6": {"input": 0.003, "output": 0.015},
}


def estimate_cost(model: str, usage: Usage) -> float:
    """估算单次调用成本（USD）"""
    prices = PRICING.get(model, {"input": 0.002, "output": 0.006})
    return (
        usage.prompt_tokens / 1000 * prices["input"]
        + usage.completion_tokens / 1000 * prices["output"]
    )


# ── CostTracker ───────────────────────────────────────────────

class CostTracker:
    """Token 消耗跟踪与成本估算。

    按模型记录每次 LLM 调用的输入/输出 token，
    根据美元/百万 token 定价累计成本（单位：USD）。
    定价与 PROVIDER_CONFIG 中的 default_model 一一对应。

    Usage:
        tracker = CostTracker()
        tracker.record(usage, model="deepseek-v4-pro")
        tracker.report()
    """

    _PRICING_USD_PER_M: dict[str, dict[str, float]] = {
        "deepseek-v4-pro": {"input": 0.27, "output": 1.10},
        "qwen-plus": {"input": 2.0, "output": 6.0},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    }

    def __init__(self) -> None:
        self._calls: list[dict[str, Any]] = []

    def record(self, usage: Usage, model: str) -> None:
        """记录一次 API 调用的 token 消耗。

        Args:
            usage: Usage 对象（prompt_tokens / completion_tokens）
            model: 模型名称（如 deepseek-v4-pro / gpt-4o-mini）
        """
        prices = self._PRICING_USD_PER_M.get(
            model, {"input": 2.0, "output": 8.0}
        )
        input_cost = usage.prompt_tokens / 1_000_000 * prices["input"]
        output_cost = usage.completion_tokens / 1_000_000 * prices["output"]
        self._calls.append({
            "model": model,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "cost_usd": input_cost + output_cost,
        })

    def estimated_cost(self, model: str | None = None) -> float:
        """返回估算成本（USD）。

        Args:
            model: 模型名称，为 None 时返回全部模型合计。
        """
        calls = self._calls if model is None else [
            c for c in self._calls if c["model"] == model
        ]
        total_usd = sum(c["cost_usd"] for c in calls)
        return round(total_usd, 6)

    def report(self, model: str | None = None) -> None:
        """打印成本报告（USD）。

        Args:
            model: 模型名称，为 None 时打印全部。
        """
        calls = self._calls if model is None else [
            c for c in self._calls if c["model"] == model
        ]
        if not calls:
            logger.info("CostTracker: 暂无调用记录")
            return

        from collections import defaultdict

        agg: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"calls": 0, "prompt": 0, "completion": 0, "cost_usd": 0.0}
        )
        for c in calls:
            m = c["model"]
            agg[m]["calls"] += 1
            agg[m]["prompt"] += c["prompt_tokens"]
            agg[m]["completion"] += c["completion_tokens"]
            agg[m]["cost_usd"] += c["cost_usd"]

        total_calls = sum(a["calls"] for a in agg.values())
        total_prompt = sum(a["prompt"] for a in agg.values())
        total_completion = sum(a["completion"] for a in agg.values())
        total_usd = sum(a["cost_usd"] for a in agg.values())

        lines = [
            "=" * 72,
            "  LLM Cost Report (USD)",
            "=" * 72,
            f"{'Model':<28} {'Calls':>6} {'Prompt':>10} {'Completion':>12} {'Cost(USD)':>12}",
            "-" * 72,
        ]
        for m in sorted(agg.keys()):
            a = agg[m]
            lines.append(
                f"{m:<28} {a['calls']:>6} {a['prompt']:>10,} {a['completion']:>12,} "
                f"{a['cost_usd']:>12.6f}"
            )
        lines.append("-" * 72)
        lines.append(
            f"{'TOTAL':<28} {total_calls:>6} {total_prompt:>10,} {total_completion:>12,} "
            f"{total_usd:>12.6f}"
        )
        lines.append("=" * 72)

        for line in lines:
            logger.info(line)


# ── Provider 抽象基类 ────────────────────────────────────────


class LLMProvider(ABC):
    """LLM 提供商抽象基类"""

    def __init__(self, api_key: str, base_url: str, model: str, provider_name: str = ""):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.provider_name = provider_name
        self.client = httpx.Client(timeout=60.0)

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> LLMResponse:
        """发送聊天请求，返回统一格式响应"""
        ...

    def close(self) -> None:
        self.client.close()


class OpenAICompatibleProvider(LLMProvider):
    """兼容 OpenAI Chat Completions API 的提供商。"""

    def chat(self, messages, temperature=0.7, max_tokens=2000) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        resp = self.client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        content = data["choices"][0]["message"]["content"]
        usage_data = data.get("usage", {})
        usage = Usage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
        )
        return LLMResponse(content=content, usage=usage)


class AnthropicProvider(LLMProvider):
    """Anthropic Claude Messages API 提供商。

    API 文档: https://docs.anthropic.com/en/api/messages
    """

    def chat(self, messages, temperature=0.7, max_tokens=2000) -> LLMResponse:
        system_content = ""
        api_messages: list[dict[str, str]] = []
        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            else:
                api_messages.append({"role": msg["role"], "content": msg["content"]})

        url = f"{self.base_url}/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": api_messages,
        }
        if system_content:
            payload["system"] = system_content
        if temperature > 0:
            payload["temperature"] = temperature

        resp = self.client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        content = data["content"][0]["text"]
        usage_data = data.get("usage", {})
        usage = Usage(
            prompt_tokens=usage_data.get("input_tokens", 0),
            completion_tokens=usage_data.get("output_tokens", 0),
        )
        return LLMResponse(content=content, usage=usage)


# ── 工厂函数 ─────────────────────────────────────────────────

PROVIDER_CONFIG: dict[str, dict[str, Any]] = {
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url_env": "DEEPSEEK_BASE_URL",
        "model_env": "DEEPSEEK_MODEL",
        "default_base_url": "https://api.deepseek.com",
        "default_model": "deepseek-v4-pro",
    },
    "qwen": {
        "api_key_env": "QWEN_API_KEY",
        "base_url_env": "QWEN_BASE_URL",
        "model_env": "QWEN_MODEL",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
    },
    "openai": {
        "api_key_env": "OPENAI_API_KEY",
        "base_url_env": "OPENAI_BASE_URL",
        "model_env": "OPENAI_MODEL",
        "default_base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4.5",
    },
    "anthropic": {
        "type": "anthropic",
        "api_key_env": "ANTHROPIC_API_KEY",
        "base_url_env": "ANTHROPIC_BASE_URL",
        "model_env": "ANTHROPIC_MODEL",
        "default_base_url": "https://api.anthropic.com",
        "default_model": "claude-sonnet-4-6",
    },
}


def create_provider(provider_name: str | None = None) -> LLMProvider:
    """工厂函数：根据提供商名称创建对应的 LLM 客户端。

    Args:
        provider_name: 提供商名称（deepseek/qwen/openai/anthropic），
                       默认读取环境变量 LLM_PROVIDER

    Returns:
        LLMProvider 实例
    """
    name = (provider_name or os.getenv("LLM_PROVIDER", "deepseek")).lower()
    if name not in PROVIDER_CONFIG:
        raise ValueError(f"未知的模型提供商: {name}")

    config = PROVIDER_CONFIG[name]
    api_key = os.getenv(config["api_key_env"], "")
    if not api_key:
        raise RuntimeError(f"缺少 API Key，请设置环境变量: {config['api_key_env']}")

    base_url = os.getenv(config["base_url_env"], config["default_base_url"])
    model = os.getenv(config["model_env"], config["default_model"])

    logger.info("创建 LLM 客户端: provider=%s, model=%s", name, model)

    if config.get("type") == "anthropic":
        return AnthropicProvider(api_key=api_key, base_url=base_url, model=model, provider_name=name)
    return OpenAICompatibleProvider(api_key=api_key, base_url=base_url, model=model, provider_name=name)


# ── CostTracker 工厂 ──────────────────────────────────────────

def create_tracker(provider_name: str | None = None) -> CostTracker:
    """创建 CostTracker 实例。

    Args:
        provider_name: LLM 提供商名称（deepseek/qwen/openai/anthropic），
                       None 时读取环境变量 LLM_PROVIDER（默认 deepseek）

    Returns:
        新创建的 CostTracker 实例
    """
    name = (provider_name or os.getenv("LLM_PROVIDER", "deepseek")).lower()
    logger.info("创建 CostTracker: provider=%s", name)
    return CostTracker()


# ── 带重试的调用封装 ──────────────────────────────────────────


def chat_with_retry(
    provider: LLMProvider,
    messages: list[dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int = 2000,
    max_retries: int = 3,
    backoff_base: float = 2.0,
    tracker: CostTracker | None = None,
) -> LLMResponse:
    """带指数退避重试的聊天调用。

    Args:
        tracker: 可选的 CostTracker，传入后自动记录每次成功调用。
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            response = provider.chat(messages=messages, temperature=temperature, max_tokens=max_tokens)
            if attempt > 0:
                logger.info("第 %d 次重试成功", attempt)
            if tracker is not None:
                tracker.record(response.usage, provider.model)
            return response
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
            last_error = e
            if attempt < max_retries - 1:
                wait_time = backoff_base ** attempt
                logger.warning("LLM 调用失败（第 %d/%d 次），%0.1fs 后重试: %s", attempt + 1, max_retries, wait_time, e)
                time.sleep(wait_time)
            else:
                logger.error("LLM 调用失败，已达最大重试次数: %s", e)
    raise last_error


# ── 便捷函数 ─────────────────────────────────────────────────


def quick_chat(
    prompt: str,
    system: str = "你是一个 AI 技术分析助手。",
    provider_name: str | None = None,
) -> str:
    """快捷调用：一句话调用 LLM，返回纯文本。"""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    provider = create_provider(provider_name)
    try:
        tracker = create_tracker(provider_name)
        response = chat_with_retry(provider, messages, tracker=tracker)
        cost = estimate_cost(provider.model, response.usage)
        logger.info(
            "Token 用量: %d (prompt) + %d (completion) = %d, 估算成本: $%.6f",
            response.usage.prompt_tokens, response.usage.completion_tokens,
            response.usage.total_tokens, cost,
        )
        tracker.report()
        return response.content
    finally:
        provider.close()


def chat(
    prompt: str,
    system: str = "你是一个 AI 技术分析助手。",
    provider: str | None = None,
    max_retries: int = 3,
) -> dict[str, Any]:
    """
    便捷调用 LLM，返回包含 content 和 usage 的字典。

    Args:
        prompt: 用户提示词
        system: 系统提示词
        provider: 提供商名称（deepseek/qwen/openai/anthropic），默认读环境变量
        max_retries: 最大重试次数

    Returns:
        {"content": str, "usage": {"prompt_tokens": int, ...}}
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    provider_name = provider or os.getenv("LLM_PROVIDER", "deepseek")
    llm = create_provider(provider_name)
    try:
        response = chat_with_retry(llm, messages, max_retries=max_retries)
        return response.to_dict()
    finally:
        llm.close()


# ── CLI 测试入口 ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print("=== LLM 客户端测试 ===")
    model = os.getenv('LLM_PROVIDER', 'deepseek')
    print(f"提供商: {model}")
    try:
        result = quick_chat("用一句话介绍什么是 AI Agent。")
        print(f"\n回复: {result}")
    except Exception as e:
        print(f"\n错误: {e}")
        print("请检查 .env 文件中的 API Key 配置。")

"""LLM 客户端自定义异常层次。"""


class LLMClientError(Exception):
    """LLM 客户端统一异常基类。"""


class LLMConnectionError(LLMClientError):
    """网络连接失败或服务端错误（5xx）。"""


class LLMRateLimitError(LLMClientError):
    """API 限流（429）。"""


class LLMAuthenticationError(LLMClientError):
    """鉴权失败（401 / 403）。"""


class LLMBadRequestError(LLMClientError):
    """请求参数错误（4xx）。"""


class LLMMaxRetriesExceededError(LLMClientError):
    """重试次数耗尽。"""

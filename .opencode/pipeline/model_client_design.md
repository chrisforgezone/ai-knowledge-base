# Model Client 设计文档

## 1. 概述

`model_client.py` 提供统一的 LLM 调用抽象层，支持 DeepSeek、Qwen、MiniMax、OpenAI、Anthropic 五家模型，通过 `.env` / 系统环境变量实现零代码切换。

## 2. 文件清单

```
.opencode/pipeline/
├── exceptions.py        # LLM 异常层次（6 个异常类）
└── model_client.py      # Provider ABC + 具体实现 + CLI 测试入口
```

## 3. 类图

```
┌─────────────────────────────────────────────────┐
│              StrEnum: ProviderName               │
│  DEEPSEEK‧QWEN‧MINIMAX‧OPENAI‧ANTHROPIC         │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│  @pydantic.dataclass            @pydantic.dataclass     │
│  Message                        Usage                  │
│  ├── role: Literal["system",    ├── prompt_tokens       │
│  │     "user", "assistant"]     ├── completion_tokens   │
│  └── content: str               └── total_tokens        │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│  @pydantic.dataclass                            │
│  ChatRequest                                    │
│  ├── messages: list[Message]                    │
│  ├── model: str                                 │
│  ├── temperature: float  = 0.7                  │
│  ├── max_tokens: int     = 4096                 │
│  ├── top_p: float        = 1.0                  │
│  └── stream: bool        = False                │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│  @pydantic.dataclass                            │
│  ChatResponse                                   │
│  ├── content: str                               │
│  ├── usage: Usage | None                        │
│  └── finish_reason: str | None                  │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│  Pydantic BaseModel: ProviderConfig              │
│  ├── name: ProviderName                         │
│  ├── api_key: str                               │
│  ├── base_url: str                              │
│  ├── default_model: str                         │
│  └── timeout: float = 60.0                      │
│                                                 │
│  + from_provider_name(name) @classmethod         │
│    → 读 os.getenv("{PREFIX}_API_KEY")            │
│      os.getenv("{PREFIX}_BASE_URL", default)     │
│      os.getenv("{PREFIX}_MODEL", default)        │
└─────────────────────────────────────────────────┘

        ┌──────────────────────────────┐
        │     ABC LLMProvider          │
        ├──────────────────────────────┤
        │ + config: ProviderConfig     │
        ├──────────────────────────────┤
        │ # abstract（子类实现）        │
        │   chat(req)   -> ChatResponse│
        │   achat(req)  -> ChatResponse│
        │   _build_http_payload(req)   │
        │   _parse_http_response(data) │
        │   _get_headers()             │
        │   _get_chat_endpoint()       │
        ├──────────────────────────────┤
        │ # concrete（模板方法）        │
        │   quick_chat(prompt, **kw)   │
        │   chat_retry(req, retries=3) │
        │   _should_retry(exc) @static │
        │   _raise_for_status(resp)    │
        └──────┬───────────┬───────────┘
               │           │
 ┌─────────────▼──┐  ┌────▼──────────────┐
 │ OpenAICompatible│  │ AnthropicProvider  │
 │ Provider        │  │                    │
 ├─────────────────┤  ├────────────────────┤
 │ endpoint:       │  │ endpoint:          │
 │  /chat/complet  │  │  /messages         │
 │ headers:        │  │ headers:           │
 │  Bearer token   │  │  x-api-key +       │
 │                 │  │  anthropic-version │
 │ 适用:           │  ├────────────────────┤
 │  OpenAI         │  │ 请求转换:          │
 │  DeepSeek       │  │  system → 顶层字段  │
 │  Qwen(DashScope)│  │  user/assistant →  │
 │  MiniMax        │  │  不变               │
 │                 │  ├────────────────────┤
 │                 │  │ 响应转换:          │
 │                 │  │  content[0].text   │
 │                 │  │   → ChatResponse   │
 │                 │  │  usage.{input,     │
 │                 │  │   output}_tokens   │
 │                 │  │   → Usage           │
 │                 │  │  stop_reason       │
 │                 │  │   → finish_reason  │
 └─────────────────┘  └────────────────────┘
```

## 4. 数据流 (quick_chat)

```
调用方                  LLMProvider.quick_chat()       .chat()        httpx
  │                           │                         │              │
  │ provider.quick_chat(      │                         │              │
  │   "你好")                 │                         │              │
  │──────────────────────────►│                         │              │
  │                           │                         │              │
  │                           │ 构建 ChatRequest:       │              │
  │                           │  messages=[{role:user,  │              │
  │                           │   content:"你好"}]       │              │
  │                           │  model=default_model    │              │
  │                           │                         │              │
  │                           │ self.chat(request)      │              │
  │                           │────────────────────────►│              │
  │                           │                         │              │
  │                           │                         │ _build_http_payload()
  │                           │                         │ → HTTP JSON  │
  │                           │                         │ _get_headers()→│
  │                           │                         │ POST url     │
  │                           │                         │─────────────►│
  │                           │                         │              │
  │                           │                         │  HTTP 200    │
  │                           │                         │◄─────────────│
  │                           │                         │              │
  │                           │                         │ _raise_for_status()
  │                           │                         │ _parse_http_response()
  │                           │                         │ → ChatResponse
  │                           │                         │              │
  │                           │    ChatResponse         │              │
  │                           │◄────────────────────────│              │
  │                           │                         │              │
  │    ChatResponse           │                         │              │
  │◄──────────────────────────│                         │              │
```

## 5. chat_retry 重试策略

```
初始请求
  │
  ├─ 成功 → 返回 ChatResponse
  │
  └─ 抛出异常
       │
       ├─ _should_retry(exc) = False (401/403/400)
       │    → 直接 raise，不重试
       │
       └─ _should_retry(exc) = True (NetworkError/5xx/429)
            │
            ├─ 第 1 次重试: 等待 base_delay * 2^0 = 1s  → 成功则返回
            ├─ 第 2 次重试: 等待 base_delay * 2^1 = 2s  → 成功则返回
            └─ 第 3 次重试: 等待 base_delay * 2^2 = 4s  → 成功则返回
                                                         失败 → LLMMaxRetriesExceededError
```

最多 4 次请求（1 初始 + 3 重试），最小等待总时长（全失败时） = 1+2+4 = 7s。

## 6. Anthropic 格式转换

### 6.1 请求转换: OpenAI → Anthropic

```
OpenAI ChatRequest                         Anthropic /messages body
─────────────────────                      ─────────────────────────
messages: [                                {
  {role: "system", content: "你是助手"},      "model": "claude-sonnet-4-6",
  {role: "user",   content: "你好"},          "max_tokens": 4096,
  {role: "assistant", content: "你好！"},      "system": "你是助手",
  {role: "user",   content: "介绍AI"}         "messages": [
]                                               {"role": "user",   "content": "你好"},
temperature: 0.7                               {"role": "assistant", "content": "你好！"},
max_tokens: 4096                                {"role": "user",   "content": "介绍AI"}
                                              ],
                                              "temperature": 0.7
                                            }
```

**规则**:
1. 所有 `role="system"` 的消息被提取，拼接后放入顶层 `system` 字段。
2. `user` 和 `assistant` 消息原样保留。
3. `temperature` 仅在 != 0.7 时发送（减少噪音）。
4. `top_p` 仅在 != 1.0 时发送。

### 6.2 响应转换: Anthropic → ChatResponse

```
Anthropic 响应                               ChatResponse
─────────────                               ─────────────
{                                           ChatResponse(
  "id": "msg_xxx",                              content="AI即人工智能...",
  "content": [                                  usage=Usage(
    {"type": "text", "text": "AI即人工智能..."},   prompt_tokens=10,
  ],                                              completion_tokens=50,
  "stop_reason": "end_turn",                      total_tokens=60),
  "usage": {                                    finish_reason="end_turn"
    "input_tokens": 10,                       )
    "output_tokens": 50
  }
}
```

**规则**:
1. 取 `content` 数组中类型为 `"text"` 的第一个块的文本。
2. `usage.input_tokens` → `Usage.prompt_tokens`
3. `usage.output_tokens` → `Usage.completion_tokens`
4. `total_tokens = input_tokens + output_tokens`
5. `stop_reason` → `finish_reason`

## 7. 异常体系

```
LLMClientError (基类)
├── LLMConnectionError          # 网络连接失败、5xx
├── LLMRateLimitError           # 429
├── LLMAuthenticationError      # 401 / 403
├── LLMBadRequestError          # 400
└── LLMMaxRetriesExceededError  # 重试 3 次后仍失败
```

HTTP 状态码 → 异常映射由 `LLMProvider._raise_for_status()` 统一处理。

## 8. 配置加载流程

```
ProviderConfig.from_provider_name("deepseek")
  │
  ├── 解析 name → ProviderName.DEEPSEEK
  ├── 查表 _PROVIDER_DEFAULTS[DEEPSEEK]
  │   → base_url="https://api.deepseek.com/v1"
  │   → model="deepseek-chat"
  │
  ├── os.getenv("DEEPSEEK_API_KEY")   → 必填，缺失则 raise LLMClientError
  ├── os.getenv("DEEPSEEK_BASE_URL")  → 可选，回退到 defaults["base_url"]
  ├── os.getenv("DEEPSEEK_MODEL")     → 可选，回退到 defaults["model"]
  │
  └── return ProviderConfig(
        name=DEEPSEEK,
        api_key="sk-xxx",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
      )
```

模块顶层执行 `load_dotenv()` 一次，将 `.env` 文件注入 `os.environ`，后续 `os.getenv()` 可读取。

## 9. 环境变量契约

| 变量 | 必填 | 默认值 | 适用 Provider |
|------|------|--------|--------------|
| `DEEPSEEK_API_KEY` | 是 | - | deepseek |
| `DEEPSEEK_BASE_URL` | 否 | `https://api.deepseek.com/v1` | deepseek |
| `DEEPSEEK_MODEL` | 否 | `deepseek-chat` | deepseek |
| `QWEN_API_KEY` | 是 | - | qwen |
| `QWEN_BASE_URL` | 否 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | qwen |
| `QWEN_MODEL` | 否 | `qwen-plus` | qwen |
| `MINIMAX_API_KEY` | 是 | - | minimax |
| `MINIMAX_BASE_URL` | 否 | `https://api.minimax.chat/v1` | minimax |
| `MINIMAX_MODEL` | 否 | `abab6.5s-chat` | minimax |
| `OPENAI_API_KEY` | 是 | - | openai |
| `OPENAI_BASE_URL` | 否 | `https://api.openai.com/v1` | openai |
| `OPENAI_MODEL` | 否 | `gpt-4o` | openai |
| `ANTHROPIC_API_KEY` | 是 | - | anthropic |
| `ANTHROPIC_BASE_URL` | 否 | `https://api.anthropic.com/v1` | anthropic |
| `ANTHROPIC_MODEL` | 否 | `claude-sonnet-4-20250514` | anthropic |

## 10. 使用示例

```python
from pipeline.model_client import (
    ChatRequest, ChatResponse, Message, Usage,
    ProviderConfig, ProviderName,
    OpenAICompatibleProvider, AnthropicProvider,
)

# 方式 1: 一句话调用
deepseek = OpenAICompatibleProvider(
    ProviderConfig.from_provider_name("deepseek")
)
resp: ChatResponse = deepseek.quick_chat("一句话介绍AI Agent")
print(resp.content)

# 方式 2: 手动构造 ChatRequest + 重试
request = ChatRequest(
    messages=[Message(role="user", content="解释量子计算")],
    model="deepseek-chat", temperature=0.0,
)
resp = deepseek.chat_retry(request, retries=3, base_delay=1.0)

# 方式 3: 异步调用
resp = await deepseek.achat(request)

# 方式 4: Anthropic
claude = AnthropicProvider(
    ProviderConfig.from_provider_name("anthropic")
)
resp = claude.quick_chat("Hello!", system="Be helpful.")
```

## 11. 设计决策记录

| 决策 | 选择 | 原因 |
|------|------|------|
| Anthropic 方案 | 独立 Provider + 格式转换 | 不依赖外部代理，自包含 |
| 传输对象类型 | `@pydantic.dataclass` | 兼有 dataclass 轻量 + Pydantic 校验 |
| quick_chat / chat_retry | 实例方法 | 与 ProviderConfig 自然绑定 |
| ChatResponse 不含 model | 是 | 调用方已知道 model；减少冗余 |
| HTTP 客户端生命周期 | 每次调用创建新 Client | 避免连接池状态问题，简化实现 |
| 配置读取 | `dotenv` + `os.getenv` | 与项目现有 `.env` 机制一致 |
| 重试实现 | 自定义循环 | 更精确的异常分类控制 |

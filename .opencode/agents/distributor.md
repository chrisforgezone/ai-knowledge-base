# Distributor Agent

## 角色

分发 Agent，负责将 Organizer 整理后的 Top 10 知识条目通过 Telegram 和飞书两个渠道并行推送给订阅者。

分发 Agent 是管线的末端节点，执行完毕管线即结束。

## 输入

通过 LangGraph state 从 Organizer 接收分发摘要：

```python
class BaseEntry(BaseModel):
    id: str
    title: str
    source: Literal["github_trending", "hacker_news"]
    source_url: str
    summary: str
    tags: list[str]
    relevance_score: float
    stars: int | None

class DistributionSummary(BaseModel):
    generated_at: datetime
    date: str
    total_new: int
    top_10: list[BaseEntry]
```

不直接读取文件系统。

## 工作职责

1. 从 pipeline state 获取 `DistributionSummary`
2. 若 `total_new == 0`，静默跳过，记 `logger.info("今日无新知识条目，跳过分发")`
3. 按 `relevance_score` 降序取 Top 10，动态拆批（每批 ≤ 5 条，预留字符安全余量）
4. 通过 `asyncio.gather` 并行推送到 Telegram 和飞书
5. 两渠道同一批次间间隔 3 秒（避免 rate limit）
6. 回写分发结果到 pipeline state

**只推送，不修改知识库数据。**

## 允许权限

| 权限 | 范围 | 说明 |
|------|------|------|
| `api:telegram` | `api.telegram.org` | 调用 Telegram Bot API 发送消息 |
| `api:feishu` | 飞书 Webhook URL | 调用飞书机器人 Webhook 发送消息 |
| `config:read` | `src/config.py` | 读取 Telegram Bot Token 和飞书 Webhook URL（通过 pydantic-settings 注入） |

## 禁止权限

| 禁止项 | 原因 |
|--------|------|
| 访问 `knowledge/raw/` | 原始数据只读权归 Collector |
| 访问 `knowledge/articles/` | 知识库读写权归 Organizer |
| 调用 DeepSeek API | 分析权归 Analyzer |
| 修改 pipeline state 中非分发结果字段 | 数据边界 |
| 硬编码 Telegram Token / 飞书 Webhook URL | 安全红线 §8.1 |

---

## 消息格式

### Telegram（Markdown 格式）

每条消息体 ≤ 3500 字符（预留余量），超限则动态拆为更多批次。

```
📰 AI 知识日报 | 2026-05-21 (第 1/2 批)

1. 🔗 [Autogen：微软的多 Agent 协作框架](https://github.com/microsoft/autogen)
   🏷 GitHub | ★9.2 | #Multi-Agent #Framework
   📝 微软发布的 AutoGen 框架支持多 Agent 协作，通过 Conversation-Driven 方式...

2. 🔗 [Show HN: 开源 LLM 推理优化工具](https://github.com/example/llm-tuner)
   🏷 Hacker News | ★8.7 | #LLM #Inference #Optimization
   📝 一个开源的 LLM 推理优化工具，支持量化、KV-cache 等多项技术...

3. ...
```

**格式规则：**
- 标题使用 `[text](source_url)` Markdown 链接语法，Telegram 可点击
- `🏷` 后跟来源标识（`GitHub` / `Hacker News`）和评分（`★N.N`）
- 标签以 `#tag` 展示
- 摘要截断到 120 字符，末尾用 `...`
- 批次标识 `(第 N/M 批)`：1–5 条标 `(第 1/1 批)`，6–10 条标 `(第 1/2 批)` `(第 2/2 批)`
- 当 `total_new < 5` 时，动态标 `(第 1/1 批)`

### 飞书（交互式富文本卡片）

飞书发送 `interactive` 类型卡片消息：

```json
{
  "msg_type": "interactive",
  "card": {
    "header": {
      "title": {
        "tag": "plain_text",
        "content": "📰 AI 知识日报 | 2026-05-21 (1/2)"
      },
      "template": "blue"
    },
    "elements": [
      {
        "tag": "div",
        "fields": [
          {
            "tag": "lark_md",
            "content": "**1. [Autogen：微软的多 Agent 协作框架](https://github.com/microsoft/autogen)**\n🏷 GitHub | ★9.2 | #Multi-Agent #Framework\n📝 微软发布的 AutoGen 框架支持多 Agent 协作，通过 Conversation-Driven 方式..."
          }
        ]
      }
    ],
    "note": {
      "tag": "plain_text",
      "content": "共 Top 10 条新知识条目 | 由 AI Knowledge Base 自动生成"
    }
  }
}
```

**格式规则：**
- 卡片标题使用 `template: "blue"`
- 每条条目一个 `div` block，内容使用 `lark_md` 标签（支持 Markdown 链接）
- 标题带 `[text](source_url)` Markdown 链接，飞书内可点击跳转
- `🏷` 后跟来源标识和评分，标签以 `#tag` 展示
- `📝` 摘要截断到 120 字符
- 卡片 `note` 底部标注总条数和生成来源
- 飞书同样分批（每批 ≤ 5 条），批次间隔 3 秒

---

## 推送策略

| 项目 | 策略 |
|------|------|
| 渠道顺序 | 并行（`asyncio.gather`），互不阻塞 |
| 批次大小 | 动态计算，≤ 5 条/批，单条消息 ≤ 3500 字符 |
| 批次间隔 | 3 秒（同一渠道内） |
| total_new = 0 | 静默跳过，不发消息 |
| 11+ 条目 | 只推 Top 10，其余静默写入知识库 |

### 动态拆批算法

1. 按 `relevance_score` 降序取 Top 10
2. 逐条拼装消息文本，累积字符数达 3500 时截断当前批次，开启新批次
3. 每批条目数上限 5 条（即使 3500 字符未满也不敢超过 5 条）
4. 计算批次总数 M，每批内条目数可能不同

---

## 错误处理

| 异常类型 | 处理方式 |
|----------|---------|
| 网络超时 | Telegram 10s、飞书 15s 超时；重试该渠道该批次 1 次（指数退避 3s → 6s），仍失败则放弃该渠道全部批次 |
| HTTP 非 2xx | Telegram 看 `description` 字段定位错误原因；飞书看 `msg` 字段。重试 1 次（同上），仍失败则放弃该渠道 |
| 飞书卡片 JSON schema 校验失败 | 重试 1 次（同批次重建 JSON），仍失败则放弃飞书渠道 |
| 单渠道全部失败 | 记 `logger.error("渠道 {name} 分发失败: {reason}")`，另一渠道不受影响 |
| 两渠道全部失败 | 记 `logger.error("所有分发渠道均失败")`，管线不阻断 |
| state 中 `top_10` 为 null 或 `total_new < 0` | 阻断管线，记 `logger.error` |
| config 缺少必需配置 | 缺哪个跳过哪个渠道，记 `logger.error` |

---

## 分发结果回写

distributor 执行完毕后回写 state：

```json
{
  "distribution_result": {
    "telegram": {
      "status": "success",
      "sent_count": 10,
      "batches": 2,
      "error": null
    },
    "feishu": {
      "status": "error",
      "sent_count": 0,
      "batches": 0,
      "error": "Webhook 返回 500"
    }
  }
}
```

| 字段 | 说明 |
|------|------|
| `status` | `success` / `partial`（部分批次失败）/ `error`（全部失败）/ `skipped`（配置缺失） |
| `sent_count` | 实际成功发送的条目数 |
| `batches` | 实际发送的批次数 |
| `error` | 失败原因，成功时为 null |

---

## 质量自查清单

| # | 检查项 | 不通过时 |
|---|--------|---------|
| 1 | state 中 `top_10` 不为 null，`total_new` ≥ 0 | 阻断管线 |
| 2 | Telegram Bot Token 和飞书 Webhook URL 从 config 读取非空 | 缺少哪个跳过哪个渠道 |
| 3 | 每条消息体 ≤ 4096 字符（Telegram API limit） | 动态拆批，不发送超长消息 |
| 4 | HTTP 响应状态码为 2xx | 重试 1 次（指数退避），仍失败则放弃该渠道 |
| 5 | 飞书卡片 JSON 结构通过飞书 schema 校验 | 重试 1 次，仍失败放弃飞书渠道 |
| 6 | 同一渠道所有批次全部发送成功 | 任一失败则标记该渠道失败 |
| 7 | 至少一个渠道成功或 `total_new == 0` | 两渠道全失败且 total_new > 0 时记 error，不阻断 |
| 8 | `sent_count` 与 `top_10` 数量一致（每条都推送了） | 记 warning |

# AI 知识库 · 编码规范 v1.0

## TL;DR

- **要做什么**: PEP 8 + 类型标注 + Google 风格 docstring + loguru 日志
- **不做什么**: 魔法字符串 / 裸 print / 裸 except / TODO 进入 main / 硬编码密钥
- **边界 & 验收**: 分支覆盖率 ≥ 80%, 单文件 ≤ 300 行, ruff + mypy + pytest 全绿
- **怎么验证**: CI 三步走 (ruff → mypy → pytest --cov)

---

## 1. 命名规范

- 变量/函数/模块名：`snake_case`（模块名全小写，单词间用 `_`）
- 类名：`PascalCase`
- 常量：`UPPER_SNAKE_CASE`
- 禁止单字母变量（循环变量 `i`、`j` 除外），禁止拼音命名
- ruff 规则 `N`（pep8-naming）开启自动检查

## 2. 类型与函数签名

- 所有函数签名必须包含完整类型标注（参数 + 返回值）
- mypy 检查时使用 `--disallow-untyped-defs`
- `_` 私有函数同样要求标注
- 第三方库缺少 stub 时可以在函数上方 `# type: ignore[no-untyped-call]`

## 3. 文档字符串

- 所有公开函数/类使用 Google 风格 docstring
- 必须包含 `Args:` / `Returns:` / `Raises:`（无参数/无异常时写 `None`）
- `_` 前缀函数和 `__init__.py` 中的 re-export 可以豁免
- `@property` 只需一行描述

## 4. 魔法字符串

- 状态值、来源名、渠道名等枚举型字符串统一用 `StrEnum` 定义，集中放在对应模块的 `constants.py` 或模型文件中
- API URL / Webhook URL 从 `config.py` 的 `pydantic-settings` 注入，禁止硬编码
- 日志消息、异常消息不在此列

## 5. 日志

- 所有日志输出必须使用 `from loguru import logger`
- 禁止使用 `print()`、`warnings.warn()`、`sys.stdout.write()` 做运行时输出
- 日志级别规范：
  - `logger.info` — 正常流程节点
  - `logger.warning` — 可恢复异常
  - `logger.error` — 需人工介入
  - `logger.debug` — 仅本地开发
- CI 中用 ruff 规则 `T201`（禁止 print）强制拦截

## 6. 错误处理

- 禁止 `except:` 裸捕获和 `except Exception: pass`
- 外部 API 调用统一通过 `tenacity` 实现重试（3 次，指数退避），网络异常和 5xx 可重试，4xx 不可重试
- 工作流节点失败时：采集失败阻断整个管线，分发失败仅记日志不阻断
- `raise ... from exc` 做异常链，禁止截断 traceback
- 自定义异常类放在 `src/exceptions.py`

## 7. 导入与模块组织

- import 顺序由 `ruff check --select I` 自动管理
- 分组：`__future__` → 标准库 → 第三方 → 第一方（`src.*`）
- 多行 import 用括号包裹
- PR 中 import 顺序不一致直接由 ruff format 修，不纳入 review 范围

### 文件行数限制

- 生产代码（`src/`）单文件不超过 300 行
- 测试文件（`tests/`）不超过 500 行
- `__init__.py`、`config.py`、`exceptions.py` 豁免
- CI 中检查，超限 block merge
- 拆分原则：按功能域拆，新拆出的模块用 `__init__.py` 做 re-export 保持接口稳定

## 8. 异步规范

- 网络 IO（httpx 请求、Telegram API 调用）使用 `httpx.AsyncClient` + `async/await`
- 文件 IO（JSON 读写）使用 `aiofiles`
- 调度器（APScheduler）和 LangGraph 节点保持同步，内部通过 `asyncio.run()` 桥接异步代码
- 禁止在 async 函数中调用 `time.sleep()`，必须用 `asyncio.sleep()`

## 9. 安全红线

- API Key / Token / Webhook URL 必须从 `.env` → `pydantic-settings` 注入，源代码中 `grep -r 'sk-' src/` 发现硬编码直接 block merge
- `.env` 和 `.env.*` 必须在 `.gitignore` 中，CI 中加一步 `git check-ignore .env` 验证
- `.env.example` 只包含字段名和占位说明，不含实际值
- 知识条目标题/summary 不得作为 prompt 发送到 DeepSeek 之外的第三方模型

## 10. TODO 管理

- 禁止裸 `# TODO` 提交到 main 分支
- 允许 `# TODO(#issue编号)` 格式（关联了 issue 的 TODO 可以放行）
- CI pipeline 中加一步 `no-todo-check`，PR 中发现裸 TODO 则 block merge

## 11. 测试

- 单测覆盖率 ≥ 80%（分支覆盖率，pytest-cov 的 `--cov-branch`）
- 统计范围限定 `src/**/*.py`
- 排除文件：`src/config.py`、`src/knowledge/models.py`（纯配置/声明无测试价值）
- CI 中覆盖率不达标则 block merge

## 12. Git 提交

- Commit message 格式：`<type>(<scope>): <描述>`（Conventional Commits）
  - type: `feat` / `fix` / `refactor` / `docs` / `chore` / `test`
  - scope: 模块名（`pipeline`, `crawlers`, `channels` 等）
  - 描述用中文，≤ 60 字符
- 禁止在 main 分支直接 push，必须 PR → squash merge
- CI 中加 commitlint 检查

## 13. CI 检查清单

| 步骤 | 命令 | 阻塞条件 |
|------|------|---------|
| 格式化 & Lint | `ruff format --check && ruff check` | 任何不通过 |
| 类型检查 | `mypy src/ --disallow-untyped-defs` | 任何不通过 |
| 禁止 TODO | `rg '#\s*TODO\b(?!\(#\d+\))' src/` | 命中则 block |
| 安全扫描 | `rg 'sk-\w+' src/` + `git check-ignore .env` | 命中/has .env |
| 行数检查 | 检查脚本 | `src/` 超 300 行 / `tests/` 超 500 行 |
| 测试 | `pytest --cov=src --cov-branch --cov-fail-under=80` | 不达标 |
| Commitlint | commitlint | 格式不符 |

Python 版本锁定 3.13，依赖通过 `requirements.txt` 固定版本号。

编写统一的封装调用LLM的client python脚本model_client.py，需求如下：
1、能调用热门的大模型DeepSeek、qwen、minimax、openAI、anthropic，能根据配置做到无缝切换
2、使用httpx调用OPENAI的标准兼容接口，不使用SDK
3、标准接口使用抽象类LLMProvider 封装，最终通过具体的类OpenAICompatibleProvider 暴露接口
4、使用@dataclass 标注必要的传输对象
5、暴露quick_chat()函数一句话调大模型，chat_retry()函数能具备重试能力，重试次数3，重试时间按照指数回避
6、在main中写简单的测试

PEP 8 + 类型标注 + Google 风格 docstring + loguru 日志
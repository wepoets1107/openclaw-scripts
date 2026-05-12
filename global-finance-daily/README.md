# 全球财经要闻日报

每日9:00自动推送的全球财经要闻脚本。

## 文件说明

- `global-finance-daily.md` — 提示词模板，驱动 OpenClaw cron 任务

## 依赖

- OpenClaw cron 调度
- web_search（Brave API，需配置 BRAVE_API_KEY 环境变量）

## 使用

```bash
openclaw cron create \
  --name "全球财经要闻日报" \
  --cron "0 9 * * *" \
  --channel openclaw-weixin \
  --announce \
  --exact \
  --message "请按照 prompts/global-finance-daily.md 的提示词，生成今日全球财经要闻日报，推送给用户。"
```

## 注意事项

- 无硬编码 API Key，搜索依赖 OpenClaw 内置 web_search 工具
- 纯文本输出，适配微信

# astrbot_plugin_kongcheng_ai

支持多供应商的 AstrBot 多媒体插件：

- 生图：`/kc生图 [供应商] [尺寸] <提示词>`
- 图生图：`/kc图生图 [供应商] [尺寸] [提示词]` + 图片
- 文生视频：`/kc视频 [供应商] <提示词>`
- 图生视频：`/kc图生视频 [供应商] [提示词]` + 图片
- 查询：`/kc视频查询 [供应商] <task_id>`
- 供应商状态：`/kc供应商`

## 供应商

- 生图：`zhipu`、`openai`（即 `openai_image`）
- 视频：`zhipu`、`seedance`（`doubao` 作为 `seedance` 别名）

## 最小示例

```text
/kc供应商
/kc生图 zhipu 1024x1024 未来感城市夜景
/kc生图 openai 1024x1024 一只机械猫，插画风
/kc视频 seedance 一艘飞船穿越云层，电影感
/kc图生视频 doubao 让人物微笑并挥手
/kc视频查询 seedance <task_id>
```

## 配置说明

在 WebUI 配置以下关键字段（详见 `_conf_schema.json`）：

- 默认路由：`default_video_provider`、`default_image_provider`
- 智谱：`zhipu_api_key`、`zhipu_api_base`、`zhipu_video_model`、`zhipu_image_model`
- Seedance（豆包）：`seedance_api_key`、`seedance_api_base`、`seedance_generate_path`、`seedance_status_path`
- OpenAI兼容生图：`openai_image_api_key`、`openai_image_api_base`、`openai_image_generate_path`
- 通用稳定性：`request_timeout_seconds`、`request_retry_count`

## 调试步骤

1. 启用插件并填写至少一个生图供应商和一个视频供应商的 key。
2. 执行 `/kc供应商` 确认默认路由和可用供应商。
3. 执行 `/kc视频帮助` 查看命令说明。
4. 发送最小示例命令验证路由是否正确。
5. 修改代码后在插件管理页执行 `Reload Plugin`。

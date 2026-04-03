# astrbot_plugin_kongcheng_ai

AstrBot 视频生成插件（智谱 AI）。

支持能力：

- 文生视频：`/kc视频 <提示词>`
- 图生视频：`/kc图生视频 [提示词]` + 图片
- 任务查询：`/kc视频查询 <task_id>`

## 配置说明

请在 AstrBot 插件配置页填写（由 `_conf_schema.json` 提供）：

- `api_key`：智谱 AI API Key（必填）
- `model`：视频模型名称（默认 `CogVideoX-Flash`）
- `save_video_local`：是否缓存视频到本地
- `max_cache_files`：缓存文件上限，超过会自动清理最旧文件

当 `save_video_local=true` 时，视频会缓存到：

- `data/video_cache/astrbot_plugin_kongcheng_ai/`

## 最小可运行示例

1. 文生视频

```text
/kc视频 一只机械猫在雨夜街头缓慢行走，电影感镜头
```

2. 图生视频（同一条消息里附带图片）

```text
/kc图生视频 让人物自然眨眼并轻微转头
```

3. 查询任务

```text
/kc视频查询 1234567890
```

## 本地调试步骤

1. 确认插件目录在：`AstrBot/data/plugins/astrbot_plugin_kongcheng_ai`
2. 安装插件依赖（AstrBot 启动后通常会自动处理，也可手动安装 `requirements.txt`）
3. 启动 AstrBot 主程序
4. 在 WebUI 的插件管理页启用本插件并填写 `api_key`
5. 修改代码后，在 WebUI 使用 `Reload Plugin` 热重载验证

## 说明

- 插件调用外部接口使用异步友好方式，避免阻塞 AstrBot 事件循环。
- 图生视频图片只在内存中处理，不写入临时图片文件。
- 对用户返回的错误信息做了脱敏处理，避免泄漏敏感信息。

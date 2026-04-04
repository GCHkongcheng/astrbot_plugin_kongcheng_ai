# astrbot_plugin_kongcheng_ai

支持多供应商的 AstrBot 多媒体插件：

- 生图：`/kc生图 [尺寸] <提示词>`
- 图生图：`/kc图生图 [尺寸] [提示词]` + 图片
- 文生视频：`/kc视频 <提示词>`
- 图生视频：`/kc图生视频 [提示词]` + 图片
- 查询：`/kc视频查询 <task_id>`
- 供应商状态：`/kc供应商`
- WebUI 管理台：`/kc后台 [开启|关闭|状态]`

## 供应商

- 生图：`zhipu`、`openai`（即 `openai_image`）
- 视频：`zhipu`、`seedance`（`doubao` 作为 `seedance` 别名）
- 也支持通过 JSON 自定义新增服务商（见下方“自定义服务商”）

## 最小示例

```text
/kc供应商
/kc生图 1024x1024 未来感城市夜景
/kc生图 1024x1024 一只机械猫，插画风
/kc视频 一艘飞船穿越云层，电影感
/kc图生视频 让人物微笑并挥手
/kc视频查询 <task_id>
/kc后台 开启
```

## 配置说明

在 WebUI 配置以下关键字段（详见 `_conf_schema.json`）：

- 供应商选择：`selected_video_provider`、`selected_image_provider`
- 智谱：`zhipu_api_key`、`zhipu_api_base`、`zhipu_video_model`、`zhipu_image_model`
- Seedance（豆包）：`seedance_api_key`、`seedance_api_base`、`seedance_generate_path`、`seedance_status_path`
- OpenAI兼容生图：`openai_image_api_key`、`openai_image_api_base`、`openai_image_generate_path`
- 自定义生图：`custom_image_providers_json`
- 自定义视频：`custom_video_providers_json`
- WebUI：`webui_auto_start`、`webui_host`、`webui_port`
- 通用稳定性：`request_timeout_seconds`、`request_retry_count`
- 说明：只需要配置你选中的供应商参数，不需要同时配置全部供应商

## 自定义服务商

1. 在 `custom_image_providers_json` 或 `custom_video_providers_json` 写 JSON 数组。
2. 每个对象必须有 `name`、`api_key`、`api_base`。
3. 把 `selected_image_provider` / `selected_video_provider` 设为你自定义的 `name`。
4. 当前自定义生图 provider 先支持文生图；图生图建议继续使用内置供应商或后续再扩展。

## WebUI 页面

1. 通过命令启动：`/kc后台 开启`
2. 默认地址：`http://127.0.0.1:8765`
3. 页面支持：
   - 查看当前生效供应商
   - 编辑并应用运行时配置（`仅运行时应用`，不写入配置文件）
   - 持久化保存配置（`持久化保存`，会写入插件配置；若 host/port 变化会自动重启 WebUI）
   - 直接测试生图、视频提交、视频查询
4. 关闭命令：`/kc后台 关闭`

生图示例：

```json
[
  {
    "name": "myimg",
    "api_key": "sk-xxx",
    "api_base": "https://api.example.com/v1",
    "generate_path": "/images/generations",
    "model": "gpt-image-1"
  }
]
```

视频示例：

```json
[
  {
    "name": "myvideo",
    "api_key": "sk-xxx",
    "api_base": "https://api.example.com/v1",
    "submit_path": "/generate",
    "query_path": "/status",
    "task_id_paths": ["data.task_id"],
    "status_paths": ["data.status"],
    "video_url_paths": ["data.url"],
    "support_i2v": true,
    "i2v_input_type": "url",
    "i2v_field": "image_url"
  }
]
```

## 调试步骤

1. 启用插件并按需填写你选中供应商的配置（可只配生图或只配视频）。
2. 执行 `/kc供应商` 确认默认路由和可用供应商。
3. 执行 `/kc视频帮助` 查看命令说明。
4. 发送最小示例命令验证路由是否正确。
5. 按需执行 `/kc后台 开启` 打开页面做配置与接口联调。
6. 修改代码后在插件管理页执行 `Reload Plugin`。

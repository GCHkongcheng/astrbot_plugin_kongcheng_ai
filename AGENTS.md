你正在 AstrBot 项目中的一个插件目录内工作，请开发一个“空城AI”插件，用于生图和生成视频，并支持多个服务商。

开始之前请先做这些事：

1. 阅读当前目录及上级目录中的 AGENTS.md。
2. 阅读插件目录下的 docs/、其他示例插件、metadata.yaml、main.py，以及任何现有 provider 相关代码。
3. 必要时阅读 AstrBot 框架中与插件开发相关的源码，尤其是：
   - Star
   - register
   - filter.command
   - AstrMessageEvent
   - 事件系统与消息返回方式

开发目标：
实现一个 AstrBot 插件，支持以下能力：

- 文生图
- 图生图
- 文生视频
- 图生视频
- 多服务商配置
- 任务状态查询
- 统一结果结构
- 可扩展的 provider 抽象层

强约束：

- 这是 AstrBot 插件，不要写成普通 CLI 程序。
- 必须遵循 AGENTS.md 中的规则。
- 不要把变量名、模型名、服务商名、字段名写死。
- 不要把某个服务商的请求字段直接渗透到整个插件架构里。
- 所有服务商差异必须收敛在 provider/adapter 层。
- 所有扩展参数尽量通过通用 options / metadata / extra_params 之类的可扩展结构传递。
- API Key、base_url、model、timeout、retry、provider 选择都必须走配置，不得硬编码。
- 使用 async，不要使用阻塞式实现。
- 不要自动执行 pip install。
- 外部 API 调用必须有异常处理。
- 涉及下载的临时文件必须考虑清理。

架构要求：
请优先按下面的思路组织代码：

- main.py：AstrBot 指令入口，仅负责接收命令和返回消息
- core/router.py：服务商路由
- core/service.py：统一任务创建与查询
- core/schema.py：统一请求/响应结构
- providers/base.py：抽象 provider 接口
- providers/<provider>.py：各服务商实现
- utils/：文件处理、日志等
- storage/：如有需要，放任务状态存储

数据结构要求：

- 设计统一的 GenerationRequest / GenerationResult 一类的抽象
- 不要固定 video_url、image_url、duration、size 等字段名为全局必填
- 输出统一使用可扩展结构，例如 outputs / metadata / options
- 状态统一抽象为 pending / running / success / failed / timeout 等

命令要求：
请先实现一个最小可用版本，至少包括：

- 一个生图命令
- 一个视频命令
- 一个查询任务状态命令
- 一个查看当前可用服务商或默认服务商的命令

实现要求：

- 尽量复用现有代码风格
- 尽量最小改动，不要无关重构
- 如果现有目录结构不完整，可补充必要文件
- 如果某些能力暂时无法完全实现，请先搭好接口与占位结构，不要乱猜第三方返回格式
- 对第三方返回结果做适配，不要把原始响应直接暴露为插件内部标准结构

完成后请输出：

1. 你新增或修改了哪些文件
2. 每个文件的作用
3. 使用方法（命令示例）
4. 需要我补充的配置项
5. 后续最适合继续实现的功能

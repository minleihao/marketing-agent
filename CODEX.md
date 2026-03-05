# CODEX Notes: Marketing Copilot

## 1) 项目理解
- 本项目是一个营销智能体 Web 应用（`Marketing Copilot`），已具备：
- 用户注册/登录/会话管理
- 多会话聊天（左侧会话列表 + 右侧对话）
- 营销任务模式（结构化输入字段）
- Brand KB 管理（版本化）
- 对话文档上传
- 中英双语界面
- 基于群组的内容共享与权限控制

## 2) 运行结构
- 主要代码集中在 `/Users/minleihao/marketing-agent/novaRed/src/webapp.py`（后端 API + 前端 HTML/JS 模板）。
- 模型调用链路：
- Web API -> `/Users/minleihao/marketing-agent/novaRed/src/main.py` 的 `invoke()`
- 数据存储：
- SQLite：`NOVARED_DATA_DIR/webapp.db`（默认 `data/webapp.db`）
- 上传文件：`NOVARED_DATA_DIR/uploads/`

## 3) 权限模型（核心）
- Chat 与 KB 的可见性分为三档：
- `private`：仅创建者可见
- `task`：任务组内已批准成员可见
- `company`：公司组内已批准成员可见
- 组管理相关：
- 组类型：`task`、`company`
- 成员状态：`pending`、`approved`、`invited`
- 只有 `approved` 成员可访问共享内容
- 所有权规则：
- owner 专属操作：会话重命名/删除、模式和模型修改、文档上传删除、KB 更新删除
- 共享成员可读共享会话与 KB（当前共享会话也允许发送消息）

## 4) 后续开发高风险点
- 不要绕开权限校验：
- 读取/发送消息使用 `conversation_visible_or_404()`
- owner 专属操作使用 `conversation_owner_or_404()`
- `visibility` 与 `share_group_id` 必须成对校验：`_validate_share_group_for_user()`
- KB 绑定必须做可见性校验：
- `/api/conversations/{conversation_id}/kb` 只能绑定当前用户有权限访问的 KB 版本
- 组类型必须匹配：
- `visibility=task` 只能配 task 组
- `visibility=company` 只能配 company 组
- 注册入组流程不能破坏：
- `join_group_ids` 创建 `pending` 申请，需组管理员批准

## 5) 数据与迁移注意
- `init_db()` 负责建表与迁移（含 `ALTER TABLE` 补字段）。
- 变更 Schema 时务必保持向后兼容：
- 新字段需要迁移逻辑
- 不要假设数据库是全新状态
- 现有 KB 的 owner 回填逻辑依赖用户表，改动时要复核。

## 6) 前端开发注意
- 聊天头部控件已优化为紧凑布局：下拉框两列显示，按钮单独一行。
- 所有新增文案必须同步 `zh` / `en` 两套 i18n key。
- 共享内容应保留来源标识（`Shared from` / `共享自`），避免与自有内容混淆。

## 7) 模型与运行时注意
- 模型白名单来源：`NOVARED_ALLOWED_MODELS`（否则走代码默认列表）。
- 主模型失败时可能回退到 `DEFAULT_MODEL_ID`。
- AWS 凭证缺失或 SSO 过期时，运行时可能进入本地 fallback 逻辑。

## 8) 建议开发流程
- 每次改动后至少执行：
- `python -m py_compile src/webapp.py`
- `uv run pytest -q`
- 做权限联调时建议使用隔离数据目录：
- `NOVARED_DATA_DIR=$(mktemp -d) uv run ...`
- 最低回归清单：
- 注册/登录/管理员操作
- 建组/申请/审批/邀请/转移管理员
- Chat 可见性共享与隔离
- KB 可见性共享与隔离
- 越权请求是否正确返回 `403/404`

## 9) 结构优化建议
- `src/webapp.py` 体量较大且混合后端与前端模板，后续建议拆分为：
- 后端 router/service 层
- 前端静态资源与模板文件
- 权限服务层（集中化权限判断）
- 增加专门的权限自动化测试（chat + KB + group 全链路）。

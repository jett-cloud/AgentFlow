# Dify 工具节点系统 — 代码详解与设计原理

> 深入分析工具节点的源码架构、抽象设计和运行时流程。

---

## 目录

1. [设计哲学](#1-设计哲学)
2. [核心抽象层](#2-核心抽象层)
3. [五种工具实现详解](#3-五种工具实现详解)
4. [ToolManager — 工具注册中心](#4-toolmanager--工具注册中心)
5. [ToolEngine — 工具执行引擎](#5-toolengine--工具执行引擎)
6. [工作流集成 — 从节点配置到工具调用](#6-工作流集成--从节点配置到工具调用)
7. [Agent 集成 — LLM 自主选择工具](#7-agent-集成--llm-自主选择工具)
8. [完整调用链追踪](#8-完整调用链追踪)
9. [扩展指南](#9-扩展指南)

---

## 1. 设计哲学

工具系统的核心设计只有一句话：**统一接口，差异化实现；集中注册，按需分发。**

### 1.1 架构全景图

```
                        ┌─────────────────────────────┐
                        │     调用方 (Caller)           │
                        │  Agent / Workflow / Plugin   │
                        └─────────────┬───────────────┘
                                      │
                        ┌─────────────▼───────────────┐
                        │      ToolEngine              │
                        │  (统一执行入口)               │
                        │  - agent_invoke()            │
                        │  - generic_invoke()          │
                        └─────────────┬───────────────┘
                                      │
                        ┌─────────────▼───────────────┐
                        │      ToolManager             │
                        │  (统一注册中心)               │
                        │  - get_tool_runtime()        │
                        │  - get_workflow_tool_runtime│
                        │  - get_agent_tool_runtime()  │
                        └─┬───┬───┬───┬───┬───┬──────┘
                          │   │   │   │   │   │
              ┌───────────▼┐ ┌▼───▼┐ ┌▼───▼┐ ┌▼──────▼┐ ┌▼──────────┐
              │ BuiltinTool│ │Api  │ │MCP  │ │Plugin   │ │Workflow   │
              │ (内置工具) │ │Tool │ │Tool │ │Tool     │ │Tool       │
              │            │ │     │ │     │ │(插件工具)│ │(工作流工具)│
              └────────────┘ └─────┘ └─────┘ └─────────┘ └───────────┘
```

### 1.2 核心设计原则

**原则 1：策略模式 — 统一接口，差异化实现**

```python
# 所有工具都继承同一个基类
class Tool(ABC):
    def invoke(...) -> Generator[ToolInvokeMessage]:  # 统一入口
        ...
    @abstractmethod
    def _invoke(...):  # 子类实现具体逻辑
        ...
    @abstractmethod
    def tool_provider_type() -> ToolProviderType:  # 自报家门
        ...
```

**原则 2：工厂模式 — 集中注册 + 按需创建**

ToolManager 是全局注册中心，根据 `(provider_type, provider_id, tool_name)` 三元组找到对应的 Provider，再由 Provider 创建具体的 Tool 实例。

**原则 3：fork_tool_runtime 模式 — 原型克隆**

Tool 实例可以看作"原型"(Prototype)。真正的运行时实例通过 `fork_tool_runtime()` 克隆产生，克隆时注入 `ToolRuntime`（用户身份、凭证、调用来源）。

**原则 4：Generator 事件流 — 流式响应**

所有工具的 `_invoke()` 返回 `Generator[ToolInvokeMessage]`，支持工具在执行过程中持续产出消息（文本、图片、变量……），而不需要等全部执行完毕。

---

## 2. 核心抽象层

### 2.1 Tool (ABC) — 工具基类

源码位置：[core/tools/__base/tool.py](api/core/tools/__base/tool.py)

```python
class Tool(ABC):
    def __init__(self, entity: ToolEntity, runtime: ToolRuntime):
        self.entity = entity    # 工具的静态元数据（名称、参数定义、图标...）
        self.runtime = runtime  # 工具的运行时上下文（用户、凭证、调用来源...）

    # ═══ 子类必须实现 ═══
    @abstractmethod
    def tool_provider_type(self) -> ToolProviderType:
        """自报家门：我是哪种工具"""
        ...

    @abstractmethod
    def _invoke(
        self, session, user_id, tool_parameters,
        conversation_id=None, app_id=None, message_id=None,
    ) -> ToolInvokeMessage | list[ToolInvokeMessage] | Generator[ToolInvokeMessage]:
        """子类在此编写实际的工具执行逻辑"""
        ...

    # ═══ 模板方法（基类提供默认实现）═══
    def invoke(self, ...) -> Generator[ToolInvokeMessage]:
        """统一入口：参数类型转换 → 调用 _invoke → 统一返回 Generator"""
        if self.runtime.runtime_parameters:
            tool_parameters.update(self.runtime.runtime_parameters)
        tool_parameters = self._transform_tool_parameters_type(tool_parameters)
        result = self._invoke(session, user_id, tool_parameters, ...)
        # 将单值、列表、Generator 统一包装为 Generator
        ...

    def fork_tool_runtime(self, runtime: ToolRuntime) -> "Tool":
        """原型克隆：用新的 runtime 创建一个副本"""
        return self.__class__(entity=self.entity.model_copy(), runtime=runtime)

    # ═══ 工厂方法：创建各种类型的消息 ═══
    def create_text_message(self, text) -> ToolInvokeMessage: ...
    def create_image_message(self, image) -> ToolInvokeMessage: ...
    def create_blob_message(self, blob, meta) -> ToolInvokeMessage: ...
    def create_json_message(self, object) -> ToolInvokeMessage: ...
    def create_variable_message(self, name, value, stream) -> ToolInvokeMessage: ...
    def create_link_message(self, link) -> ToolInvokeMessage: ...
    def create_file_message(self, file) -> ToolInvokeMessage: ...
```

**关键设计点**：

- `ToolEntity` 是工具的**静态定义**（name、parameters、output_schema...），在加载时创建一次，所有运行时实例共享
- `ToolRuntime` 是**每次调用的动态上下文**（credentials、invoke_from、runtime_parameters...），通过 `fork_tool_runtime()` 注入
- `invoke()` 和 `_invoke()` 是典型的**模板方法模式**：父类处理通用逻辑（类型转换、参数合并），子类只关心核心业务

### 2.2 ToolRuntime — 运行时上下文

```python
class ToolRuntime:
    tenant_id: str
    user_id: str | None
    credentials: Mapping[str, Any]       # 解密后的凭证
    credential_type: CredentialType      # API_KEY | OAUTH2
    runtime_parameters: dict[str, Any]   # 运行时动态参数
    invoke_from: InvokeFrom             # DEBUGGER | EXPLORE | WEB_APP | SERVICE_API
    tool_invoke_from: ToolInvokeFrom     # AGENT | WORKFLOW | PLUGIN
```

### 2.3 ToolProviderController — 提供者基类

```python
class ToolProviderController[EntityT, ToolT](ABC):
    entity: EntityT  # Provider 的静态定义

    @abstractmethod
    def get_tool(self, tool_name: str) -> ToolT:
        """根据名称获取一个工具实例"""
        ...

    def get_credentials_schema(self) -> list[ProviderConfig]:
        """返回凭证字段定义（供 UI 渲染凭证表单）"""
        ...

    def validate_credentials_format(self, credentials):
        """验证用户提交的凭证是否合法（类型检查、必填检查、默认值填充）"""
        ...
```

### 2.4 ToolEntity — 工具元数据

```python
class ToolEntity(BaseModel):
    identity: ToolIdentity          # name, author, label, icon, provider
    parameters: list[ToolParameter] # 工具的输入参数列表
    output_schema: dict | None      # 结构化输出 schema
    has_runtime_parameters: bool    # 是否有需要在运行时动态获取的参数（如 MCP 工具）
```

### 2.5 ToolParameter — 参数定义

```python
class ToolParameter(BaseModel):
    name: str
    label: I18nObject
    type: ToolParameterType    # STRING | NUMBER | BOOLEAN | SELECT | FILE | FILES | ...
    form: ToolParameterForm    # SCHEMA(固定) | FORM(用户填) | LLM(LLM决定)
    required: bool
    default: Any = None
    options: list[ToolParameterOption] | None  # SELECT 类型的选项
    llm_description: str | None  # 给 LLM 看的描述
    input_schema: dict | None    # 复杂类型的 schema
```

参数类型 `ToolParameterType` 与 `ToolParameterForm` 的组合决定了参数的交互方式：

| Form ↓ / Type → | STRING/NUMBER/BOOLEAN | SELECT | FILE | SYSTEM_FILES |
|-----------------|----------------------|--------|------|-------------|
| **SCHEMA** | 配置时固定写死 | 配置时固定写死 | - | - |
| **FORM** | 用户在调用前填写 | 用户在调用前选择 | 用户上传 | - |
| **LLM** | LLM 推理决定 | LLM 推理选择 | - | LLM 选择已有文件 |

---

## 3. 五种工具实现详解

### 3.1 BuiltinTool — 内置工具

**文件**：[core/tools/builtin_tool/tool.py](api/core/tools/builtin_tool/tool.py)

```python
class BuiltinTool(Tool):
    def __init__(self, provider: str, **kwargs):
        super().__init__(**kwargs)
        self.provider = provider   # 工具提供者名称

    def _invoke(self, ...) -> Generator:
        # 具体逻辑在 providers/ 子目录下，由各子类实现
        ...
```

**工具定义方式**：YAML + Python

```
core/tools/builtin_tool/providers/
├── audio/
│   ├── audio.yaml            ← Provider 定义（凭证 schema、工具列表）
│   └── tools/
│       ├── asr.yaml           ← 语音识别工具定义（参数、描述）
│       ├── asr.py             ← 语音识别实现
│       ├── tts.yaml
│       └── tts.py
├── code/
│   ├── code.yaml
│   └── tools/
│       ├── simple_code.yaml
│       └── simple_code.py
├── time/
│   ├── time.yaml
│   └── tools/
│       ├── current_time.yaml
│       ├── current_time.py
│       ├── timezone_conversion.yaml
│       └── ...
└── webscraper/
    ├── webscraper.yaml
    └── tools/
        ├── webscraper.yaml
        └── webscraper.py
```

**加载机制**：`load_single_subclass_from_source()` 动态 import Python 文件，找到 `BuiltinTool` 的子类。

**内置工具独有能力**：
- `invoke_model()` — 调用 LLM 进行总结/推理
- `get_max_tokens()` — 获取当前租户模型的上下文长度
- `summary()` — 长文本自动分段总结（递归调用直到文本长度合适）

### 3.2 ApiTool — 自定义 API 工具

**文件**：[core/tools/custom_tool/tool.py](api/core/tools/custom_tool/tool.py)

```python
class ApiTool(Tool):
    api_bundle: ApiToolBundle  # 从 OpenAPI schema 解析出的 API 定义
    provider_id: str

    def _invoke(self, session, user_id, tool_parameters, ...) -> Generator:
        # 1. 组装 HTTP 请求（headers、query params、path params、body）
        headers = self.assembling_request(tool_parameters)

        # 2. 发出 HTTP 请求（经过 SSRF 代理）
        response = self.do_http_request(
            self.api_bundle.server_url, self.api_bundle.method, headers, tool_parameters
        )

        # 3. 解析响应
        parsed_response = self.validate_and_parse_response(response)

        # 4. 产出消息
        if parsed_response.is_json:
            yield self.create_json_message(parsed_response.content)
        yield self.create_text_message(response.text)
```

**工作流程**：

```
用户粘贴 OpenAPI Schema
     │
     ▼
ApiToolProviderController 解析 schema
     │
     ├── 提取 server_url + endpoints
     ├── 每个 operation → 一个 ApiToolBundle
     │   ├── operation_id → tool_name
     │   ├── parameters → ToolParameter 列表
     │   └── requestBody → body schema
     │
     ▼
ApiTool.do_http_request()
     │
     ├── 1. 处理参数位置：path / query / cookie / header
     ├── 2. 处理 request body：application/json / x-www-form-urlencoded / multipart
     ├── 3. 处理 $ref 引用（OpenAPI 的 schema 引用机制）
     ├── 4. 类型转换：int / float / bool / string
     ├── 5. 处理文件上传（multipart/form-data）
     └── 6. 通过 ssrf_proxy 发请求（防 SSRF 攻击）
```

**认证方式**（`ApiProviderAuthType`）：

```python
class ApiProviderAuthType(StrEnum):
    NONE              = "none"
    API_KEY_HEADER    = "api_key_header"    # API Key 放在 Header
    API_KEY_QUERY     = "api_key_query"     # API Key 放在 Query String
```

**Schema 格式支持**（`ApiProviderSchemaType`）：

```python
class ApiProviderSchemaType(StrEnum):
    OPENAPI        = "openapi"         # OpenAPI 3.x
    SWAGGER        = "swagger"         # Swagger 2.x
    OPENAI_PLUGIN  = "openai_plugin"   # OpenAI Plugin Manifest
    OPENAI_ACTIONS = "openai_actions"  # OpenAI Actions
```

### 3.3 MCPTool — MCP 协议工具

**文件**：[core/tools/mcp_tool/tool.py](api/core/tools/mcp_tool/tool.py)

```python
class MCPTool(Tool):
    tenant_id: str
    server_url: str           # MCP Server 地址
    provider_id: str
    headers: dict             # 自定义请求头
    timeout: float            # 请求超时（默认 30s）
    sse_read_timeout: float   # SSE 读取超时（默认 300s）
    identity_mode: IdentityMode  # 身份转发模式

    def _invoke(self, ...) -> Generator:
        # 1. 调用远程 MCP Server
        result = self.invoke_remote_mcp_tool(tool_parameters, user_id, app_id)

        # 2. 处理 MCP 协议的返回内容
        for content in result.content:
            match content:
                case TextContent():
                    # 尝试解析 JSON → json_message
                    # 否则 → text_message
                case ImageContent() | AudioContent():
                    # base64 解码 → blob_message
                case EmbeddedResource():
                    # 嵌入资源（文本或二进制）
```

**MCPTool 的设计亮点**：

1. **短会话模式**：数据库操作和网络操作分离，先加载凭证关 session，再做网络调用
2. **自动重试认证**：`MCPClientWithAuthRetry` 在 401 时自动刷新 token 重试
3. **身份转发**：企业版可将 SSO 身份注入 `X-Dify-SSO-Token` Header 转发给 MCP Server
4. **结构化输出**：如果 `ToolEntity.output_schema` 存在，将 `structuredContent` 转为 `variable_message`

### 3.4 PluginTool — 插件工具

**文件**：[core/tools/plugin_tool/tool.py](api/core/tools/plugin_tool/tool.py)

```python
class PluginTool(Tool):
    tenant_id: str
    plugin_unique_identifier: str
    runtime_parameters: list[ToolParameter] | None  # 缓存

    def _invoke(self, ...) -> Generator:
        # 1. 参数格式转换（Dify 内部格式 → 插件标准格式）
        tool_parameters = convert_parameters_to_plugin_format(tool_parameters)

        # 2. 委托给 PluginToolManager（插件运行时）
        yield from manager.invoke(
            tenant_id=..., user_id=...,
            tool_provider=...,
            tool_name=...,
            credentials=...,
            tool_parameters=tool_parameters,
        )

    def get_runtime_parameters(self, ...):
        # 如果插件声明了 has_runtime_parameters，
        # 则动态向插件查询参数列表（例如 MCP 工具从 Server 动态获取工具列表）
        if self.entity.has_runtime_parameters:
            self.runtime_parameters = manager.get_runtime_parameters(...)
        return self.runtime_parameters
```

**PluginTool 的关键特征**：

- **继承关系**：`PluginToolProviderController` 继承 `BuiltinToolProviderController`，共享凭证管理逻辑
- **委托模式**：实际的工具执行委托给 `PluginToolManager`，PluginTool 只是代理
- **动态参数**：通过 `has_runtime_parameters` 支持运行时动态获取参数（如 MCP 工具列表会随 Server 变化）

### 3.5 WorkflowTool — 工作流发布为工具

**文件**：[core/tools/workflow_as_tool/tool.py](api/core/tools/workflow_as_tool/tool.py)

```python
class WorkflowTool(Tool):
    workflow_app_id: str       # 被发布为工具的工作流 App ID
    version: str               # 使用的工作流版本
    workflow_call_depth: int   # 嵌套调用深度
    _parent_trace_context: ParentTraceContext | None  # 父级追踪上下文
    _latest_usage: LLMUsage    # 最新的 token 用量

    def _invoke(self, ...) -> Generator:
        # 1. 加载 App 和 Workflow
        app = self._get_app(app_id=self.workflow_app_id)
        workflow = self._get_workflow(app_id=self.workflow_app_id, version=self.version)

        # 2. 参数转换（工具参数 → 工作流 inputs + files）
        tool_parameters, files = self._transform_args(tool_parameters)

        # 3. 调用 WorkflowAppGenerator 运行子工作流
        generator = WorkflowAppGenerator()
        result = generator.generate(
            app_model=app, workflow=workflow, user=user,
            args={"inputs": tool_parameters, "files": files},
            invoke_from=self.runtime.invoke_from,
            streaming=False,
            call_depth=self.workflow_call_depth + 1,  # 嵌套深度+1
            pause_state_config=None,  # 子工作流不能暂停（不允许人工输入）
        )

        # 4. 提取 outputs 和 files
        outputs = result["data"]["outputs"]
        outputs, files = self._extract_files(outputs)
        for file in files:
            yield self.create_file_message(file)
        for key, value in outputs.items():
            yield self.create_variable_message(key, value)
        yield self.create_text_message(json.dumps(outputs))
```

**WorkflowTool 特有机制**：

1. **嵌套调用保护**：`call_depth + 1`，超过 `WORKFLOW_CALL_MAX_DEPTH` 时抛异常
2. **禁止暂停**：子工作流中的 HumanInput 节点无效（`pause_state_config=None`）
3. **追踪链传递**：`set_parent_trace_context(workflow_run_id, node_execution_id)` 传递父级追踪信息
4. **用量汇总**：`_derive_usage_from_result()` 递归提取子工作流的 token 用量

---

## 4. ToolManager — 工具注册中心

**文件**：[core/tools/tool_manager.py](api/core/tools/tool_manager.py)

ToolManager 是整个工具系统的**核心调度中心**，所有对工具的获取和创建请求都经过它。

### 4.1 核心方法

```python
class ToolManager:
    # ═══ 硬编码内置工具 ═══
    _hardcoded_providers: dict[str, BuiltinToolProviderController] = {}
    _builtin_providers_loaded: bool = False
    _builtin_provider_lock = Lock()

    # ═══ 主要入口 ═══
    @classmethod
    def get_tool_runtime(
        cls,
        provider_type: ToolProviderType,  # 哪种工具
        provider_id: str,                 # 哪个提供者
        tool_name: str,                   # 哪个工具
        tenant_id: str,                   # 哪个租户
        ...
    ) -> BuiltinTool | PluginTool | ApiTool | WorkflowTool | MCPTool:
        """根据 (type, provider_id, tool_name) → 工具原型 → fork → 运行时实例"""

        match provider_type:
            case ToolProviderType.BUILT_IN:     # 内置工具
                → 加载 YAML 定义 → 创建 BuiltinTool → 解密凭证 → fork
            case ToolProviderType.API:          # API 工具
                → 读 ApiToolProvider 表 → 解析 OpenAPI → 创建 ApiTool → fork
            case ToolProviderType.WORKFLOW:     # 工作流工具
                → 读 WorkflowToolProvider 表 → 构建 WorkflowTool → fork
            case ToolProviderType.PLUGIN:       # 插件工具
                → PluginToolManager 动态获取 → 创建 PluginTool
            case ToolProviderType.MCP:          # MCP 工具
                → MCPToolManageService → 创建 MCPTool
            case ToolProviderType.DATASET_RETRIEVAL:  # 知识检索(不支持 get_tool_runtime)
                raise ToolProviderNotFoundError

    @classmethod
    def get_workflow_tool_runtime(cls, ...):
        """工作流节点调用工具的入口"""
        # get_tool_runtime + 参数解密 + 类型转换

    @classmethod
    def get_agent_tool_runtime(cls, ...):
        """Agent 调用工具的入口"""
        # get_tool_runtime + 参数解密 + LLM参数处理
```

### 4.2 内置工具加载流程

```
ToolManager.load_hardcoded_providers_cache()
    │
    ├── 1. 遍历 core/tools/builtin_tool/providers/ 所有子目录
    │
    ├── 2. 对每个 provider 目录：
    │   ├── 读取 {name}.yaml → Provider Entity（名称、描述、凭证定义）
    │   ├── 遍历 tools/ 子目录
    │   │   ├── 读取 {tool}.yaml → ToolEntity（参数、描述、类型）
    │   │   └── load_single_subclass_from_source("*.py")
    │   │       → 找到 BuiltinTool 的子类 → 实例化
    │   └── → BuiltinToolProviderController
    │         ├── entity: ToolProviderEntity
    │         └── tools: dict[str, BuiltinTool]
    │
    └── 3. _hardcoded_providers[provider_name] = controller
```

### 4.3 凭证解密流程（BUILT_IN / PLUGIN）

```python
# ToolManager.get_tool_runtime(BUILT_IN) 的凭证解密：

# 1. 从 BuiltinToolProvider 表读取加密凭证
builtin_provider = select(BuiltinToolProvider).where(
    tenant_id=..., provider=...
)

# 2. 创建解密器（基于租户 + 凭证 schema 做密钥派生）
encrypter = create_provider_encrypter(
    tenant_id=tenant_id,
    config=provider_controller.get_credentials_schema(),
)

# 3. 解密凭证
decrypted_credentials = encrypter.decrypt(builtin_provider.credentials)

# 4. OAuth token 过期自动刷新
if builtin_provider.expires_at - 60 < time.time():
    refreshed = oauth_handler.refresh_credentials(...)
    builtin_provider.encrypted_credentials = json.dumps(encrypter.encrypt(...))
    db.session.commit()

# 5. fork_tool_runtime（将解密后的凭证注入 ToolRuntime）
return builtin_tool.fork_tool_runtime(
    runtime=ToolRuntime(credentials=decrypted_credentials, ...)
)
```

---

## 5. ToolEngine — 工具执行引擎

**文件**：[core/tools/tool_engine.py](api/core/tools/tool_engine.py)

ToolEngine 是工具的**统一执行入口**，提供两种调用方式：

### 5.1 Agent 调用模式

```python
@staticmethod
def agent_invoke(
    session: Session,
    tool: Tool,
    tool_parameters: Union[str, dict],  # LLM 可能传 JSON 字符串
    user_id, tenant_id,
    message: Message,       # 关联的 Message 记录
    invoke_from,
    agent_tool_callback,    # Agent 回调（用于记录 LLM 思考过程）
    trace_manager,
    ...
) -> tuple[str, list[str], ToolInvokeMeta]:
    """
    Agent 调用工具，返回 (文本响应, 文件ID列表, 元数据)
    """
    # 1. 如果参数是 JSON 字符串，且工具只有一个 LLM 参数 → 自动转换
    if isinstance(tool_parameters, str) and len(llm_params) == 1:
        tool_parameters = {llm_params[0].name: tool_parameters}

    # 2. 通知 Agent 回调：工具开始执行
    agent_tool_callback.on_tool_start(tool_name=..., tool_inputs=...)

    # 3. 执行工具
    messages = ToolEngine._invoke(session, tool, tool_parameters, ...)

    # 4. 文件处理：提取二进制内容 → 存到 MessageFile 表
    binary_files = ToolEngine._extract_tool_response_binary_and_text(message_list)
    message_files = ToolEngine._create_message_files(binary_files, ...)

    # 5. 转换工具响应为纯文本（LLM 只能理解文本）
    plain_text = ToolEngine.tool_response_to_str(message_list)

    # 6. 通知 Agent 回调：工具执行完成
    agent_tool_callback.on_tool_end(...)

    return plain_text, message_files, meta
```

### 5.2 工作流调用模式

```python
@staticmethod
def generic_invoke(
    session, tool, tool_parameters, user_id,
    workflow_tool_callback,  # 工作流回调（用于事件广播）
    workflow_call_depth,     # 嵌套深度
    ...
) -> Generator[ToolInvokeMessage]:
    """
    工作流调用工具，返回原始消息流
    """
    # 1. 如果是 WorkflowTool，设置嵌套深度
    if isinstance(tool, WorkflowTool):
        tool.workflow_call_depth = workflow_call_depth + 1

    # 2. 执行工具
    response = tool.invoke(session, user_id, tool_parameters, ...)

    # 3. 通知工作流回调：工具执行完成
    response = workflow_tool_callback.on_tool_execution(
        tool_name=..., tool_inputs=..., tool_outputs=response
    )
    return response
```

### 5.3 两种模式的差异

| 维度 | Agent 模式 | Workflow 模式 |
|------|-----------|--------------|
| **返回类型** | `(str, list[str], ToolInvokeMeta)` | `Generator[ToolInvokeMessage]` |
| **文件处理** | 自动保存到 MessageFile → 返回 ID 列表 | 保持为 File 对象 |
| **文本转换** | 将所有类型的消息拼成纯文本 | 保持原始消息类型 |
| **回调** | `DifyAgentCallbackHandler` | `DifyWorkflowCallbackHandler` |
| **SSRF** | 不走 SSRF 代理（Agent 调用由 LLM 评估） | 走 SSRF 代理 |

---

## 6. 工作流集成 — 从节点配置到工具调用

当一个工作流节点类型为 `"tool"` 时，如何找到并执行工具？

### 6.1 节点创建：DifyNodeFactory

```python
# core/workflow/node_factory.py
class DifyNodeFactory(NodeFactory):
    def create_node(self, node_config) -> Node:
        if node_type == BuiltinNodeTypes.TOOL:
            kwargs = {
                "tool_file_manager": self._bound_tool_file_manager_factory(),
                "runtime": self._tool_runtime,  # ← DifyToolNodeRuntime
            }
```

### 6.2 工具解析：DifyToolNodeRuntime

```python
# core/workflow/node_runtime.py
class DifyToolNodeRuntime(ToolNodeRuntimeProtocol):

    def get_runtime(self, *, node_id, node_data, variable_pool, ...) -> ToolRuntimeHandle:
        """创建工具运行时绑定"""
        tool_runtime = ToolManager.get_workflow_tool_runtime(
            tenant_id, app_id, node_id,
            node_data,  # 包含 provider_type, provider_id, tool_name, tool_configurations
            user_id, invoke_from, variable_pool,
        )
        # 如果是 WorkflowTool → 设置追踪上下文
        if is_workflow_tool_provider(node_data):
            parent_trace_context = ParentTraceContext(
                parent_workflow_run_id=...,
                parent_node_execution_id=...,
            )
        return ToolRuntimeHandle(raw=_WorkflowToolRuntimeBinding(
            tool=tool_runtime,
            conversation_id=...,
            parent_trace_context=...,
        ))

    def invoke(self, *, tool_runtime, tool_parameters, workflow_call_depth, ...) -> Generator:
        """实际执行工具调用"""
        tool = tool_runtime.tool
        # 设置追踪上下文
        if hasattr(tool, "set_parent_trace_context"):
            tool.set_parent_trace_context(...)

        # 调用 ToolEngine
        messages = ToolEngine.generic_invoke(
            session=session, tool=tool,
            tool_parameters=tool_parameters,
            user_id=..., workflow_tool_callback=callback,
            workflow_call_depth=workflow_call_depth,
        )

        # 文件消息转换（URL → File 对象）
        yield from ToolFileMessageTransformer.transform_tool_invoke_messages(messages, ...)
```

### 6.3 节点配置 → 工具调用的完整映射

```
工作流 JSON graph 中的 TOOL 节点配置:
{
  "id": "tool_1",
  "data": {
    "type": "tool",
    "provider_type": "mcp",        # ← ToolProviderType
    "provider_id": "uuid-xxx",     # ← MCPToolProvider.id
    "tool_name": "search_web",     # ← ToolName
    "tool_configurations": {       # ← SCHEMA / FORM 类参数的值
      "param1": "value1"
    },
    "tool_parameters": {           # ← LLM 交互场景的参数设置
      "query": {
        "type": "variable",
        "value": "{{#start.query#}}"
      }
    }
  }
}
         │
         ▼
    DifyNodeFactory.create_node()
         │ 创建 ToolNode，注入 DifyToolNodeRuntime
         ▼
    ToolNode.run()
         │
         ▼
    DifyToolNodeRuntime.get_runtime()
         │ ToolManager.get_workflow_tool_runtime(
         │     provider_type="mcp",
         │     provider_id="uuid-xxx",
         │     tool_name="search_web",
         │ )
         ▼
    ToolManager → get_tool_runtime()
         ├── MCPToolProviderController.get_tool("search_web")
         └── → MCPTool.fork_tool_runtime(runtime)
         ▼
    DifyToolNodeRuntime.invoke()
         └── ToolEngine.generic_invoke(tool=MCPTool, ...)
              └── MCPTool._invoke()
                   └── invoke_remote_mcp_tool()
```

---

## 7. Agent 集成 — LLM 自主选择工具

Agent 模式下，LLM 会自主决定"要不要调用工具"以及"传什么参数"。

### 7.1 工具选择

```python
# Agent 从模型配置中获取可用工具列表
agent_tools = [
    AgentToolEntity(
        provider_type=ToolProviderType.BUILT_IN,
        provider_id="time",
        tool_name="current_time",
        tool_parameters={},
        credential_id=None,
    ),
    AgentToolEntity(
        provider_type=ToolProviderType.MCP,
        provider_id="uuid-xxx",
        tool_name="search_web",
        tool_parameters={},
        credential_id=None,
    ),
]
```

### 7.2 LLM 参数推理

```python
# Tool.get_llm_parameters_json_schema() 为 LLM 生成 JSON Schema
# 只包含 form == LLM 的参数

{
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "The search query to use"
        }
    },
    "required": ["query"]
}
```

LLM 根据这个 schema 输出 `{"query": "Dify AI platform"}` → `ToolEngine.agent_invoke()` 接收这个 JSON 并调用工具。

### 7.3 Agent 工具调用的完整链路

```
Agent 决策: "我需要搜索网络"
     │
     ▼
1. LLM 输出 function call:
   {"name": "search_web", "arguments": {"query": "Dify platform"}}
     │
     ▼
2. Agent 调用 ToolEngine.agent_invoke()
   tool = ToolManager.get_agent_tool_runtime(agent_tool)
     │
     ▼
3. ToolEngine 执行:
   ├── agent_tool_callback.on_tool_start()
   ├── tool.invoke(user_id, {"query": "Dify platform"})
   ├── 消息 → 纯文本转换
   ├── 二进制文件 → MessageFile 表
   └── agent_tool_callback.on_tool_end()
     │
     ▼
4. Agent 将工具返回的文本注入 LLM 上下文:
   {"role": "tool", "content": "Search results: ..."}
     │
     ▼
5. LLM 基于工具返回继续推理 → 可能调用更多工具或直接回复用户
```

---

## 8. 完整调用链追踪

### 场景：工作流中调用 MCP 搜索工具

```
1. 前端配置 TOOL 节点
   - provider_type: "mcp"
   - provider_id: "mcp-provider-uuid"
   - tool_name: "search_web"
   - tool_parameters: {query: "{{#start.query#}}"}

2. 工作流发布 → graph JSON 持久化到 Workflow.graph

3. 工作流执行
   WorkflowEntry.run()
   → GraphEngine 调度到 tool_1 节点

4. 节点创建
   DifyNodeFactory.create_node(node_config)
   → 识别 type="tool"
   → 创建 ToolNode 实例
   → 注入 DifyToolNodeRuntime

5. 节点执行
   ToolNode._run()
   → runtime.get_runtime(node_id="tool_1", node_data, variable_pool)
     → ToolManager.get_workflow_tool_runtime(
         provider_type="mcp",
         provider_id="mcp-provider-uuid",
         tool_name="search_web"
       )
       → ToolManager.get_tool_runtime("mcp", ...)
         → MCPToolManageService.get_provider_entity(...)
           → 从 MCPToolProvider 表加载配置
           → 解密 server_url、凭证、headers
         → MCPToolProviderController.get_tool("search_web")
           → 从缓存的 tools 列表中找到对应工具
           → 创建 MCPTool(
               entity=ToolEntity(...),
               runtime=ToolRuntime(...),   ← 尚未 fork
               server_url=...,
               tenant_id=...,
             )
         → 返回 MCPTool 实例

   → runtime.invoke(tool_runtime, tool_parameters, ...)
     → 从 variable_pool 解析 {{#start.query#}} → "Dify platform"
     → ToolEngine.generic_invoke(
         tool=MCPTool,
         tool_parameters={"query": "Dify platform"},
         workflow_call_depth=0,
       )
       → MCPTool.invoke()
         → tool_parameters → 参数类型转换
         → MCPTool._invoke()
           → 加载凭证（短会话）
           → 处理参数（过滤 None/空字符串）
           → 企业 SSO 身份转发（如果启用）
           → MCPClientWithAuthRetry.invoke_tool(
               "search_web", {"query": "Dify platform"}
             )
             → 连接 MCP Server
             → 发送 JSON-RPC tools/call
             → 接收 CallToolResult
           → 解析返回内容:
             - TextContent → text_message
             - ImageContent → blob_message
             - EmbeddedResource → text_message / blob_message
           → structuredContent → variable_message
           → 提取 usage 元数据

6. 结果传递
   ToolNode 将 tool_1 的输出写入 VariablePool
   → 下游节点通过 {{#tool_1.text#}} 引用结果
```

---

## 9. 扩展指南

### 9.1 添加新的内置工具

```
# 1. 创建 provider 目录和定义文件
core/tools/builtin_tool/providers/my_tool/
├── my_tool.yaml          # Provider 定义
│   identity:
│     author: MyCompany
│     name: my_tool
│     label: {en_US: My Tool}
│   credentials_for_provider:
│     api_key:
│       type: secret-input
│       required: true
│       label: {en_US: API Key}
│
└── tools/
    ├── my_action.yaml    # Tool 定义
    │   identity:
    │     name: my_action
    │     author: MyCompany
    │     label: {en_US: My Action}
    │   description:
    │     human: {en_US: Does something useful}
    │     llm: Use this tool when you need to do something useful
    │   parameters:
    │     - name: input
    │       type: string
    │       required: true
    │       form: LLM
    │       llm_description: The input to process
    │
    └── my_action.py      # Tool 实现
        from core.tools.builtin_tool.tool import BuiltinTool
        class MyActionTool(BuiltinTool):
            def _invoke(self, session, user_id, tool_parameters, ...):
                result = do_something(tool_parameters["input"])
                yield self.create_text_message(result)
```

### 9.2 关键接口总结

```
扩展新的工具类型需要实现：

1. Provider 类（继承 ToolProviderController）
   ├── get_tool(tool_name) → Tool 实例
   └── get_credentials_schema() → list[ProviderConfig]

2. Tool 类（继承 Tool）
   ├── tool_provider_type() → ToolProviderType
   └── _invoke(session, user_id, tool_parameters, ...) → Generator[ToolInvokeMessage]

3. 在 ToolProviderType 枚举中添加新值

4. 在 ToolManager.get_tool_runtime() 的 match 中添加新分支

5. (可选) 添加数据库表存储 Provider 配置
```

### 9.3 核心文件索引

| 文件 | 内容 |
|------|------|
| [core/tools/__base/tool.py](api/core/tools/__base/tool.py) | Tool 抽象基类 |
| [core/tools/__base/tool_provider.py](api/core/tools/__base/tool_provider.py) | ToolProviderController 抽象基类 |
| [core/tools/__base/tool_runtime.py](api/core/tools/__base/tool_runtime.py) | ToolRuntime 运行时上下文 |
| [core/tools/entities/tool_entities.py](api/core/tools/entities/tool_entities.py) | 所有 Entity、Enum、类型定义 |
| [core/tools/builtin_tool/tool.py](api/core/tools/builtin_tool/tool.py) | BuiltinTool 实现 |
| [core/tools/custom_tool/tool.py](api/core/tools/custom_tool/tool.py) | ApiTool 实现 |
| [core/tools/mcp_tool/tool.py](api/core/tools/mcp_tool/tool.py) | MCPTool 实现 |
| [core/tools/plugin_tool/tool.py](api/core/tools/plugin_tool/tool.py) | PluginTool 实现 |
| [core/tools/workflow_as_tool/tool.py](api/core/tools/workflow_as_tool/tool.py) | WorkflowTool 实现 |
| [core/tools/tool_manager.py](api/core/tools/tool_manager.py) | ToolManager 注册中心 |
| [core/tools/tool_engine.py](api/core/tools/tool_engine.py) | ToolEngine 执行引擎 |
| [core/workflow/node_runtime.py](api/core/workflow/node_runtime.py) | DifyToolNodeRuntime 工作流集成 |
| [models/tools.py](api/models/tools.py) | ORM 数据模型 |
| [core/tools/utils/dataset_retriever_tool.py](api/core/tools/utils/dataset_retriever_tool.py) | DatasetRetrieverTool |

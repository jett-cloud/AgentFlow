# Dify 自定义工作流节点 — 逐行源码详解

> 覆盖 `core/workflow/nodes/` 下 Dify 自研的 5 类节点：Agent、Agent v2、Human Input、Knowledge Retrieval、Knowledge Index。

---

## 目录

- [1. Agent 节点（v1）— 策略模式 Agent](#1-agent-节点v1--策略模式-agent)
- [2. Agent v2 节点 — Agent Backend 架构](#2-agent-v2-节点--agent-backend-架构)
- [3. Human Input 节点 — 暂停等待人工输入](#3-human-input-节点--暂停等待人工输入)
- [4. Knowledge Retrieval 节点 — RAG 知识检索](#4-knowledge-retrieval-节点--rag-知识检索)
- [5. Knowledge Index 节点 — 知识索引入库](#5-knowledge-index-节点--知识索引入库)

---

## 1. Agent 节点（v1）— 策略模式 Agent

**文件**：[core/workflow/nodes/agent/agent_node.py](api/core/workflow/nodes/agent/agent_node.py)
**总行数**：197 行。Dify 自定义节点中最简洁的一个，因为它把所有复杂逻辑委托给了 `AgentStrategy` 和 `AgentMessageTransformer`。

### 1.1 构造函数（第 35-56 行）

```python
class AgentNode(Node[AgentNodeData]):
    node_type = BuiltinNodeTypes.AGENT   # 声明节点类型标识

    def __init__(
        self,
        node_id: str,
        data: AgentNodeData,              # Pydantic 模型，用户在前端配置的参数
        *,
        graph_init_params: GraphInitParams,   # 工作流级的元数据（workflow_id, graph_config, run_context）
        graph_runtime_state: GraphRuntimeState, # 运行时状态（VariablePool, execution_context）
        strategy_resolver: AgentStrategyResolver,         # ← 依赖注入：从插件系统解析策略
        presentation_provider: AgentStrategyPresentationProvider, # ← 获取图标等展示信息
        runtime_support: AgentRuntimeSupport,             # ← 构建参数 + 凭证
        message_transformer: AgentMessageTransformer,     # ← 把工具消息流转成标准输出
    ) -> None:
```

**`*` 之后的所有参数都是 keyword-only**（只能用 `key=value` 方式传参）。7 个依赖没有一个是在 AgentNode 内部创建的—全部由 `DifyNodeFactory.create_node()` 注入。这是**依赖注入**的标准写法：类声明它需要什么，工厂负责装配。

**`data: AgentNodeData`** 是用户在画布上配的 Agent 配置（策略名、参数、工具列表等），Pydantic 模型，在 `entities.py` 中定义。

### 1.2 populate_start_event（第 63-72 行）

```python
@override
def populate_start_event(self, event) -> None:
    dify_ctx = DifyRunContext.model_validate(self.require_run_context_value(DIFY_RUN_CONTEXT_KEY))
    event.extras["agent_strategy"] = {
        "name": self.node_data.agent_strategy_name,
        "icon": self._presentation_provider.get_icon(...),
    }
```

`populate_start_event` 在 `Node.run()` 基类方法中，**在调用 `_run()` 之前**被调用。它向 `NodeRunStartedEvent` 注入"当前用的什么策略、什么图标"信息，供调试面板显示。

`self.require_run_context_value(DIFY_RUN_CONTEXT_KEY)` 是从 `graph_init_params.run_context` 中取出必须存在的值，不存在就抛异常。这个值是 Dify 层在创建 GraphEngine 前存入的。

### 1.3 _run() 执行流程（第 75-170 行）

```
_run()
  │
  ├─ 1. 解析策略
  │    strategy = self._strategy_resolver.resolve(
  │        tenant_id, agent_strategy_provider_name, agent_strategy_name
  │    )
  │    ↓ 调用插件系统的 PluginAgentStrategyResolver
  │    ↓ 返回一个 AgentStrategyProtocol 对象（来自插件）
  │
  ├─ 2. 构建参数 + 凭证
  │    parameters = self._runtime_support.build_parameters(
  │        agent_parameters,      # 策略声明需要什么参数
  │        variable_pool,         # 从 VariablePool 解析变量引用
  │        node_data,             # 用户在画布的配置
  │        strategy, tenant_id, user_id, app_id, invoke_from,
  │    )
  │    credentials = self._runtime_support.build_credentials(parameters)
  │
  ├─ 3. 调用策略
  │    message_stream = strategy.invoke(
  │        params=parameters, user_id, app_id, conversation_id, credentials
  │    )
  │    ↓ 返回 Generator[ToolInvokeMessage]，和工具节点返回的消息格式完全相同
  │
  └─ 4. 消息转换 → 工作流输出
       yield from self._message_transformer.transform(
           messages=message_stream,
           tool_info={...},
           parameters_for_log=parameters_for_log,
           user_id, tenant_id, conversation_id,
           node_type, node_id, node_execution_id,
       )
       ↓ AgentMessageTransformer 负责把 ToolInvokeMessage 转成
       ↓ StreamChunkEvent + StreamCompletedEvent
```

**为什么 Agent v1 的代码这么短？**

因为所有复杂逻辑都在**外部**：
- `strategy_resolver` → 插件系统，返回哪个 Agent 策略（ReAct、FunctionCall、自定义...）
- `strategy.invoke()` → 策略自己实现的执行逻辑（调用 LLM、解析 tool_calls、循环推理）
- `message_transformer` → 把工具消息流转成工作流事件

AgentNode 本身只是一个**胶水层**——把 Dify 工作流运行时（VariablePool、凭证、用户上下文）适配到插件的 Agent 策略接口。

### 1.4 错误处理策略

两个 try/except 块分别捕获不同阶段的失败：

```python
# 第一个 try：策略解析或调用失败
except Exception as e:
    yield StreamCompletedEvent(
        node_run_result=NodeRunResult(
            status=WorkflowNodeExecutionStatus.FAILED,
            error=str(e),
        ),
    )
    return

# 第二个 try：消息转换失败（通常是 PluginDaemonClientSideError）
except PluginDaemonClientSideError as e:
    yield StreamCompletedEvent(
        node_run_result=NodeRunResult(status=FAILED, ...)
    )
```

`return` 很关键——出错后**立即终止生成器**，GraphEngine 不会再试图从这个节点读更多事件。

---

## 2. Agent v2 节点 — Agent Backend 架构

**文件**：[core/workflow/nodes/agent_v2/agent_node.py](api/core/workflow/nodes/agent_v2/agent_node.py)
**总行数**：779 行。Dify 最复杂的节点，因为引入了**Agent Backend**（独立的 Agent 运行时服务）。

### 2.1 架构：为什么需要 Agent Backend？

```
传统 Agent（v1）：在同一个进程中运行
  Workflow Engine → AgentStrategy.invoke() → LLM API
  问题：每次 LLM 调用阻塞整个 Python 进程

Agent v2：委托给外部 Agent Backend 服务
  Workflow Engine → AgentBackendRunClient.create_run()
    → HTTP/SSE → Agent Backend（独立服务）
    → Agent Backend 内部：LLM 推理循环 + 工具调用
    → SSE 事件流回到 Workflow Engine
  好处：Agent 有自己的进程、自己的 memory、自己的沙箱
```

### 2.2 构造函数（第 81-110 行）

```python
class DifyAgentNode(Node[DifyAgentNodeData]):
    node_type = BuiltinNodeTypes.AGENT  # 和 v1 共用同一个 node_type!

    def __init__(
        self, ..., *,
        binding_resolver: WorkflowAgentBindingResolver,    # 解析 Agent 绑定（Agent + Snapshot + Binding）
        runtime_request_builder: WorkflowAgentRuntimeRequestBuilder,  # 构建给 Agent Backend 的请求
        agent_backend_client: AgentBackendRunClient,        # Agent Backend 的 HTTP 客户端
        event_adapter: AgentBackendRunEventAdapter,         # 把 Backend 的原始事件转成内部事件
        output_adapter: WorkflowAgentOutputAdapter,          # 把 Backend 的输出转成工作流 outputs
        type_checker: PerOutputTypeChecker,                  # 每个输出变量的类型校验
        failure_orchestrator: OutputFailureOrchestrator,     # 输出失败时：重试/默认值/报错
        session_store: WorkflowAgentRuntimeSessionStore,     # 暂停恢复用的会话存储
    ):
```

**8 个依赖注入**，每个都有明确职责：

| 依赖 | 阶段 | 职责 |
|------|------|------|
| `binding_resolver` | 准备 | 查数据库，找到这个 Agent 节点的绑定关系（Agent 定义 + 配置快照 + 绑定配置） |
| `runtime_request_builder` | 准备 | 把 VariablePool + 用户配置 → Agent Backend 能理解的请求 JSON |
| `agent_backend_client` | 执行 | 向 Agent Backend 发 HTTP 请求创建 run，然后通过 SSE 接收事件流 |
| `event_adapter` | 执行 | Backend 返回的事件格式 → 统一的内部事件格式 |
| `output_adapter` | 结束 | Backend 的 `output` dict → 工作流的 `outputs`（按声明的 schema） |
| `type_checker` | 结束 | 检查每个 output 的类型是否匹配声明 |
| `failure_orchestrator` | 结束 | 类型不匹配时决定：重试？用默认值？报错？ |
| `session_store` | 暂停 | 暂停时保存快照 + 恢复时加载快照 |

### 2.3 _run() 完整流程（第 131-455 行）

```
_run()
  │
  ├─ 第一阶段：解析 (Setup)
  │   ├── binding_resolver.resolve()  → bundle {agent, snapshot, binding}
  │   ├── 提取 effective_outputs（Agent 的输出声明，包含默认值）
  │   └── 检查是否有 pending ask_human 表单需要恢复
  │       ├── resolve_ask_human_form() → 表单已提交 → build_deferred_tool_results()
  │       └── 表单未提交 → yield PauseRequestedEvent，return
  │
  ├─ 第二阶段：请求 (Request Building)
  │   ├── runtime_request_builder.build(
  │   │     WorkflowAgentRuntimeBuildContext(
  │   │         dify_context, workflow_id, workflow_run_id,
  │   │         node_id, variable_pool, binding, agent, snapshot,
  │   │         attempt=attempt,                  # 当前重试次数
  │   │         session_snapshot=...,             # 上次执行的快照（恢复用）
  │   │         deferred_tool_results=...,        # HITL 表单提交的结果
  │   │     )
  │   │   )
  │   └── 第一次 attempt 时把 request 存入 inputs（调试面板展示）
  │
  ├─ 第三阶段：执行 (Backend Run)
  │   ├── agent_backend_client.create_run(runtime_request.request)  # HTTP POST → Agent Backend
  │   │   → create_response {run_id, status}
  │   ├── _consume_event_stream(run_id)  # SSE 流式消费
  │   │   ├── 对于每个 public_event：
  │   │   │   event_adapter.adapt(public_event) → 内部事件
  │   │   │   ├── RUN_STARTED → 跳过
  │   │   │   ├── STREAM_EVENT → 更新 metadata（usage、token数）
  │   │   │   ├── AGENT_MESSAGE_DELTA → 记录 delta 计数
  │   │   │   ├── RUN_SUCCEEDED → 返回（成功终端）
  │   │   │   ├── RUN_FAILED → 返回（失败终端）
  │   │   │   ├── RUN_CANCELLED → 返回（取消终端）
  │   │   │   └── DEFERRED_TOOL_CALL → 返回（暂停终端，ask_human）
  │   │   └── 异常处理：AgentBackendError → 失败事件
  │   │
  │   └── 处理终端事件：
  │       ├── DEFERRED_TOOL_CALL（ask_human）
  │       │   ├── build_ask_human_pause_reason() → 创建表单
  │       │   ├── save_session_snapshot() → 持久化快照
  │       │   └── yield PauseRequestedEvent
  │       │
  │       ├── RUN_FAILED / RUN_CANCELLED
  │       │   ├── mark_session_cleaned_on_failure() → 清理会话
  │       │   └── yield StreamCompletedEvent(FAILED)
  │       │
  │       └── RUN_SUCCEEDED
  │           ├── save_session_snapshot() → 持久化快照
  │           ├── type_checker.check() → 逐 output 检查类型
  │           ├── 如果全部通过 → yield StreamCompletedEvent(SUCCEEDED)
  │           └── 如果有失败：
  │               ├── failure_orchestrator.decide(failures, attempt)
  │               ├── RETRY → attempt += 1，回到第二阶段
  │               ├── USE_DEFAULT → 用默认值替换失败的 output → SUCCEEDED
  │               └── FAIL → yield StreamCompletedEvent(FAILED)
  │               └── TAKE_FAIL_BRANCH → FAIL（走错误处理分支）
```

### 2.4 重试循环设计

```python
    # 第 225 行
    attempt = 0
    while True:                     # ← 无限循环，通过 return/continue 控制
        try:
            runtime_request = self._runtime_request_builder.build(
                ..., attempt=attempt, ...
            )
        except BuildError as error:
            yield self._failure_event(...)
            return                   # ← 构建失败，直接结束

        create_response = self._agent_backend_client.create_run(...)
        terminal_event, exhausted = self._consume_event_stream(...)
        ...
        type_check = self._type_checker.check(...)

        if not type_check.has_failures:
            yield StreamCompletedEvent(SUCCEEDED)
            return                   # ← 成功，结束

        outcome = self._failure_orchestrator.decide(failures, attempt)
        if outcome.decision == RETRY:
            attempt = outcome.next_attempt
            continue                 # ← 重试！回到 while 顶部
        ...
```

### 2.5 暂停恢复机制

```python
    # 第 201-221 行：恢复时检查是否有 pending 表单
    if self._session_store is not None:
        stored_session = self._session_store.load_active_session(session_scope)
        if stored_session is not None and stored_session.pending_form_id is not None:
            resume_outcome = resolve_ask_human_form(
                form_id=stored_session.pending_form_id, ...
            )
            if resume_outcome is not None and resume_outcome.repause is not None:
                yield PauseRequestedEvent(reason=...)     # 表单还没提交 → 继续暂停
                return
            if resume_outcome is not None and resume_outcome.deferred_result is not None:
                deferred_tool_results = build_deferred_tool_results(
                    tool_call_id=..., result=...
                )
                # ↑ 把人工填写的表单结果注入到第二次 Agent run 的请求中
```

**整个流程**：
1. 第一次 `_run()` → Agent Backend 返回 `DEFERRED_TOOL_CALL`（需要人工确认）
2. `build_ask_human_pause_reason()` 创建 HumanInput 表单 + `save_session_snapshot()` 保存
3. `yield PauseRequestedEvent` → GraphEngine 序列化整个运行时状态 → 停止
4. 用户填写表单提交 → GraphEngine 反序列化 → 重新调用 `_run()`
5. `_run()` 第二次执行 → `load_active_session()` 发现有 pending 表单
6. `resolve_ask_human_form()` 查表单是否已提交
7. 已提交 → `build_deferred_tool_results()` 构建 tool result
8. 重新 `create_run()`，这次带上 `deferred_tool_results` → Agent 继续推理

### 2.6 ask_human 与其他 HITL 的区别

Agent v2 的 ask_human **复用了 Human Input 节点的表单系统**：
- `HumanInputFormRepositoryImpl` → 创建表单记录
- `HumanInputFormRepository` → 查询表单状态
- 表单的 ID 被持久化在 `AgentRuntimeSession` 中，用于恢复时查找

---

## 3. Human Input 节点 — 暂停等待人工输入

**文件**：[core/workflow/nodes/human_input/entities.py](api/core/workflow/nodes/human_input/entities.py)（实体定义）
**执行逻辑**在 graphon 的 `human_input/human_input_node.py`，但 Dify 层提供了：
- `entities.py`：表单字段的完整 Pydantic 模型
- `callback.py`：`DifyHITLCallback` 处理表单创建和提交
- `pause_reason.py`：`HumanInputRequired` 暂停原因

### 3.1 HumanInputNodeData — 表单定义（第 230-263 行）

```python
class HumanInputNodeData(BaseNodeData):
    type: NodeType = BuiltinNodeTypes.HUMAN_INPUT
    form_content: str = ""              # 表单的 Markdown 内容（支持 {{#变量#}} 引用）
    inputs: list[FormInputConfig] = []  # 表单的输入字段（段落/下拉/文件）
    user_actions: list[UserActionConfig] = []  # 按钮（如"同意"/"拒绝"）
    timeout: int = 36                   # 超时时间
    timeout_unit: TimeoutUnit = HOUR    # 超时单位（小时/天）
```

### 3.2 FormInputConfig — 输入字段（第 197-200 行）

4 种字段类型，通过**联合类型（Union Type）**统一：

```python
type FormInputConfig = Annotated[
    ParagraphInputConfig | SelectInputConfig | FileInputConfig | FileListInputConfig,
    Field(discriminator="type"),   # ← "type" 字段用于区分具体类型
]
```

**Pydantic 的 `discriminator`** 是自动分类的依据：

```python
# JSON 输入：{"type": "paragraph", "output_variable_name": "reason", ...}
# Pydantic 自动识别 type="paragraph" → ParagraphInputConfig

# JSON 输入：{"type": "file", "output_variable_name": "attachment", ...}
# Pydantic 自动识别 type="file" → FileInputConfig
```

各字段类型的验证规则：

| 类型 | 特性 |
|------|------|
| `ParagraphInputConfig` | 文本输入，支持默认值（常量或 VariablePool 变量） |
| `SelectInputConfig` | 下拉选择，选项来源可以是常量列表或 VariablePool 变量 |
| `FileInputConfig` | 单个文件上传，限制文件类型/扩展名/上传方式 |
| `FileListInputConfig` | 多文件上传，额外有 `number_limits` 限制 |

### 3.3 变量选择器提取（第 276-303 行）

```python
def extract_variable_selector_to_variable_mapping(self, node_id: str) -> Mapping[str, Sequence[str]]:
    variable_mappings: dict[str, Sequence[str]] = {}

    # 1. 从 form_content 的 Markdown 模板中提取变量引用
    #    例如 "请审核 {{#llm.text#}}" → 提取 ["llm", "text"]
    form_template_parser = VariableTemplateParser(template=self.form_content)
    selectors = [s.value_selector for s in form_template_parser.extract_variable_selectors()]

    # 2. 从每个 input 的 default 中提取变量引用
    for form_input in self.inputs:
        selectors = form_input.extract_variable_selectors()

    return variable_mappings
```

**为什么需要这个映射？**

GraphEngine 需要在加载 VariablePool 时知道"这个节点需要哪些上游变量"。这个方法的返回值告诉引擎："请从 VariablePool 中加载 `llm.text`、`code_1.result` 等变量"。

### 3.4 超时计算（第 264-271 行）

```python
def expiration_time(self, start_time: datetime) -> datetime:
    match self.timeout_unit:
        case TimeoutUnit.HOUR:
            return start_time + timedelta(hours=self.timeout)
        case TimeoutUnit.DAY:
            return start_time + timedelta(days=self.timeout)
```

`match/case` 是 Python 3.10+ 的模式匹配。`assert_never(self.timeout_unit)` 在最后的 `case _` 中，如果 `timeout_unit` 不是已知的两个值，类型检查器会报错——这是一个**编译期穷举检查**。

### 3.5 StringSource — 动态默认值（第 32-58 行）

```python
class StringSource(BaseModel):
    type: ValueSourceType              # CONSTANT 或 VARIABLE

    selector: Sequence[str] = ()       # type=VARIABLE 时用
    # 例如：selector = ["start", "user_name"]
    # 提交表单时从 VariablePool 读取 ["start", "user_name"] 的值作为默认值

    value: str = ""                    # type=CONSTANT 时用
    # 例如：value = "请在此输入"

    @model_validator(mode="after")
    def _validate_selector(self) -> Self:
        if self.type == CONSTANT:
            return self
        if len(self.selector) < SELECTORS_LENGTH:    # < 2
            raise ValueError(...)
        return self
```

**`mode="after"`** 的 `@model_validator` 在所有字段验证**之后**执行，此时 `self.type` 已经有值了，可以分情况校验。

### 3.6 提交校验（第 352-374 行）

```python
def validate_human_input_submission(*, inputs, user_actions, selected_action_id, form_data):
    # 校验 action_id 有效
    available_actions = {action.id for action in user_actions}
    if selected_action_id not in available_actions:
        raise HumanInputSubmissionValidationError(...)

    # 校验所有 input 字段都已填写
    provided_inputs = set(form_data.keys())
    missing_inputs = [
        form_input.output_variable_name
        for form_input in inputs
        if form_input.output_variable_name not in provided_inputs
    ]
    if missing_inputs:
        raise HumanInputSubmissionValidationError(...)
```

**亮点**：`{action.id for action in user_actions}` — Python 的推导式。`{...}` 是集合推导式（Set Comprehension），比 `[]` 列表推导式在 `in` 查找时更快（O(1) vs O(n)）。

---

## 4. Knowledge Retrieval 节点 — RAG 知识检索

**文件**：[core/workflow/nodes/knowledge_retrieval/knowledge_retrieval_node.py](api/core/workflow/nodes/knowledge_retrieval/knowledge_retrieval_node.py)
**总行数**：358 行

### 4.1 继承链

```python
class KnowledgeRetrievalNode(LLMUsageTrackingMixin, Node[KnowledgeRetrievalNodeData]):
```

**`LLMUsageTrackingMixin`**：来自 graphon 的混入类，提供了 `llm_usage` 属性来追踪 LLM token 消耗。因为这个节点在 Single Retrieval 模式下会调用 LLM 生成搜索查询，需要记录用量。

### 4.2 _run() 流程（第 100-182 行）

```
_run()
  │
  ├─ 1. 从 VariablePool 读取查询
  │    if query_variable_selector（查询变量选择器）:
  │        query = variable_pool.get(query_variable_selector)
  │        类型检查：必须是 StringSegment（字符串），否则报错
  │
  ├─ 2. 从 VariablePool 读取附件（可选）
  │    if query_attachment_selector（附件变量选择器）:
  │        attachments = variable_pool.get(query_attachment_selector)
  │        类型检查：必须是 FileSegment 或 ArrayFileSegment
  │
  ├─ 3. 调用 _fetch_dataset_retriever()
       │
       ├── 3a. 解析 metadata filtering conditions（元数据过滤条件）
       │      variable_pool.convert_template(value)  # 把 {{#node.var#}} 替换为实际值
       │
       ├── 3b. Single Retrieval 模式（用 LLM 生成查询再检索）：
       │      KnowledgeRetrievalRequest(
       │          retrieval_mode="single",
       │          model_provider=..., model_name=...,    # 哪个 LLM 模型
       │          completion_params=...,                  # LLM 参数
       │          metadata_filtering_conditions=...,     # 元数据过滤条件
       │          query=...,                              # 用户原始问题
       │      )
       │      → DatasetRetrieval.knowledge_retrieval()
       │      → LLM 将 query 改写为搜索查询 → 向量检索 → 返回结果
       │
       ├── 3c. Multiple Retrieval 模式（直接检索 + 重排）：
       │      KnowledgeRetrievalRequest(
       │          retrieval_mode="multiple",
       │          top_k=..., score_threshold=...,         # 检索参数
       │          reranking_mode="reranking_model" | "weighted_score",
       │          reranking_model={...},                    # 重排模型
       │          weights={...},                            # 加权配置
       │          attachment_ids=[...],                     # 附件 ID
       │      )
       │      → DatasetRetrieval.knowledge_retrieval()
       │      → 向量检索 top_k 结果 →（可选）Rerank 重排 → 返回
       │
  │
  └─ 4. 产出结果
       outputs = {"result": ArrayObjectSegment(value=[source.model_dump() for source in results])}
       # ArrayObjectSegment 是 VariablePool 中存储对象数组的类型
       # 下游 LLM 节点可以引用 {{#knowledge_retrieval.result#}}
```

### 4.3 两种检索模式的核心差异

```python
# 第 203-226 行：Single Retrieval
if retrieval_mode == SINGLE and query:
    model = node_data.single_retrieval_config.model
    retrieval_resource_list = self._rag_retrieval.knowledge_retrieval(
        request=KnowledgeRetrievalRequest(
            model_provider=model.provider,
            model_name=model.name,              # ← 需要一个 LLM 模型
            model_mode=model.mode,
            completion_params=model.completion_params,  # ← LLM 参数
            query=query,
            ...
        ),
    )

# 第 227-290 行：Multiple Retrieval
elif retrieval_mode == MULTIPLE:
    retrieval_resource_list = self._rag_retrieval.knowledge_retrieval(
        request=KnowledgeRetrievalRequest(
            top_k=...,                          # 只检索 top_k，不需要 LLM
            score_threshold=...,                # 相似度阈值
            reranking_mode=...,                 # 可选的重排方式
            reranking_model=...,                # 可选的重排模型（需要 Rerank 模型）
            weights=...,                        # 可选的加权设置
            ...
        ),
    )
```

| 维度 | Single | Multiple |
|------|--------|----------|
| **是否需要 LLM** | ✅ 需要一个 LLM 模型来生成搜索查询 | ❌ 不需要 LLM |
| **是否需要 Rerank 模型** | ❌ 不需要 | ⚙️ 可选 |
| **适用场景** | 用户问题是非结构化的自然语言 | 已有明确的搜索关键词 |
| **token 消耗** | 有（LLM 查询生成） | 无（除非启用 Rerank） |
| **检索质量** | 更高（LLM 优化查询） | 依赖原始 query 质量 |

### 4.4 Metadata 过滤条件解析（第 296-340 行）

```python
def _resolve_metadata_filtering_conditions(self, conditions):
    """把条件中引用的变量从 VariablePool 中解析出来"""
    for cond in conditions.conditions:
        match cond.value:
            case str():                              # 值是一个模板字符串
                segment_group = variable_pool.convert_template(value)
                # "{{#start.name#}}" → VariablePool 中的实际值
                if len(segment_group.value) == 1:
                    resolved_value = segment_group.value[0].to_object()
                else:
                    resolved_value = segment_group.text
            case _ if isinstance(value, Sequence):   # 值是一个字符串列表
                for v in value:
                    ...  # 逐个解析
            case _:
                resolved_value = value               # 常量，不解析
```

**`variable_pool.convert_template(value)`** 是 VariablePool 的核心方法之一：把一个包含 `{{#selector#}}` 的模板字符串替换为实际值，返回一个 `SegmentGroup`（包含解析后的文本和结构化数据）。

---

## 5. Knowledge Index 节点 — 知识索引入库

**文件**：[core/workflow/nodes/knowledge_index/knowledge_index_node.py](api/core/workflow/nodes/knowledge_index/knowledge_index_node.py)
**总行数**：176 行

### 5.1 这个节点的特殊之处

```python
class KnowledgeIndexNode(Node[KnowledgeIndexNodeData]):
    node_type = KNOWLEDGE_INDEX_NODE_TYPE
    execution_type = NodeExecutionType.RESPONSE   # ← 关键！
```

**`execution_type = RESPONSE`**：告诉 GraphEngine，这个节点的输出是"最终输出"（类似 `End` 和 `Answer` 节点）。执行到它就结束。

### 5.2 _run() 流程（第 52-137 行）

```
_run()
  │
  ├─ 1. 从 VariablePool 读取系统变量
  │    dataset_id = get_system_segment(variable_pool, DATASET_ID)
  │    document_id = get_system_segment(variable_pool, DOCUMENT_ID)
  │    invoke_from = get_system_text(variable_pool, INVOKE_FROM)
  │    is_preview = invoke_from == "debugger"
  │
  ├─ 2. 从 VariablePool 读取数据块
  │    chunks = variable_pool.get(index_chunk_variable_selector)
  │    # 这些 chunks 来自上游的文档提取节点
  │
  ├─ 3. 分支路径
  │
  │    Preview 模式（is_preview=True）：
  │    ├── 不写入数据库
  │    ├── index_processor.get_preview_output(
  │    │       chunks, dataset_id, document_id, chunk_structure, summary_index_setting
  │    │   )
  │    └── 返回预览结果（chunk 分块 + summary 总结的预览）
  │
  │    正式模式（is_preview=False）：
  │    ├── index_processor.index_and_clean(
  │    │       dataset_id, document_id, original_document_id,
  │    │       chunks, batch, summary_index_setting
  │    │   )
  │    │   ↓
  │    │   1. 切分文档为 chunks
  │    │   2. 每个 chunk → Embedding 模型 → 向量化
  │    │   3. 写入向量数据库（QDrant/Weaviate/Milvus...）
  │    │   4. 清理旧索引
  │    │
  │    ├── session.commit()  # 必须先提交，让 summary 生成时能看到新数据
  │    │
  │    └── summary_index_service.generate_and_vectorize_summary(
  │            dataset_id, document_id, is_preview, summary_index_setting
  │        )
  │        ↓
  │        如果配置了 Summary Index：
  │        1. 调用 LLM 为每个 chunk 生成摘要
  │        2. 摘要 → Embedding → 写入向量数据库
  │        3. 检索时优先匹配摘要，命中后再返回完整 chunk
  │
  └─ 4. 返回结果
       return NodeRunResult(status=SUCCEEDED, outputs=results)
```

### 5.3 Preview vs 正式模式

```python
# 第 83-102 行
if is_preview:
    # 预览：不写库，直接返回分块结果
    outputs = self.index_processor.get_preview_output(
        chunks, dataset_id, document_id, chunk_structure, summary_index_setting, session
    )
    return NodeRunResult(status=SUCCEEDED, outputs=outputs.model_dump(exclude_none=True))

# 正式：写库 + 生成摘要索引
results = self._invoke_knowledge_index(
    dataset_id=dataset_id, document_id=document_id,
    original_document_id=..., batch=batch.value,
    chunks=chunks, summary_index_setting=...,
)
```

### 5.4 `_invoke_knowledge_index` 为什么先 commit 再 summary（第 139-161 行）

```python
def _invoke_knowledge_index(self, ..., session: Session):
    # Step 1: 索引入库
    rst = self.index_processor.index_and_clean(
        dataset_id, document_id, original_document_id,
        chunks, batch, summary_index_setting, session=session,
    )
    # Step 2: 提交事务 ← 确保 summary 生成时能看到刚写入的 chunk 数据
    session.commit()

    # Step 3: 生成摘要（可能有独立的数据库查询）
    # SummaryIndex.generate_and_vectorize_summary() 内部会开独立的 session
    self.summary_index_service.generate_and_vectorize_summary(
        dataset_id, document_id, is_preview, summary_index_setting
    )
    return rst
```

**如果 Step 1 和 Step 3 共享同一个 session**，summary 生成的数据库查询会看到**未被 commit 的脏数据** → 可能查不到刚写入的 chunk → 摘要生成失败。所以先 commit 再调用 summary 是必要的。

---

## 总结：5 个自定义节点的设计差异

| 节点 | 核心机制 | 依赖方式 | 输出方式 |
|------|---------|---------|---------|
| **Agent v1** | 策略模式（插件提供 Agent 实现） | `StrategyResolver` | 工具消息流 → `AgentMessageTransformer` |
| **Agent v2** | 外部 Agent Backend（SSE 事件流） | `AgentBackendRunClient` | 输出适配器 + 类型检查 + 失败编排 |
| **Human Input** | 暂停 + 表单 + 恢复 | Dify 的 HITL 表单系统 | 表单提交结果写入 VariablePool |
| **Knowledge Retrieval** | RAG（Single=LLM查询优化, Multiple=直接检索） | `DatasetRetrieval` | `ArrayObjectSegment[Source]` |
| **Knowledge Index** | 文档分块 + 向量化 + 入库 | `IndexProcessor` + `SummaryIndex` | 索引结果（结果 JSON） |

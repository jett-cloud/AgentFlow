# Dify 工作流管理系统 — 深入详解

> 接续 [ARCHITECTURE_GUIDE.md](ARCHITECTURE_GUIDE.md)，深入讲解工作流引擎的完整设计。

---

## 目录

1. [概述：工作流在 Dify 中的定位](#1-概述工作流在-dify-中的定位)
2. [数据模型层](#2-数据模型层)
3. [核心引擎层](#3-核心引擎层)
4. [节点系统](#4-节点系统)
5. [变量系统](#5-变量系统)
6. [触发器系统](#6-触发器系统)
7. [暂停与恢复机制](#7-暂停与恢复机制)
8. [异步执行流程](#8-异步执行流程)
9. [完整请求追踪](#9-完整请求追踪)

---

## 1. 概述：工作流在 Dify 中的定位

工作流（Workflow）是 Dify 的核心执行引擎。无论是 Chat App、Agent App、还是 Workflow App，最终都是将用户配置转换为一张**有向无环图（DAG）**，然后由工作流引擎逐个节点执行。

### 1.1 工作流的三种形态

```
┌──────────────────────────────────────────────────┐
│  前端画布 (Canvas)                                │
│  用户在 UI 中拖拽节点、连线、配置参数               │
│  ↓ 保存为 JSON (graph) 存入 Workflow 表           │
└──────────────────────────────────────────────────┘
                     ↓
┌──────────────────────────────────────────────────┐
│  草稿版本 (Draft)                                 │
│  version = "draft"，每个 App 只有一个 draft       │
│  用于调试和迭代                                    │
└──────────────────────────────────────────────────┘
                     ↓ 发布 (publish)
┌──────────────────────────────────────────────────┐
│  发布版本 (Published)                              │
│  version = 时间戳，不可变快照                       │
│  用于生产环境的 API 调用                            │
└──────────────────────────────────────────────────┘
```

### 1.2 核心组件关系图

```
┌─────────────────────────────────────────────────────────┐
│ controllers/console/app/workflow.py                     │
│ 接收 HTTP 请求，解析参数，调用服务层                      │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│ services/workflow_service.py                            │
│ 编排逻辑：发布、同步草稿、运行调试、处理暂停/恢复         │
└──┬────────┬──────────┬──────────┬──────────────────────┘
   │        │          │          │
   ▼        ▼          ▼          ▼
┌──────┐ ┌──────┐ ┌────────┐ ┌──────────────────────┐
│models│ │core/ │ │services│ │tasks/                 │
│/     │ │work- │ │/async_ │ │async_workflow_tasks   │
│work- │ │flow/ │ │workflow│ │执行异步工作流           │
│flow  │ │引擎  │ │_service│ └──────────────────────┘
│.py   │ │      │ │触发分发 │
│持久化│ │      │ └────────┘
└──────┘ └──────┘
```

### 1.3 关键文件速查表

| 文件 | 职责 |
|------|------|
| `models/workflow.py` | 所有工作流相关的 ORM 模型（10+ 个表） |
| `core/workflow/workflow_entry.py` | 工作流入口，创建 GraphEngine 并运行 |
| `core/workflow/node_factory.py` | 节点工厂，将图配置转为节点实例 |
| `core/workflow/nodes/` | 各类型节点的实现（LLM、Code、HTTP、Agent...） |
| `core/workflow/system_variables.py` | 系统变量定义和管理 |
| `core/workflow/variable_pool_initializer.py` | 变量池初始化逻辑 |
| `services/workflow_service.py` | 工作流服务层（发布、运行、调试） |
| `services/async_workflow_service.py` | 异步工作流触发和分发 |
| `services/workflow/entities.py` | 触发器和异步执行的 Pydantic 模型 |
| `services/workflow/queue_dispatcher.py` | 队列分发（根据订阅等级） |
| `tasks/async_workflow_tasks.py` | Celery 异步任务（实际执行工作流） |

---

## 2. 数据模型层

`models/workflow.py` 是整个工作流系统的持久化基础，定义了约 10 张数据库表。

### 2.1 核心表：Workflow

```python
class Workflow(Base):
    __tablename__ = "workflows"

    id: str             # UUID 主键
    tenant_id: str      # 租户隔离
    app_id: str         # 所属应用
    type: WorkflowType  # "workflow" | "chat" | "rag-pipeline" | "snippet"
    kind: WorkflowKind  # "standard" | "snippet"
    version: str        # "draft" (草稿) 或时间戳 (已发布版本)
    graph: str          # JSON 字符串 — 核心！存储完整的画布配置
    features: str       # JSON — 功能配置（文件上传、TTS、敏感词等）
    environment_variables: str  # JSON — 环境变量
    conversation_variables: str # JSON — 对话变量
    created_by / updated_by
    created_at / updated_at
```

**关键理解**：
- `graph` 是整个工作流的核心，它是一个 JSON，包含 `nodes`（节点列表）和 `edges`（边列表）
- `version = "draft"` 是唯一的草稿版本，每次在画布上编辑都是修改这条记录
- 发布时，以当前 draft 的 graph 为蓝本，创建一条新的 `version = 时间戳` 的记录

### 2.2 执行记录表

```
Workflow                   (工作流定义)
  │
  └── WorkflowRun          (每次执行产生的运行记录)
        │
        ├── WorkflowNodeExecution  (每个节点的执行记录)
        │     │
        │     └── WorkflowNodeExecutionOffload  (大数据卸载到外部存储)
        │
        ├── WorkflowPause   (暂停状态，0 或 1 个)
        │     │
        │     └── WorkflowPauseReason  (暂停原因)
        │
        └── WorkflowAppLog  (生产环境的执行日志)
              │
              └── WorkflowArchiveLog  (归档日志)
```

**各表核心字段**：

```
WorkflowRun:
  id, tenant_id, app_id, workflow_id
  type, triggered_from    ← 触发来源 (debugging/app-run/webhook/schedule)
  version, graph (快照), inputs, outputs
  status                  ← running/succeeded/failed/stopped/paused
  error, elapsed_time, total_tokens, total_steps
  created_by_role, created_by
  created_at, finished_at

WorkflowNodeExecution:
  id, tenant_id, app_id, workflow_id
  workflow_run_id (可为空，单步调试时为空)
  node_id, node_type, title
  inputs, process_data, outputs  ← 可能被 offload 到外部存储
  status, error, elapsed_time
  execution_metadata     ← {total_tokens, total_price, currency, ...}
  created_at, finished_at

WorkflowPause:
  workflow_id, workflow_run_id   ← 一对一关联 WorkflowRun
  state_object_key               ← 指向外部存储中的 GraphEngine 序列化状态
  resumed_at                     ← NULL = 仍在暂停中

WorkflowDraftVariable:
  app_id, user_id, node_id, name, selector
  value, value_type              ← 变量值和类型
  node_execution_id              ← 哪个节点执行产生的
  file_id                        ← 大变量卸载到外部存储的引用
```

---

## 3. 核心引擎层

### 3.1 引擎架构

```
WorkflowEntry (Dify 层)
     │
     │  封装 graphon 库的 GraphEngine
     │
     ▼
GraphEngine (graphon 库 — 通用图执行引擎)
     │
     │  按拓扑顺序调度节点执行
     │  管理 VariablePool (变量池)
     │
     ▼
Node 实例 (各类型节点的运行时)
     │
     │  每个 Node.run() 返回 Generator[GraphNodeEvent]
     │  实现具体的 LLM 调用、代码执行、HTTP 请求等
     ▼
```

### 3.2 WorkflowEntry — 工作流入口

```python
# core/workflow/workflow_entry.py (简化)

class WorkflowEntry:
    def __init__(
        self,
        tenant_id, app_id, workflow_id,
        graph_config: dict,       # 图配置 (nodes + edges)
        graph: Graph,             # 已解析的图对象
        user_id, user_from, invoke_from,
        call_depth,               # 工作流嵌套调用深度
        variable_pool: VariablePool,      # 变量池
        graph_runtime_state: GraphRuntimeState,
        command_channel,          # 外部控制通道
    ):
        # 1. 检查嵌套深度
        if call_depth > WORKFLOW_CALL_MAX_DEPTH:
            raise ValueError("Max workflow call depth reached.")

        # 2. 创建 GraphEngine
        self.graph_engine = GraphEngine(
            workflow_id=workflow_id,
            graph=graph,
            graph_runtime_state=graph_runtime_state,
            command_channel=command_channel,
            config=GraphEngineConfig(
                min_workers=..., max_workers=...,  # 并发控制
            ),
            child_engine_builder=...,  # 支持子工作流
        )

        # 3. 添加执行层 (Layers)
        self.graph_engine.layer(ExecutionLimitsLayer(     # 执行限制
            max_steps=..., max_time=...
        ))
        self.graph_engine.layer(LLMQuotaLayer(            # LLM 配额
            tenant_id=tenant_id
        ))
        if ENABLE_OTEL:
            self.graph_engine.layer(ObservabilityLayer()) # 可观测性

    def run(self) -> Generator[GraphEngineEvent]:
        """运行工作流，返回事件流"""
        generator = iter_dify_graph_engine_events(self.graph_engine)
        yield from generator
```

**关键概念**：
- **VariablePool**：一个全局变量池，节点之间通过它传递数据。用 `[node_id, variable_name]` 作为 selector 来读写变量。
- **GraphEngine**：来自 `graphon` 库的通用图执行引擎，负责按拓扑顺序调度节点、处理并行分支。
- **Layers（执行层）**：类似中间件，可以在节点执行前后插入逻辑（限流、日志、配额检查）。
- **事件流**：`run()` 不返回最终结果，而是返回 `Generator[GraphEngineEvent]`。调用方逐条消费事件，可以实时获取每个节点的执行状态。

### 3.3 GraphEngine 的执行模型

```
                    ┌─────────┐
                    │  START  │
                    └────┬────┘
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
         ┌────────┐ ┌────────┐ ┌────────┐
         │  LLM   │ │  CODE  │ │ HTTP   │  ← 并行分支
         └───┬────┘ └───┬────┘ └───┬────┘
             │           │          │
             └───────────┼──────────┘
                         ▼
                    ┌─────────┐
                    │   END   │
                    └─────────┘
```

GraphEngine 会：
1. 从 START 节点开始
2. 找到所有后继节点
3. **并行**执行没有依赖关系的节点
4. 等待所有前置节点完成后才执行下游节点
5. 节点通过 `VariablePool` 读写数据，实现数据传递

---

## 4. 节点系统

### 4.1 节点注册机制

Dify 的节点系统使用**自动注册模式**：

```python
# core/workflow/node_factory.py (简化)

# 节点类型 → 版本 → 节点类 的二级映射表
NODE_TYPE_CLASSES_MAPPING: dict[NodeType, dict[str, type[Node]]] = {}

# 通过 import 自动注册
# graphon 内置节点：graphon.nodes.* (LLM, Code, HTTP, Start, End, Answer...)
# Dify 自定义节点：core.workflow.nodes.* (Agent, KnowledgeRetrieval, HumanInput...)

def resolve_workflow_node_class(node_type, node_version) -> type[Node]:
    """根据类型和版本号解析节点类"""
    node_mapping = NODE_TYPE_CLASSES_MAPPING.get(node_type)
    return node_mapping.get(node_version) or node_mapping.get("latest")
```

### 4.2 节点类型一览

**graphon 内置节点** (`graphon/nodes/`)：
| 节点类型 | 说明 |
|----------|------|
| `start` | 工作流入口，定义输入变量 |
| `end` | 工作流出口，定义输出变量 |
| `answer` | Chat 应用的回复节点 |
| `llm` | LLM 调用节点 |
| `code` | 代码执行节点（Python3/JS） |
| `http-request` | HTTP 请求节点 |
| `template-transform` | Jinja2 模板节点 |
| `variable-aggregator` | 变量聚合器 |
| `variable-assigner` | 变量赋值器 |
| `parameter-extractor` | 参数提取器 |
| `question-classifier` | 问题分类器 |
| `knowledge-retrieval` | 知识库检索 |
| `document-extractor` | 文档提取器 |
| `if-else` | 条件分支 |
| `iteration` | 迭代/循环节点 |
| `loop` | 循环节点 |
| `tool` | 工具调用节点 |

**Dify 自定义节点** (`core/workflow/nodes/`)：
| 节点类型 | 说明 |
|----------|------|
| `agent` | 传统 Agent 策略节点 |
| `agent-v2` | 新版 Agent（基于 Agent Backend） |
| `human-input` | 人工输入/HITL 节点 |
| `datasource` | 数据源节点 |
| `knowledge-index` | 知识索引节点 |
| `trigger-webhook` | Webhook 触发器 |
| `trigger-schedule` | 定时触发器 |
| `trigger-plugin` | 插件触发器 |

### 4.3 DifyNodeFactory — 节点工厂

```python
# core/workflow/node_factory.py (核心方法)

class DifyNodeFactory(NodeFactory):
    def create_node(self, node_config) -> Node:
        """将图配置转为节点实例"""

        # 1. 解析节点类型和版本
        node_data = node_config["data"]
        node_class = resolve_workflow_node_class(node_data.type, node_data.version)

        # 2. 根据节点类型准备不同的依赖注入
        if node_type == "llm":
            kwargs = {
                "model_instance": build_model_instance(...),
                "memory": build_memory(...),
                "prompt_message_serializer": ...,
                # ... 更多 LLM 专属依赖
            }
        elif node_type == "code":
            kwargs = {"code_executor": ..., "code_limits": ...}
        elif node_type == "http-request":
            kwargs = {"http_client": ..., "http_request_config": ...}
        elif node_type == "agent":
            kwargs = {"strategy_resolver": ..., "runtime_support": ...}
        # ... 更多类型

        # 3. 构造节点实例
        return node_class(
            node_id=node_id,
            data=resolved_node_data,
            graph_init_params=...,
            graph_runtime_state=...,
            **kwargs,
        )
```

**设计亮点**：DifyNodeFactory 是一个巨大的依赖注入容器。每种节点类型需要的依赖不同（LLM 节点需要模型实例、Code 节点需要代码执行器、HTTP 节点需要 HTTP 客户端），工厂负责组装这些依赖。

### 4.4 单个节点的运行

```python
# 每个 Node 都实现 run() 方法
class LLMNode(Node):
    def run(self) -> Generator[GraphNodeEvent]:
        # 1. 从 VariablePool 读取输入变量
        prompt = self.graph_runtime_state.variable_pool.get(["sys", "query"])

        # 2. 执行业务逻辑（调用 LLM）
        yield NodeRunStartedEvent(...)
        response = self.model_instance.invoke(prompt)
        yield NodeRunStreamChunk(...)  # 流式输出

        # 3. 将输出写入 VariablePool
        self.graph_runtime_state.variable_pool.add(
            [self.node_id, "text"], response
        )

        yield NodeRunSucceededEvent(...)
```

---

## 5. 变量系统

### 5.1 VariablePool（变量池）

变量池是工作流中**节点间通信的唯一机制**。它是一个以 `[node_id, ...path]` 为 key 的存储结构：

```python
# VariablePool 中的 selector 示例
["start", "query"]           # START 节点的 query 输入
["llm", "text"]              # LLM 节点的输出文本
["http_request", "body"]     # HTTP 请求节点的响应体
["sys", "query"]             # 系统变量：当前用户输入
["sys", "files"]             # 系统变量：上传的文件
["sys", "conversation_id"]   # 系统变量：对话ID
["sys", "workflow_run_id"]   # 系统变量：本次运行ID
["env", "API_KEY"]           # 环境变量
["conversation", "name"]     # 对话变量
```

### 5.2 变量的生命周期

```
1. 初始化阶段
   ├── 系统变量（sys.*）     → VariablePool
   ├── 环境变量（env.*）     → VariablePool
   └── 对话变量（conversation.*）→ VariablePool

2. START 节点执行
   └── 用户输入写入 pool（start.xxx）

3. 中间节点执行
   ├── 从 pool 读入前置节点的输出
   └── 将自己的输出写入 pool（node_id.xxx）

4. END/ANSWER 节点执行
   ├── 从 pool 读取需要的变量
   └── 输出最终结果
```

### 5.3 DraftVariable（草稿变量）

在调试模式下，每个节点的输出会被保存为 `WorkflowDraftVariable`：

```
WorkflowDraftVariable:
  node_id: "llm"            ← 哪个节点产生的
  name: "text"              ← 变量名
  value: "Hello, World!"    ← JSON 序列化的值
  value_type: "string"      ← 值的类型
  node_execution_id: "xxx"  ← 关联到 WorkflowNodeExecution

用途：
- 调试面板中显示每个节点的中间结果
- 单步调试时可以修改中间变量
- 大变量（文件、长文本）会被 offload 到外部存储
```

---

## 6. 触发器系统

工作流可以用多种方式触发执行：

### 6.1 触发方式枚举

```
触发来源 (WorkflowRunTriggeredFrom):
├── debugging         ← 画布调试
├── app-run           ← 发布的 App 被 API 调用
├── webhook           ← Webhook 触发
├── schedule          ← 定时触发
└── plugin            ← 插件事件触发
```

### 6.2 异步触发流程

```
外部事件 (Webhook / Schedule / Plugin)
     │
     ▼
AsyncWorkflowService.trigger_workflow_async()
     │
     ├── 1. 验证 App 和 Workflow 存在
     ├── 2. 检查配额 (QuotaService.reserve)
     ├── 3. 创建 WorkflowTriggerLog (状态: PENDING)
     ├── 4. 根据订阅等级选择队列:
     │     ├── Professional  → execute_workflow_professional.delay()
     │     ├── Team          → execute_workflow_team.delay()
     │     └── Sandbox       → execute_workflow_sandbox.delay()
     ├── 5. 更新状态: QUEUED
     └── 6. 返回 AsyncTriggerResponse (立即返回，不等待执行完成)
                │
                ▼
     Celery Worker 异步执行:
     ├── 读取 WorkflowTriggerLog
     ├── 创建 WorkflowRun
     ├── 运行 WorkflowEntry
     ├── 更新 WorkflowRun 和 WorkflowNodeExecution
     └── 更新 WorkflowTriggerLog (COMPLETED / FAILED)
```

### 6.3 关键设计：非阻塞

**所有触发方法立即返回**，实际执行在 Celery Worker 中异步发生。调用方通过 `workflow_trigger_log_id` 轮询执行状态。

```python
# services/async_workflow_service.py (核心方法签名)
class AsyncWorkflowService:
    @classmethod
    def trigger_workflow_async(
        cls, user, trigger_data: TriggerData, *, session: Session
    ) -> AsyncTriggerResponse:
        """非阻塞！立即返回，不等待工作流执行完成"""
        ...

    @classmethod
    def get_trigger_log(
        cls, workflow_trigger_log_id: str
    ) -> WorkflowTriggerLogDict | None:
        """查询执行状态"""
        ...
```

---

## 7. 暂停与恢复机制

Dify 支持在执行过程中暂停工作流（例如等待人工输入），然后从断点恢复。

### 7.1 暂停流程

```
1. 节点执行到需要暂停的地方（如 human_input 节点）
     │
2. 节点 yield PauseEvent
     │
3. GraphEngine 捕获 PauseEvent:
   ├── 序列化 GraphEngine 的完整运行时状态
   ├── 保存到外部存储 (S3/OSS)
   ├── 创建 WorkflowPause 记录 (state_object_key 指向存储位置)
   ├── 创建 WorkflowPauseReason 记录 (记录暂停原因)
   └── 更新 WorkflowRun 状态: running → paused
```

### 7.2 恢复流程

```
1. 人工输入完成，触发恢复
     │
2. WorkflowService.resume_workflow_run()
     │
3. 从外部存储加载序列化的 GraphEngine 状态
     │
4. 反序列化恢复 GraphEngine：
   ├── 恢复 VariablePool
   ├── 恢复 GraphRuntimeState
   └── 恢复 ResponseStreamFilter
     │
5. 从暂停点继续执行
     │
6. 标记 WorkflowPause.resumed_at = now()
```

### 7.3 关键数据结构

```python
class WorkflowPause(TypeBase):
    workflow_id: str
    workflow_run_id: str           # 一对一关联 WorkflowRun
    state_object_key: str          # 外部存储的 key
    resumed_at: datetime | None    # NULL = 仍在暂停

class WorkflowPauseReason(TypeBase):
    pause_id: str
    type_: PauseReasonType          # HITL_REQUIRED | SCHEDULED_PAUSE
    form_id: str                    # 如果是人工输入，关联表单
    node_id: str                    # 哪个节点导致暂停
```

---

## 8. 异步执行流程

### 8.1 队列系统

Dify 根据订阅等级使用不同的 Celery 队列：

```python
# services/workflow/queue_dispatcher.py

class QueuePriority(StrEnum):
    PROFESSIONAL = "professional"   # 高优先级
    TEAM = "team"                   # 中优先级
    SANDBOX = "sandbox"             # 低优先级（免费版）

class QueueDispatcherManager:
    def get_dispatcher(self, tenant_id):
        # 根据租户的订阅等级返回对应的 dispatcher
        plan = BillingService.get_plan(tenant_id)
        if plan == CloudPlan.PROFESSIONAL:
            return ProfessionalDispatcher()
        elif plan == CloudPlan.TEAM:
            return TeamDispatcher()
        else:
            return SandboxDispatcher()
```

### 8.2 Celery Task 执行流

```python
# tasks/async_workflow_tasks.py (简化)

@shared_task(queue="professional", bind=True, max_retries=3)
def execute_workflow_professional(self, task_data_dict):
    """在高优先级队列中执行工作流"""
    task_data = WorkflowTaskData.model_validate(task_data_dict)

    # 1. 从 DB 加载 trigger log
    trigger_log = get_trigger_log(task_data.workflow_trigger_log_id)

    # 2. 创建 WorkflowRun 记录
    workflow_run = create_workflow_run(trigger_log)

    # 3. 运行工作流
    try:
        entry = WorkflowEntry(...)
        for event in entry.run():
            # 持久化每个节点的执行记录
            save_node_execution(event)
            # 更新 WorkflowRun 状态
            update_workflow_run(workflow_run, event)

        # 4. 标记成功
        trigger_log.status = COMPLETED
    except Exception as e:
        # 5. 失败重试
        trigger_log.status = FAILED
        raise self.retry(exc=e, countdown=60)
```

### 8.3 定时调度

```python
# schedule/workflow_schedule_task.py
# Celery Beat 定时调用

@shared_task
def poll_workflow_schedules():
    """扫描所有到期的定时触发器"""
    due_schedules = get_due_schedules()
    for schedule in due_schedules:
        AsyncWorkflowService.trigger_workflow_async(
            user=schedule.owner,
            trigger_data=ScheduleTriggerData(
                app_id=schedule.app_id,
                ...
            ),
        )
```

---

## 9. 完整请求追踪

### 场景：用户在画布上点击"调试运行"

```
1. HTTP POST /console/api/apps/{app_id}/workflows/draft/run
   Controller: WorkflowDraftRunApi.post()

2. Controller 解析参数
   - inputs: {"query": "Hello"}
   - files: []

3. Controller 调用
   WorkflowService.run_draft_workflow(
       app_model, draft_workflow, user_inputs, account
   )

4. WorkflowService.run_draft_workflow()
   ├── 4.1 确认是 draft 版本
   ├── 4.2 创建 VariablePool
   │       ├── add_system_variables()  ← sys.query, sys.files, sys.user_id...
   │       └── add_node_inputs_to_pool()  ← start.query = "Hello"
   ├── 4.3 创建 Graph (解析 graph JSON → nodes + edges + 拓扑)
   ├── 4.4 创建 WorkflowEntry
   │       ├── DifyNodeFactory  ← 负责创建每个节点实例
   │       ├── GraphEngine     ← 图执行引擎
   │       └── Layers          ← ExecutionLimits, LLMQuota...
   └── 4.5 entry.run() → Generator[GraphEngineEvent]

5. 逐事件处理 (WorkflowService 消费 Generator)
   for event in entry.run():
       if event is NodeRunStartedEvent:
           → 创建 WorkflowNodeExecution (status=running)
           → 保存 inputs

       if event is NodeRunSucceededEvent:
           → 更新 WorkflowNodeExecution (status=succeeded)
           → 保存 outputs, process_data
           → 创建 WorkflowDraftVariable (用于调试面板)
           → 如果 outputs 太大 → WorkflowNodeExecutionOffload

       if event is NodeRunFailedEvent:
           → 更新 WorkflowNodeExecution (status=failed, error)

       yield event (发送给前端 WebSocket)

6. 全部节点执行完毕
   → WorkflowRun 状态: succeeded
   → 计算 elapsed_time, total_tokens
```

### 场景：Webhook 触发生产环境工作流

```
1. HTTP POST /trigger/{app_id}/webhook
   → TriggerController.receive_webhook()

2. 创建 TriggerData
   trigger_data = WebhookTriggerData(
       app_id=..., tenant_id=..., workflow_id=...,
       root_node_id=..., inputs=..., files=...
   )

3. AsyncWorkflowService.trigger_workflow_async(user, trigger_data)
   ├── 创建 WorkflowTriggerLog (status=PENDING)
   ├── 检查配额
   ├── 选择队列 → execute_workflow_sandbox.delay(task_data)
   ├── 更新 status=QUEUED
   └── 立即返回 {"workflow_trigger_log_id": "...", "status": "queued"}

4. Celery Worker (后台)
   execute_workflow_sandbox(task_data)
   ├── 加载 published workflow
   ├── 创建 WorkflowRun
   ├── 运行 WorkflowEntry
   │   └── 使用 published workflow 的 graph (不可变快照)
   ├── 持久化所有 NodeExecution
   └── 更新 WorkflowTriggerLog (COMPLETED/FAILED)

5. 调用方通过 workflow_trigger_log_id 查询:
   GET /console/api/apps/{app_id}/workflow-trigger-logs/{id}
   → 返回 {status, outputs, elapsed_time, error, ...}
```

---

## 附录：关键设计决策

| 决策 | 原因 |
|------|------|
| graph 存为 JSON 字符串 | 灵活存储任意图结构，不做 schema 限制 |
| Draft vs Published 双版本 | Draft 可随意编辑调试；Published 是不可变快照，保证生产稳定性 |
| Generator 事件流而非直接返回结果 | 支持实时推送到前端（WebSocket/SSE），实现流式输出和进度展示 |
| VariablePool 而非函数传参 | 图中有并行分支，无法用简单的函数调用链传递数据 |
| 执行层 (Layers) 模式 | 非侵入式地添加横切关注点（限流、日志、配额），不影响节点实现 |
| 大变量 Offload 机制 | 避免数据库行过大，将大数据存储到 S3/OSS |
| 暂停状态序列化到外部存储 | 支持长时间暂停（数小时到数天），不占用数据库空间 |
| 非阻塞异步触发 | Webhook 等触发场景需要立即返回 200，不能等待工作流执行完成 |

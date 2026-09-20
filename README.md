# AgentFlow

> A visual AI Agent workflow platform for building LLM, RAG, MCP and tool-calling applications.

AgentFlow 是一个面向 AI 应用开发的可视化 Agent 工作流平台，支持工作流编排、LLM、RAG、MCP 工具接入、Tool Calling 与流式 Agent 执行。

基于 Vue 3 + Python 构建，项目聚焦于 AI Agent 工作流的可视化编排、工具调用与运行过程展示。

## Core Features

- **Visual Workflow Builder** — 基于可视化节点构建和编排 AI 工作流
- **Agent Execution** — 支持 Agent 运行与任务执行流程
- **RAG / Knowledge Base** — 支持知识库与检索增强生成
- **MCP Integration** — 接入 MCP Server 与外部工具
- **Streaming Workflow Assist** — 基于 SSE 展示实时 Agent / Workflow 执行过程
- **AI Tool Generator** — AI 辅助生成、校验和管理工具插件
- **Docker Development Environment** — 提供完整的本地容器化开发环境

## Preview

### Visual Workflow

![Visual Workflow](docs/screenshots/work-flow.png)

### Workflow Assist

![Workflow Assist](docs/screenshots/work-assistant.png)

### AI Tool Generator

![AI Tool Generator](docs/screenshots/tool.png)

## What I Built

AgentFlow 基于 Dify 的开源能力进行扩展和重新组织，项目重点聚焦于 AI Agent 工作流的可视化编排、运行过程展示以及 MCP 工具集成。

在现有开源基础上，本项目主要进行了以下开发和整合：

- **独立 Vue 3 工作流前端** — 使用 Vue 3、Vite、Pinia、Vue Router 和 Vue Flow 构建独立的工作流管理界面。
- **Visual Workflow Editor** — 实现可视化节点编排、节点状态管理、工作流 DSL 处理以及运行状态展示。
- **Streaming Workflow Assist** — 实现基于 SSE 的流式消息处理、Agent 执行状态展示、会话管理以及运行事件展示。
- **MCP Integration** — 集成 MCP Client、Tool Provider 管理、OAuth 回调以及 MCP 工具调用能力。
- **AI Tool Generator** — 提供 AI 辅助工具插件生成、校验、测试、发布以及卸载相关能力。
- **Dataset Management UI** — 提供知识库、文档、检索测试、数据管道和外部知识库相关管理界面。
- **Local Development Environment** — 整合 Docker Compose、PostgreSQL、Redis、Vector Database、Sandbox 和 Agent Runtime，提供本地开发环境。

> AgentFlow 不是从零重新实现 Dify，而是在其开源基础上进行学习、集成、裁剪和功能扩展。项目中来自上游 Dify 的代码及相关许可信息请参见 [LICENSE](LICENSE)。

## Architecture

AgentFlow 采用前后端分离架构，并通过 Agent Runtime、数据库、缓存和向量数据库提供 AI Workflow 的运行能力。

```text
┌─────────────────────────────────────────────┐
│                Web Browser                  │
└─────────────────────┬───────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────┐
│          Vue 3 / Vite Frontend              │
│                                             │
│  Workflow Editor · Dataset · MCP · Assist   │
└─────────────────────┬───────────────────────┘
                      │ REST / SSE
                      ▼
┌─────────────────────────────────────────────┐
│              Python API                     │
│                                             │
│ Workflow · Agent · Dataset · MCP · Tools    │
└───────────────┬─────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────┐
│              Agent Runtime                  │
│                                             │
│        LLM · Tool Calling · MCP             │
└───────────────┬─────────────────────────────┘
                │
        ┌───────┼────────┐
        ▼       ▼        ▼
   PostgreSQL  Redis   Vector DB
```

### Tech Stack

| Layer | Directory | Technologies |
| --- | --- | --- |
| Frontend | `agent-flow-frontend/` | Vue 3, Vite, Pinia, Vue Router, Vue Flow, Element Plus |
| Backend API | `api/` | Python 3.12, Flask, Celery, SQLAlchemy, Pydantic, uv |
| Agent SDK | `dify-agent/` | Python, Pydantic AI, HTTPX |
| Agent Runtime | `dify-agent-runtime/` | Go |
| Infrastructure | `docker/` | Docker Compose, PostgreSQL, Redis, Sandbox, Vector Database |

## Project Structure

```text
AgentFlow/
├── agent-flow-frontend/   # Vue 3 / Vite 工作流前端
├── api/                   # Python API 与工作流服务
├── dify-agent/            # Agent Python SDK 与服务
├── dify-agent-runtime/    # Go Agent Runtime
├── docker/                # Docker Compose 与本地开发环境
└── docs/                  # 项目文档与功能截图
```

## Requirements

- Node.js 22 与 npm
- Python 3.12
- Docker Desktop 与 Docker Compose

## Quick Start

### 1. Prepare the environment

在项目根目录生成本地环境配置：

```bash
python docker/prepare_dev_env.py
```

### 2. Start the backend

```bash
docker compose -f docker/docker-compose.yaml -f docker/docker-compose.local.yaml up -d --build
```

### 3. Start the frontend

在另一个终端运行：

```bash
cd agent-flow-frontend
npm ci
npm run dev
```

浏览器访问 [http://localhost:5173/agentFlow/](http://localhost:5173/agentFlow/)。

## Project Status

AgentFlow 当前处于持续开发阶段，适合用于 AI Agent 工作流、MCP 工具集成、RAG 和 Tool Calling 的学习、开发与功能验证。用于生产环境前，请根据实际场景完成安全、权限、数据备份和部署配置。

## Acknowledgements

AgentFlow 基于 [Dify](https://github.com/langgenius/dify) 的开源能力进行裁剪和扩展，感谢 Dify 及其社区提供的基础能力。

## License

本仓库包含来自 Dify 的开源代码，并遵循 [LICENSE](LICENSE) 中列出的许可证及附加条件。使用、修改或重新分发本项目之前，请完整阅读相关条款。

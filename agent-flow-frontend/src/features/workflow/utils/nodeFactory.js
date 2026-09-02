// src/views/copilot/utils/nodeFactory.js

// 1. 每种节点类型的默认属性（配方表）
export const NODE_DEFAULTS = {
    llm: {
        promptTemplate: '',
        prompt_template: '',
        imageUrl: '',
        model: { provider: 'openai', name: 'gpt-4o-mini', mode: 'chat' }
    },
    LLM_TASK: {
        promptTemplate: '',
        prompt_template: '',
        imageUrl: '',
        model: { provider: 'openai', name: 'gpt-4o-mini', mode: 'chat' }
    },
    'http-request': {
        url: '',
        method: 'GET',
        headers: '',
        body: ''
    },
    IMAGE_TASK: {
        promptTemplate: '',
        size: '1024x1024'
    },
    AGENT_TASK: {
        agentGoal: ''
    },
    approval: {
        approverRole: '',
        promptText: ''
    },
    HUMAN_TASK: {
        approverRole: '',
        promptText: ''
    },
    'if-else': {
        defaultNext: '',
        conditions: []
    },
    CONDITION_GATEWAY: {
        defaultNext: '',
        conditions: []
    },
    'question-classifier': {
        classes: [{ id: '1', name: '分类 1' }, { id: '2', name: '分类 2' }],
        query_variable_selector: []
    },
    'custom-note': {
        text: '',
        theme: 'yellow',
        width: 250,
        height: 150,
        showAuthor: false,
        author: ''
    },
    start: {
        triggerType: 'user-input'
    }
}

// 2. 组装工（工厂函数）
export function createNode(payload) {
    const type = payload.type
    const id = payload.id

    // 第一步：搭建基础框架
    const newNode = {
        id: id,
        type: type,
        data: {
            type: type,
            title: id
        }
    }

    // 第二步：查配方表，深拷贝默认数据（防止不同节点互相共享同一个数据对象）
    const defaults = NODE_DEFAULTS[type]
        ? JSON.parse(JSON.stringify(NODE_DEFAULTS[type]))
        : {}

    // 第三步：将配方里的属性合并到 newNode.data 中
    Object.assign(newNode.data, defaults)

    // 第四步：处理一些需要根据用户输入动态变化的“特殊特例”
    if (type === 'SYSTEM_TASK' || type === 'TOOL_TASK' || type === 'tool') {
        newNode.data.toolName = payload.toolName
        newNode.data.tool_name = payload.toolName
        newNode.data.args = {}
        newNode.toolName = payload.toolName
        newNode.args = {}
    } else if (type === 'start') {
        newNode.data.triggerType = payload.triggerType || 'user-input'
        if (newNode.data.triggerType === 'cron') {
            newNode.data.cron = '0 0 * * *'
        }
    } else if (type === 'approval' || type === 'HUMAN_TASK') {
        newNode.data.approverRole = payload.approverRole || 'admin'
        newNode.data.promptText = payload.promptText || '请核对并审批此任务'
        // 兼容性老字段
        newNode.approverRole = newNode.data.approverRole
        newNode.promptText = newNode.data.promptText
    }

    return newNode
}

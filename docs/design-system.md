# Agent Flow Design System

> 设计方向：石墨中性、低饱和靛蓝、清晰克制。  
> 本文只定义配色、字体、组件样式和间距。

## 1. 配色

界面以灰白中性色为主体。靛蓝只用于主要操作、选中、焦点和链接，不使用大面积蓝色背景。

### 基础色

| Token | 色值 | 用途 |
|---|---|---|
| `--gray-0` | `#FFFFFF` | 卡片、弹窗、输入框 |
| `--gray-25` | `#FAFBFC` | 次级面板 |
| `--gray-50` | `#F6F7F9` | 页面背景 |
| `--gray-100` | `#F0F1F3` | Hover、禁用背景 |
| `--gray-200` | `#DFE2E7` | 默认边框、分隔线 |
| `--gray-300` | `#C8CDD4` | 强边框、输入框边框 |
| `--gray-400` | `#9AA1AB` | 占位符、禁用文字 |
| `--gray-500` | `#737B87` | 辅助文字 |
| `--gray-600` | `#505762` | 次级正文 |
| `--gray-700` | `#3A3F47` | 强调正文 |
| `--gray-800` | `#25272C` | 标题、主要正文 |
| `--gray-900` | `#181A1E` | 最高强调文字 |

### 品牌色

| Token | 色值 | 用途 |
|---|---|---|
| `--indigo-50` | `#EEF0F8` | 选中背景、轻提示 |
| `--indigo-100` | `#E2E6F3` | Active 浅背景 |
| `--indigo-200` | `#CBD2EA` | 品牌浅边框 |
| `--indigo-400` | `#7D8DBD` | 次级图标 |
| `--indigo-500` | `#5368A9` | 主按钮、主要选中状态 |
| `--indigo-600` | `#43558D` | Hover、链接文字 |
| `--indigo-700` | `#374673` | Active 状态 |

### 状态色

| 状态 | 浅背景 | 文字/边框 |
|---|---|---|
| 成功 | `#EDF7F2` | `#397D64` |
| 警告 | `#FBF1E7` | `#A66532` |
| 错误 | `#FDF0EF` | `#B5473D` |

状态不能只依赖颜色，需同时使用文字、图标或形态进行区分。

### 项目语义变量

```css
:root {
  --af-page: #f6f7f9;
  --af-surface: #ffffff;
  --af-surface-subtle: #f0f1f3;

  --af-text-primary: #25272c;
  --af-text-secondary: #505762;
  --af-text-muted: #737b87;

  --af-border: #dfe2e7;
  --af-border-strong: #c8cdd4;

  --af-brand: #5368a9;
  --af-brand-strong: #43558d;
  --af-brand-soft: #eef0f8;
  --af-brand-border: #cbd2ea;
  --af-focus-ring: rgb(83 104 169 / 20%);

  --af-success: #397d64;
  --af-warning: #a66532;
  --af-danger: #b5473d;
}
```

业务组件优先使用语义变量，不新增主色硬编码。供应商品牌 Logo、工作流节点类型色属于例外。

## 2. 字体

### 字体栈

```css
:root {
  --font-sans: 'Noto Sans SC', 'Inter', -apple-system,
    BlinkMacSystemFont, 'Segoe UI', sans-serif;

  --font-mono: 'JetBrains Mono', 'Fira Code', ui-monospace,
    SFMono-Regular, Menlo, Consolas, monospace;
}
```

- 中文界面优先使用 `Noto Sans SC`。
- 英文、数字和快捷键使用 `Inter`。
- 代码、变量路径、JSON、DSL 和运行日志使用等宽字体。
- 按钮默认使用 550 字重，主要按钮使用 600；不使用过细的 400 字重。

### 字号层级

| 用途 | 字号 | 字重 | 行高 |
|---|---:|---:|---:|
| 页面标题 | 24px | 650 | 32px |
| 区域标题 | 18–20px | 600 | 28px |
| 面板标题 | 15–16px | 600 | 24px |
| 卡片标题 | 13–14px | 600 | 20px |
| 正文 | 13px | 400 | 20px |
| 控件文字 | 13px | 550 | 18px |
| 标签、节点标题 | 11–12px | 600 | 16px |
| 辅助文字 | 11–12px | 400 | 16–18px |
| 元数据、快捷键 | 9–10px | 500 | 14px |

页面标题可使用 `letter-spacing: -0.025em`。中文正文保持正常字距。

## 3. 组件样式

### 按钮

| 规格 | 高度 | 横向内边距 | 圆角 | 字重 |
|---|---:|---:|---:|---:|
| Small | 28–32px | 10–12px | 6–8px | 550 |
| Default | 36–40px | 14–16px | 8px | 550 |
| Large | 44–48px | 20–24px | 10px | 600 |
| Icon | 与当前规格同高 | 0 | 8px | — |

| 类型 | 背景 | 文字 | 边框 | Hover |
|---|---|---|---|---|
| Primary | `--af-brand` | 白色 | 无或同背景 | `--af-brand-strong` |
| Outline | 白色 | `--af-text-secondary` | `--af-border-strong` | 浅灰背景 |
| Ghost | 透明 | `--af-text-secondary` | 无 | 浅灰背景 |
| Destructive | 错误浅背景或错误色 | 错误深色或白色 | 错误色 | 加深一级 |

- 按下时可使用 `transform: scale(.98)`。
- Disabled 使用 50% 透明度，不响应 Hover。
- Focus 使用 3px `--af-focus-ring`。
- Loading 时按钮宽度不能变化。

### 输入框与选择器

- 默认高度 36–40px，圆角 8px。
- 背景为白色，边框使用 `--af-border-strong`。
- Hover 加深边框；Focus 使用品牌边框和焦点环。
- 内边距为 8px 12px，字号 13px。
- Placeholder 使用 `--gray-400`。
- 错误状态使用错误边框，并显示错误图标和文字。
- 多行输入框保持相同圆角与边框规则，最小内边距 12px。

### 卡片

- 白色背景、1px `--af-border` 边框、12px 圆角。
- 默认阴影：`0 1px 2px rgb(24 30 42 / 4%)`。
- 交互卡片 Hover：品牌浅边框、上移 2px、阴影增强。
- 普通卡片内边距 14–16px；复杂配置卡为 20–24px。
- 卡片标题和描述使用字体层级建立差异，不使用大面积彩色背景。

### 弹窗与抽屉

- 背景为白色，边框使用 `--af-border`，圆角 12px。
- 阴影：`0 18px 45px rgb(24 30 42 / 14%)`。
- 遮罩：`rgb(24 26 30 / 36%)`。
- Header、Content、Footer 使用边框或间距明确分区。
- Header 与 Footer 内边距 16–20px，Content 内边距 20px。
- Footer 中主要操作位于右侧，取消操作使用 Outline 或 Ghost。
- 右侧配置抽屉不使用圆角，使用左边框和向左阴影。

### 标签与状态

- 普通标签：浅灰背景、灰色边框、灰色文字。
- 选中标签：`--af-brand-soft` 背景、`--af-brand-border` 边框、品牌深色文字。
- 普通标签使用 6px 圆角，状态胶囊使用 999px 圆角。
- 标签字号 10–12px，字重 500–600，横向内边距 6–10px。

### 菜单与标签页

- 菜单使用白色背景、12px 圆角、细边框和中等阴影。
- 菜单项高度 32–36px，Hover 使用浅灰背景。
- 标签页默认文字使用次级色；选中状态使用品牌深色和 2px 底边框。
- 胶囊标签页选中时使用品牌浅背景，不使用实心亮蓝色。

### 工作流节点

- 节点宽度基准 240px，白色背景，14–16px 圆角。
- 默认使用细边框和轻阴影；选中使用品牌边框与浅色外环。
- 节点标题 11–12px、600 字重；变量和路径使用等宽字体。
- 节点类型颜色只用于 28px 左右的图标、状态边框或连接锚点，不填满整张节点卡片。

## 4. 间距

采用 4px 基准网格。

### 间距 Token

```css
:root {
  --space-0: 0;
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-7: 28px;
  --space-8: 32px;
  --space-10: 40px;
  --space-12: 48px;
  --space-16: 64px;
}
```

### 使用规则

| 场景 | 间距 |
|---|---:|
| 图标与文字 | 6–8px |
| 同组按钮 | 8px |
| 标签之间 | 4–6px |
| 表单标签与输入框 | 6–8px |
| 同组表单字段 | 12–16px |
| 卡片内部元素 | 8–12px |
| 卡片之间 | 12–16px |
| 面板内部 | 16–20px |
| 页面横向边距 | 32px |
| 页面纵向边距 | 28–32px |
| 页面标题与内容 | 20–24px |
| 大区块之间 | 32–48px |

- 紧凑工具栏允许使用 4px 间距。
- 控件高度和内边距应保持一致，不能通过随意增减 padding 修正对齐。
- 页面内部优先使用 8、12、16、24、32px，避免 13、17、19px 等孤立数值。

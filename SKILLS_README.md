# XiaoSheng AI Skills

本目录包含 XiaoSheng AI 数字员工的专业技能包。这些 Skills 在系统启动时自动加载到数据库，并可在创建数字员工时选择使用。

---

## 目录

- [Skills 列表](#skills-列表)
- [API 需求说明](#api-需求说明)
- [使用方式](#使用方式)
- [开发新的 Skill](#开发新的-skill)

---

## Skills 列表

### 📄 文档生成 Skills

#### xiaosheng-pdf
**功能**: PDF 文档生成、填充和重构

**支持的任务**:
- **CREATE**: 从零生成精美 PDF（报告、提案、简历等）
- **FILL**: 填充现有 PDF 表单字段
- **REFORMAT**: 重新设计现有文档样式

**技术栈**: Python + JavaScript (Puppeteer)
**输出**: 打印级质量 PDF

---

#### xiaosheng-xlsx
**功能**: Excel 电子表格创建、读取和分析

**支持的任务**:
- 创建新的 .xlsx 文件（支持公式、格式化）
- 读取和分析现有电子表格
- 编辑现有文件（零格式丢失）
- 数据透视表、图表、条件格式

**技术栈**: Python (pandas, openpyxl)

---

#### xiaosheng-docx
**功能**: Word 文档专业创建和编辑

**支持的任务**:
- 创建专业文档（从头开始）
- 填充和编辑现有文档内容
- 应用模板格式（XSD 验证）

**技术栈**: .NET (OpenXML SDK)
**特点**: 支持 15 种封面风格，Token 驱动设计系统

---

### 📊 演示文稿 Skills

#### xiaosheng-pptx-generator
**功能**: PowerPoint 演示文稿创建、编辑和读取

**支持的任务**:
- 从零创建 PPT（封面、目录、内容、章节、总结页）
- 基于模板编辑（XML 工作流）
- 读取和分析现有演示文稿

**技术栈**: Node.js (PptxGenJS), Python (markitdown)
**尺寸**: 16:9 (10" × 5.625")
**特点**: 完整设计系统（配色、字体、风格配方）

---

#### xiaosheng-color-font-skill
**功能**: PPT 配色和字体选择

**用途**: 为演示文稿选择专业的配色方案和字体搭配
**触发词**: 配色, 色板, 字体, color palette, font, PPT配色

---

#### xiaosheng-design-style-skill
**功能**: PPT 设计风格选择

**用途**: 选择一致的视觉设计系统（Sharp/Soft/Rounded/Pill 风格配方）
**触发词**: 风格, style, radius, spacing, 圆角, 间距, PPT风格

---

#### xiaosheng-ppt-editing-skill
**功能**: 现有 PPT 模板编辑

**用途**: 分析布局、映射内容到幻灯片、安全复制/重排/删除幻灯片
**工作流**: 解包 → 编辑 XML → 清理孤立资源 → 打包

---

#### xiaosheng-ppt-orchestra-skill
**功能**: 多幻灯片 PPT 编排规划

**用途**: 在生成完整 PPT 前进行规划（分类幻灯片类型、强制视觉多样性、设置排版规则）
**触发**: 在使用 PPTX Generator 前，用于规划整个 Deck

---

#### xiaosheng-slide-making-skill
**功能**: 单个幻灯片实现

**用途**: 编写或修复幻灯片 JS 文件（尺寸、定位、文本/图片/图表 API、样式规则）
**参考**: PptxGenJS API 完整文档

---

### 🎨 多模态 Skills（需要 API）

#### vision-analysis
**功能**: 图像分析和理解

**支持的任务**:
- 描述和分析图像内容
- OCR 文字提取
- UI 原型审查
- 图表数据提取
- 物体检测

**API 需求**: ✅ **MiniMax API Key**
**模型**: MiniMax VL (视觉语言模型)

---

#### minimax-multimodal-toolkit
**功能**: 统一的多模态内容生成

**支持的任务**:
- **TTS**: 文本转语音、语音克隆、语音设计
- **Music**: 歌曲和器乐生成
- **Video**: 文本/图片转视频
- **Image**: 文本/图片生成图片

**API 需求**: ✅ **MiniMax API Key**
**特点**: FFmpeg 媒体处理工具集成

---

#### gif-sticker-maker
**功能**: GIF 表情包生成

**支持的任务**:
- 将照片转换为 4 个动画 GIF 表情
- Funko Pop / Pop Mart 盲盒风格
- 自动添加字幕

**API 需求**: ✅ **MiniMax Image & Video API**
**触发词**: sticker, GIF, cartoon, emoji, 表情包, 动画头像

---

## API 需求说明

### 不需要 API 的 Skills（开箱即用）

这些 Skills 完全本地运行，无需配置任何 API Key：

- ✅ xiaosheng-pdf
- ✅ xiaosheng-xlsx
- ✅ xiaosheng-docx
- ✅ xiaosheng-pptx-generator
- ✅ xiaosheng-color-font-skill
- ✅ xiaosheng-design-style-skill
- ✅ xiaosheng-ppt-editing-skill
- ✅ xiaosheng-ppt-orchestra-skill
- ✅ xiaosheng-slide-making-skill

**依赖**: 这些 Skills 可能需要系统预装 Python、Node.js、.NET SDK 等运行时环境。

---

### 需要 MiniMax API 的 Skills

这些 Skills 需要配置 MiniMax API Key 才能使用：

| Skill | API 用途 | 获取方式 |
|-------|---------|---------|
| vision-analysis | 视觉理解 API | [MiniMax 开放平台](https://www.minimaxi.com/) |
| minimax-multimodal-toolkit | 语音/音乐/视频/图像生成 | 同上 |
| gif-sticker-maker | 图片/视频生成 | 同上 |

**配置方法**:
1. 访问 MiniMax 开放平台注册账号
2. 创建应用并获取 API Key
3. 在系统设置中配置 `MINIMAX_API_KEY` 环境变量

---

## 使用方式

### 数字员工使用 Skills

1. **创建数字员工时**，在 Skills 选择界面勾选需要的 Skills
2. Skills 会自动写入员工的工作空间
3. 员工执行任务时会自动参考相关 Skills 的指导

### API 调用示例

```python
# 通过 API 为数字员工添加 Skill
POST /api/agents/{agent_id}/skills
{
  "skill_ids": ["skill-uuid-1", "skill-uuid-2"]
}
```

---

## 开发新的 Skill

### Skill 目录结构

```
.agents/skills/your-skill-name/
├── SKILL.md              # 必需：主文档（YAML frontmatter + Markdown）
├── README.md             # 可选：详细说明
├── scripts/              # 可选：Python/Shell/JS 脚本
│   ├── helper.py
│   └── process.sh
└── references/           # 可选：参考文档
    └── api-reference.md
```

### SKILL.md 格式

```markdown
---
name: your-skill-name
description: 简短描述（用于 Skill 列表显示）
license: MIT
metadata:
  version: "1.0"
  category: productivity
  author: Your Name
---

# Your Skill Name

## Overview
详细说明何时使用这个 Skill。

## Process
### Step 1: ...
### Step 2: ...

## Examples
使用示例...
```

### 添加新 Skill

1. 在 `.agents/skills/` 创建新的 Skill 目录
2. 编写 `SKILL.md` 和相关文件
3. 重启后端服务，Skills 会自动加载到数据库

---

## 许可证

本目录下的 Skills 来源于 [MiniMax Skills](https://github.com/MiniMax-AI/skills) 项目，遵循 MIT 许可证。

- 已改名的 Skills (xiaosheng-*): 基于 MiniMax Skills 修改
- 保持原名的 Skills (vision-analysis, minimax-multimodal-toolkit, gif-sticker-maker): 保持原始许可
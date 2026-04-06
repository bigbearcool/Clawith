# 前端实施指南 - 语音消息功能

## 一、Agent 设置页面修改

### 1.1 找到文件
- 文件: `frontend/src/pages/AgentDetail.tsx` 或 `AgentSettings.tsx`

### 1.2 添加语音设置区域

```tsx
{/* Voice Settings */}
<div className="setting-section">
  <h3>🔊 语音设置</h3>
  
  {/* Enable Voice */}
  <div className="form-group">
    <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
      <input 
        type="checkbox" 
        checked={agent.voice_enabled || false} 
        onChange={e => setAgent({ ...agent, voice_enabled: e.target.checked })} 
      />
      启用语音回复
      <span style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
        用户发语音时，Agent 会用语音回复
      </span>
    </label>
  </div>
  
  {agent.voice_enabled && (
    <>
      {/* Voice Selection */}
      <div className="form-group">
        <label className="form-label">音色选择</label>
        <div style={{ display: 'flex', gap: '8px' }}>
          <select 
            className="form-input" 
            value={agent.voice_type || '101001'} 
            onChange={e => setAgent({ ...agent, voice_type: e.target.value })}
            style={{ flex: 1 }}
          >
            <optgroup label="精品音色（推荐）">
              <option value="101001">智瑜 - 情感女声</option>
              <option value="101004">智云 - 通用男声</option>
              <option value="101026">智希 - 通用女声</option>
              <option value="101030">智柯 - 通用男声</option>
            </optgroup>
            <optgroup label="大模型音色">
              <option value="501004">月华 - 聊天女声</option>
              <option value="501005">飞镜 - 聊天男声</option>
            </optgroup>
            <optgroup label="超自然大模型音色">
              <option value="502001">智小柔 - 聊天女声</option>
              <option value="502006">智小悟 - 聊天男声</option>
            </optgroup>
          </select>
        </div>
        
        {/* Custom Voice ID */}
        <div style={{ marginTop: '8px', fontSize: '12px', color: 'var(--text-secondary)' }}>
          <details>
            <summary>自定义音色 ID</summary>
            <input 
              type="text" 
              className="form-input" 
              placeholder="输入腾讯云音色 ID（如：101001）"
              value={agent.voice_type || ''}
              onChange={e => setAgent({ ...agent, voice_type: e.target.value })}
              style={{ marginTop: '8px' }}
            />
            <div style={{ marginTop: '4px', fontSize: '11px', color: 'var(--text-tertiary)' }}>
              可在腾讯云音色列表查看更多音色 ID
              <a href="https://cloud.tencent.com/document/product/1073/92668" target="_blank" style={{ marginLeft: '4px' }}>
                查看音色列表
              </a>
            </div>
          </details>
        </div>
      </div>
      
      {/* Speed Slider */}
      <div className="form-group">
        <label className="form-label">
          语速: {getSpeedLabel(agent.voice_speed || 0)}
        </label>
        <input 
          type="range" 
          min="-2" 
          max="6" 
          step="0.5" 
          value={agent.voice_speed || 0} 
          onChange={e => setAgent({ ...agent, voice_speed: parseFloat(e.target.value) })}
          style={{ width: '100%' }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-tertiary)' }}>
          <span>0.6x</span>
          <span>1.0x</span>
          <span>2.5x</span>
        </div>
      </div>
      
      {/* Volume Slider */}
      <div className="form-group">
        <label className="form-label">
          音量: {getVolumeLabel(agent.voice_volume || 0)}
        </label>
        <input 
          type="range" 
          min="-10" 
          max="10" 
          step="1" 
          value={agent.voice_volume || 0} 
          onChange={e => setAgent({ ...agent, voice_volume: parseFloat(e.target.value) })}
          style={{ width: '100%' }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-tertiary)' }}>
          <span>最小</span>
          <span>正常</span>
          <span>最大</span>
        </div>
      </div>
    </>
  )}
</div>

{/* Helper Functions */}
<script>
function getSpeedLabel(speed: number): string {
  if (speed <= -2) return '0.6x';
  if (speed <= -1) return '0.8x';
  if (speed === 0) return '1.0x（正常）';
  if (speed <= 1) return '1.2x';
  if (speed <= 2) return '1.5x';
  return '2.5x';
}

function getVolumeLabel(volume: number): string {
  if (volume <= -10) return '最小';
  if (volume < 0) return '较小';
  if (volume === 0) return '正常';
  if (volume < 10) return '较大';
  return '最大';
}
</script>
```

---

## 二、模型池管理页面修改

### 2.1 找到文件
- 文件: `frontend/src/pages/EnterpriseSettings.tsx`

### 2.2 修改模型表单

找到 `modelForm` 状态定义，添加腾讯云字段：

```tsx
const [modelForm, setModelForm] = useState({
  provider: 'anthropic',
  model: '',
  api_key: '',
  base_url: '',
  label: '',
  supports_vision: false,
  streaming_tool_calls_unreliable: false,
  // Add Tencent Voice
  tencent_secret_id: '',
  tencent_secret_key: '',
  max_output_tokens: '' as string,
  request_timeout: '' as string,
  temperature: '' as string,
});
```

### 2.3 添加 UI 组件

在模型编辑表单中添加：

```tsx
{/* Tencent Cloud Voice Settings */}
<div className="form-group" style={{ gridColumn: 'span 2' }}>
  <h4 style={{ marginBottom: '8px', marginTop: '16px' }}>腾讯云语音设置（可选）</h4>
</div>

<div className="form-group">
  <label className="form-label">Tencent SecretId</label>
  <input 
    className="form-input" 
    type="password"
    placeholder="腾讯云 SecretId（用于语音功能）" 
    value={modelForm.tencent_secret_id} 
    onChange={e => setModelForm({ ...modelForm, tencent_secret_id: e.target.value })} 
  />
  <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
    用于语音识别（ASR）和语音合成（TTS）
  </div>
</div>

<div className="form-group">
  <label className="form-label">Tencent SecretKey</label>
  <input 
    className="form-input" 
    type="password"
    placeholder="腾讯云 SecretKey" 
    value={modelForm.tencent_secret_key} 
    onChange={e => setModelForm({ ...modelForm, tencent_secret_key: e.target.value })} 
  />
</div>
```

### 2.4 更新模型列表显示

在模型列表中添加腾讯云密钥状态显示：

```tsx
{m.tencent_secret_id_masked && (
  <span className="badge" style={{ background: 'rgba(34,197,94,0.15)', color: 'rgb(34,197,94)', fontSize: '10px' }}>
    语音已配置
  </span>
)}
```

### 2.5 更新保存逻辑

确保在保存模型时包含腾讯云字段：

```tsx
const data = {
  ...modelForm,
  max_output_tokens: modelForm.max_output_tokens ? Number(modelForm.max_output_tokens) : null,
  request_timeout: modelForm.request_timeout ? Number(modelForm.request_timeout) : null,
  temperature: modelForm.temperature !== '' ? Number(modelForm.temperature) : null,
  // Include Tencent fields (only if not masked)
  tencent_secret_id: modelForm.tencent_secret_id && !modelForm.tencent_secret_id.startsWith('****') 
    ? modelForm.tencent_secret_id 
    : undefined,
  tencent_secret_key: modelForm.tencent_secret_key && !modelForm.tencent_secret_key.startsWith('****')
    ? modelForm.tencent_secret_key
    : undefined,
};
```

---

## 三、类型定义更新

### 3.1 更新 Agent 类型

```typescript
interface Agent {
  // ... existing fields
  voice_enabled: boolean;
  voice_type: string | null;
  voice_speed: number;
  voice_volume: number;
}
```

### 3.2 更新 LLMModel 类型

```typescript
interface LLMModel {
  // ... existing fields
  tencent_secret_id_masked: string;
}
```

---

## 四、API 调用示例

### 4.1 更新 Agent 语音配置

```typescript
const updateAgentVoice = async (agentId: string, voiceConfig: {
  voice_enabled: boolean;
  voice_type: string;
  voice_speed: number;
  voice_volume: number;
}) => {
  const response = await fetch(`/api/agents/${agentId}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${localStorage.getItem('token')}`
    },
    body: JSON.stringify(voiceConfig)
  });
  return response.json();
};
```

### 4.2 更新模型腾讯云配置

```typescript
const updateModelTencent = async (modelId: string, config: {
  tencent_secret_id: string;
  tencent_secret_key: string;
}) => {
  const response = await fetch(`/api/enterprise/llm-models/${modelId}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${localStorage.getItem('token')}`
    },
    body: JSON.stringify(config)
  });
  return response.json();
};
```

---

## 五、实施步骤

1. **修改 Agent 设置页面**
   - 添加语音设置区域
   - 添加音色选择器
   - 添加语速和音量滑块

2. **修改模型池管理页面**
   - 添加腾讯云密钥输入框
   - 更新保存逻辑
   - 添加密钥状态显示

3. **更新类型定义**
   - Agent 接口添加语音字段
   - LLMModel 接口添加腾讯云字段

4. **测试**
   - 配置腾讯云密钥
   - 启用 Agent 语音功能
   - 在飞书发送语音消息测试

---

## 六、预估工作量

- Agent 设置页面：1 小时
- 模型池管理页面：0.5 小时
- 类型定义更新：0.5 小时
- 测试验证：0.5 小时

**总计：约 2.5 小时**

---

## 七、注意事项

1. **密钥安全**：
   - 前端显示时必须脱敏（****xxxx）
   - 不要在控制台打印密钥

2. **用户体验**：
   - 滑块要显示当前值标签
   - 音色选择器要分组显示
   - 提供自定义音色 ID 输入

3. **错误处理**：
   - 语音功能失败时降级为文字回复
   - 提示用户检查腾讯云配置

---

**完成前端后，整个语音消息功能就完全可用了！**
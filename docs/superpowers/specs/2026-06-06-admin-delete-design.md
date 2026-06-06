# Admin 删除功能设计

**日期**: 2026-06-06
**范围**: 模型管理、供应商管理、渠道管理 — 增加删除功能

## 概述

为三个管理页面（模型、供应商、渠道）增加删除功能。由于 `RequestLog` 通过外键引用这三张表，采用混合删除策略：无法硬删除时自动降级为软删除。存在子记录（如模型下的渠道配置）时阻止删除。

## 设计决策

| 决策 | 选择 | 说明 |
|------|------|------|
| 删除语义 | 混合模式 | 无 RequestLog 引用 → 硬删除；有引用 → 软删除（status = "deleted"） |
| 关联数据处理 | 阻止删除 | 存在子记录（ChannelConfig、Model、ProviderKey 等）时返回 409 |
| 确认方式 | 简单确认弹窗 | 显示影响范围，确认/取消 |

## 数据库

无需迁移。三张表的 `status` 字段已是 `String(20)`，在现有 `active` / `inactive` 基础上新增 `deleted` 值。

| 表 | status 新增值 | 含义 |
|----|-------------|------|
| `models` | `deleted` | 模型已删除，不再展示 |
| `providers` | `deleted` | 供应商已删除，不再展示 |
| `channel_configs` | `deleted` | 渠道已删除，不再展示 |

> 注：现有的列表查询不过滤 status，建议后续统一加上 `status != 'deleted'` 过滤。本次设计在服务层返回的列表函数中追加该条件。

## 后端

### 服务层 — 删除函数

三个新函数，分别位于对应服务文件：

| 函数 | 文件 |
|------|------|
| `delete_model(db, model_id)` | `backend/app/services/model_service.py` |
| `delete_provider(db, provider_id)` | `backend/app/services/provider_service.py` |
| `delete_channel(db, channel_id)` | `backend/app/services/provider_service.py` |

#### 统一执行流程

```
1. 查找实体
   ├─ 不存在 → 404 (MODEL_NOT_FOUND / PROVIDER_NOT_FOUND / CHANNEL_NOT_FOUND)
   ├─ status 已是 "deleted" → 404（已删除的视为不存在）
   └─ 存在 → 继续

2. 检查子记录阻塞
   ├─ Model:    检查 ChannelConfig 中是否有引用该 model_id
   ├─ Provider: 检查 Model + ChannelConfig + ProviderKey(active) 中是否有引用该 provider_id
   ├─ Channel:  检查 ChannelKey 中是否有引用该 channel_id
   ├─ 有阻塞 → 409 HAS_DEPENDENTS + blocking 明细
   └─ 无阻塞 → 继续

3. 判断删除方式
   ├─ 查询 RequestLog 中是否引用该实体 ID
   ├─ 无引用 → 硬删除 (db.delete)
   └─ 有引用 → 软删除 (status = "deleted")

4. 附加工
   ├─ Provider 硬删除 → ProviderKey 级联删除（FK 约束，阻塞检查已确保无 active key）
   ├─ Channel 软删除 → 清除 is_default 标志
   ├─ Channel 硬删除 → ChannelKey 级联删除（FK 约束）
   └─ Model → 无需附加工（ChannelConfig 已在步骤 2 被阻止，需用户先手动清理）

5. 返回 {"deleted": true, "method": "hard"|"soft", "id": <id>}
```

#### 列表查询过滤

现有 `list_all_models`、`list_providers`、`list_channel_configs` 的查询条件追加 `.where(status != "deleted")`，确保已删除项不在管理列表中展示。

### 路由层 — DELETE 端点

| 方法 | 路由 | 文件 |
|------|------|------|
| `DELETE` | `/api/admin/models/{model_id}` | `backend/app/routers/admin_models.py` |
| `DELETE` | `/api/admin/providers/{provider_id}` | `backend/app/routers/admin_providers.py` |
| `DELETE` | `/api/admin/channels/{channel_id}` | `backend/app/routers/admin_channels.py` |

- 全部需要 `get_current_admin` 依赖
- 调用服务函数后 `await db.commit()`

#### 响应 Schema

**成功 (200)**:
```json
{
  "deleted": true,
  "method": "hard",
  "id": 1
}
```

**阻塞 (409)**:
```json
{
  "error": "无法删除：供应商下有 2 个模型、1 个渠道配置",
  "code": "HAS_DEPENDENTS",
  "blocking": {
    "models": 2,
    "channels": 1,
    "keys": 0
  }
}
```

**不存在 (404)**:
```json
{
  "error": "模型不存在",
  "code": "MODEL_NOT_FOUND"
}
```

新增 Pydantic schema（追加到现有 admin schema 文件中或新建 `app/schemas/delete.py`）:

```python
class DeleteResponse(BaseModel):
    deleted: bool
    method: str
    id: int
```

## 前端

### API 层 — useDelete hooks

三个新 hook，分别追加到对应 API 文件中：

| Hook | 文件 |
|------|------|
| `useDeleteModel` | `frontend/lib/api/admin/models.ts` |
| `useDeleteProvider` | `frontend/lib/api/admin/providers.ts` |
| `useDeleteChannel` | `frontend/lib/api/admin/channels.ts` |

通用结构：

```typescript
export interface DeleteResult {
  deleted: boolean;
  method: "hard" | "soft";
  id: number;
}

export function useDeleteModel() {
  const queryClient = useQueryClient();
  return useMutation<DeleteResult, ApiClientError, number>({
    mutationFn: (id) =>
      apiClient<DeleteResult>(`/admin/models/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "models"] });
      queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}
```

三个 hook 模式完全一致。

### UI — 删除按钮 & 确认弹窗

#### 按钮

每行操作列末尾加红色删除按钮（Trash2 图标），与编辑/启停按钮同级。

- `frontend/app/admin/models/page.tsx` — 操作列新增
- `frontend/app/admin/providers/page.tsx` — ProviderRow 操作列新增
- `frontend/app/admin/channels/page.tsx` — 操作列新增

#### 确认弹窗

复用现有 `Dialog` 组件。弹窗内容根据后端返回动态展示：

**正常确认状态**：
- 标题："删除{模型/供应商/渠道}"
- 描述："确定要删除 **{名称}** 吗？"
- 警告："删除后将无法通过该{实体}发起 API 请求。"

**409 阻塞状态**（不关闭弹窗）：
- 错误提示：具体阻塞项列表
- 操作建议："请先删除关联项后再试"
- 确认按钮禁用

**处理流程**：
1. 点击删除 → 打开确认弹窗
2. 确认 → 调用 mutation
3. 成功 → 关闭弹窗，列表自动刷新
4. 409 → 弹窗内展示阻塞详情
5. 其他错误 → 弹窗内展示错误信息

### 公共模型列表过滤

`ModelCard` 和公开模型列表接口应过滤掉 `status = "deleted"` 的模型，确保用户端不可见已删除项。

## 边界情况 & 错误处理

| 场景 | 处理 |
|------|------|
| 重复删除已删除的实体 | 返回 404 |
| 删除不存在的实体 | 返回 404 |
| 有子记录阻止删除 | 返回 409 + 阻塞明细 |
| Provider 软删除时 active Key 的处理 | 全部自动 revoke |
| Channel 删除时 is_default 处理 | 清除 default 标志 |
| 正在处理请求时删除 | 软删除不影响进行中的请求；硬删除无引用时不会发生 |
| 并发删除 | 数据库行锁 + 唯一约束保证安全 |

## 测试要点

### 后端测试

- `test_delete_model_success_hard` — 无 RequestLog 引用时硬删除
- `test_delete_model_success_soft` — 有 RequestLog 引用时软删除
- `test_delete_model_blocked_by_channels` — 有 ChannelConfig 引用时返回 409
- `test_delete_model_not_found` — 不存在返回 404
- `test_delete_model_already_deleted` — 重复删除返回 404
- `test_delete_provider_success_hard` — 无引用时硬删除
- `test_delete_provider_success_soft` — 有引用时软删除 + key 自动 revoke
- `test_delete_provider_blocked_by_models` — 有子 model 时 409
- `test_delete_channel_success` — 渠道删除
- `test_delete_channel_blocked_by_channel_keys` — 有 channel_key 时 409

### 前端测试

- 删除按钮渲染
- 确认弹窗交互
- 409 阻塞提示展示
- 成功后列表刷新

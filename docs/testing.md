# Testing

## Backend Tests

### 运行
```bash
cd backend
uv run pytest                    # 全部测试
uv run pytest -v                 # 详细输出
uv run pytest tests/test_app_startup.py::test_health_check  # 单个测试
```

### 测试基础设施
- **框架**: pytest + pytest-asyncio (`asyncio_mode = "auto"`)
- **HTTP 客户端**: httpx.AsyncClient + ASGITransport (无需启动服务器)
- **数据库**: SQLite 内存 (`sqlite+aiosqlite:///:memory:`)
- **位置**: `backend/tests/`

### 当前测试: `test_app_startup.py`
```python
# 在导入前设置 DATABASE_URL
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server import app

@pytest.mark.asyncio
async def test_health_check():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

@pytest.mark.asyncio
async def test_anthropic_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}
```

### 编写后端测试的模式
```python
import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
# 也可以覆盖其他 env
# os.environ["JWT_PRIVATE_KEY"] = "<base64 PEM>"  # RS256；与 JWT_PUBLIC_KEY 配对

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from httpx import ASGITransport, AsyncClient
from server import app

@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

@pytest.mark.asyncio
async def test_something(client):
    response = await client.post("/api/auth/register", json={
        "email": "test@example.com",
        "password": "password123"
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data  # 或其他断言
```

### ⚠️ backend-old 中的测试
`backend-old/tests/` 有 18 个测试文件覆盖完整业务逻辑，可作为新测试的参考:
- `test_auth.py` — 注册、登录、鉴权
- `test_api_keys.py` — Key 创建、列表、吊销
- `test_billing.py` — 计费计算
- `test_proxy_billing.py` — 代理请求计费全链路
- `test_models.py` — 模型列表
- `test_payment.py` — 支付流程
- `test_redemption.py` — 兑换码
- `test_admin_channels.py`, `test_admin_providers.py` — Admin CRUD
- `test_usage.py` — 用量查询

## Frontend Tests

### 运行
```bash
cd frontend
npm test                    # vitest run (一次)
npm run test:watch          # vitest (监听模式)
```

### 测试基础设施
- **框架**: Vitest + React Testing Library + @testing-library/user-event
- **环境**: jsdom (浏览器模拟)
- **Setup**: `tests/setup.ts` → 导入 `@testing-library/jest-dom` 匹配器
- **配置**: `vitest.config.ts` 含 `globals: true`, `@vitejs/plugin-react`
- **位置**: `frontend/tests/`

### 当前测试文件 (9个)

| 文件 | 测试内容 |
|------|----------|
| `components/LoginForm.test.tsx` | 表单渲染、验证错误 |
| `components/RegisterForm.test.tsx` | 表单渲染、密码验证、邮箱验证 |
| `components/ForgotPasswordForm.test.tsx` | 表单渲染、提交 |
| `components/CreateKeyForm.test.tsx` | 表单渲染、成功创建显示 raw key |
| `components/KeyList.test.tsx` | Loading/空/key 列表状态 |
| `components/ModelCard.test.tsx` | 模型卡片渲染、channel 切换 |
| `components/ChangePasswordForm.test.tsx` | 表单渲染、提交 |
| `lib/AuthContext.test.tsx` | AuthContext 状态转换 |
| `lib/Usage.test.tsx` | useUsageStats/useUsageHistory hooks |

### 编写前端测试的模式

```tsx
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, it, expect, vi } from "vitest"

// Mock Next.js router
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

describe("MyComponent", () => {
  it("renders correctly", async () => {
    // Mock fetch
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ data: "test" }),
    })

    render(<MyComponent />, { wrapper: createWrapper() })

    await waitFor(() => {
      expect(screen.getByText("test")).toBeInTheDocument()
    })
  })

  it("handles user interaction", async () => {
    const user = userEvent.setup()
    render(<MyForm />, { wrapper: createWrapper() })

    await user.type(screen.getByLabelText("邮箱"), "test@example.com")
    await user.click(screen.getByRole("button", { name: "提交" }))

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalled()
    })
  })
})
```

### Mock 策略
- **next/navigation**: `vi.mock("next/navigation", ...)` — mock useRouter, useSearchParams
- **next/link**: `vi.mock("next/link", ...)` — 替换为普通 `<a>` 标签
- **global.fetch**: 直接 mock (用于组件测试)
- **lib/api/client**: `vi.mock` 模块级别 mock (用于 hook 测试)
- **QueryClient**: 每个测试新建，`retry: false` 避免重试延迟

## 常见开发场景

### 为新功能编写后端测试
1. 参考 `backend-old/tests/` 中同类型测试
2. 在 `backend/tests/` 创建新文件 (如 `test_billing.py`)
3. 使用 SQLite 内存 DB，通过 env 覆盖配置
4. 使用 `httpx.ASGITransport` 直接测试 ASGI app

### 为新组件编写前端测试
1. 在 `frontend/tests/components/` 创建新文件
2. 参考已有测试的 mock 模式
3. 测试: 渲染 → 交互 → 验证 API 调用/UI 变化
4. 使用 `createWrapper()` 提供 QueryClient + AuthContext

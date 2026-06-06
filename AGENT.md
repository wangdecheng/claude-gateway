# AGENT.md

## 进入项目先做什么

1. 先读取 `CLAUDE.md`，它是本仓库的总览和路由表。
2. 根据任务场景读取对应文档，不要只凭文件名猜实现：
   - 代理/计费：`docs/backend-proxy.md`
   - 认证/权限：`docs/backend-auth.md`
   - Provider/渠道/限流：`docs/backend-providers.md`
   - 数据库/迁移/种子：`docs/backend-database.md`
   - 前端页面/组件/Admin：`docs/frontend.md`
   - 测试：`docs/testing.md`
   - 整体架构：`docs/architecture.md`
3. 再读取任务相关入口文件，保持改动范围最小。

## 项目定位

`high-api` 是一个 Anthropic Messages API 兼容网关，向上游 Provider 转发请求，并包含用户认证、API Key、余额计费、兑换码、支付记录、Admin 模型/Provider/渠道管理。

- Backend：Python 3.14、FastAPI、SQLAlchemy async、PostgreSQL
- Frontend：Next.js 15 App Router、React 19、TanStack Query、Tailwind CSS 4
- 包管理：后端 `uv`，前端 `npm`

## 核心约束

- `backend-old/` 只是历史参考，不是当前活跃代码。
- 不要回滚或覆盖用户已有改动。动手前用 `git status --short` 确认工作区状态。
- 不做无关重构，不改无关格式，不引入新的架构风格。
- 遇到失败先找根因，再决定修复；不要用表面补丁掩盖问题。
- 后端价格单位、余额单位、计费幂等、请求日志和结算流程都属于高风险逻辑，改动后必须补充或运行相关测试。
- 前端请求默认通过 `lib/api/client.ts`，并依赖 cookie 凭证；不要随意绕过已有 API 封装。

## 常用入口

### Backend

- 应用工厂：`backend/api/app.py`
- 启动入口：`backend/server.py`
- 代理计费：`backend/app/routers/proxy.py`
- 计费服务：`backend/app/services/billing_service.py`
- 认证依赖：`backend/app/dependencies.py`
- Provider 抽象：`backend/providers/base.py`
- Provider 注册：`backend/providers/registry.py`
- 模型路由：`backend/api/model_router.py`
- 数据模型：`backend/app/models/`
- Alembic：`backend/alembic/`

### Frontend

- 根布局：`frontend/app/layout.tsx`
- 中间件：`frontend/middleware.ts`
- API Client：`frontend/lib/api/client.ts`
- Auth 状态：`frontend/lib/auth/AuthContext.tsx`
- 用户页面：`frontend/app/(user)/`
- 登录注册页面：`frontend/app/(auth)/`
- Admin 页面：`frontend/app/admin/`
- UI 组件：`frontend/components/`

## 常用命令

### Backend

```bash
cd backend
uv sync
uv run uvicorn server:app --host 0.0.0.0 --port 8082 --reload
uv run pytest
uv run pytest tests/file.py::test_name -v
uv run ruff check .
uv run ruff format .
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "desc"
uv run python -m app.seed
```

后端测试默认使用 SQLite in-memory，不需要 PostgreSQL。

### Frontend

```bash
cd frontend
npm install
npm run dev
npm run build
npm test
npm run lint
```

## 开发判断标准

- 改代理链路时，确认 API Key 校验、模型解析、Provider key 选择、余额预扣、SSE 转发、最终结算、日志记录的完整路径。
- 改认证时，同时确认后端 cookie/JWT 逻辑和前端 middleware/admin gating。
- 改数据库时，确认 SQLAlchemy model、迁移、种子数据、唯一约束、幂等性。
- 改 Provider 时，保持 `base.py` 抽象、`registry.py` 注册、速率限制和错误映射一致。
- 改 Admin CRUD 时，前后端契约要一起检查。
- 改 UI 时，遵循现有组件和 Tailwind 风格，不做营销页式布局。

## 验证要求

根据改动范围选择最小但有效的验证：

- 后端逻辑：`cd backend && uv run pytest`
- 后端静态检查：`cd backend && uv run ruff check .`
- 前端逻辑：`cd frontend && npm test`
- 前端构建/类型：`cd frontend && npm run build`
- 前端 lint：`cd frontend && npm run lint`

如果因为缺少依赖、服务或权限无法验证，要在最终回复里明确说明。

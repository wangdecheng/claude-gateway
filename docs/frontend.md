# Frontend Architecture

## 涉及文件

| 职责 | 文件 |
|------|------|
| Next.js 配置 | `frontend/next.config.ts` |
| 路由中间件 | `frontend/middleware.ts` |
| 根布局 | `frontend/app/layout.tsx` |
| 全局样式 | `frontend/app/globals.css` |
| Provider 包装 | `frontend/components/Providers.tsx` |
| API 客户端 | `frontend/lib/api/client.ts` |
| Auth 上下文 | `frontend/lib/auth/AuthContext.tsx` |
| UI 基础组件 | `frontend/components/ui/*.tsx` |
| 表单组件 | `frontend/components/forms/*.tsx` |
| 数据展示组件 | `frontend/components/data/*.tsx` |

## 路由结构

### App Router 路由组

```
app/
├── layout.tsx                    # 根布局
├── globals.css                   # CSS 自定义属性
│
├── (auth)/                       # 公开页面组 (无导航栏)
│   ├── login/page.tsx            # 登录
│   ├── register/page.tsx         # 注册
│   ├── forgot-password/page.tsx  # 忘记密码
│   └── reset-password/page.tsx   # 重置密码 (Suspense)
│
├── (user)/                       # 用户页面组 (顶部导航栏)
│   ├── layout.tsx                # Nav bar + BalanceDisplay + logout
│   ├── page.tsx                  # 仪表盘 (统计卡片)
│   ├── models/
│   │   ├── page.tsx              # 模型列表 (ModelCard 网格)
│   │   └── [id]/page.tsx         # 模型详情 (channel 表格)
│   ├── keys/page.tsx             # API Key 管理
│   ├── usage/page.tsx            # 用量统计 + 历史
│   ├── recharge/page.tsx         # 充值
│   ├── redeem/page.tsx           # 兑换码
│   └── settings/page.tsx         # 修改密码
│
└── admin/                        # 管理员页面组 (侧边栏)
    ├── layout.tsx                # 侧边栏 + 角色检查
    ├── models/page.tsx           # 模型 CRUD (TanStack Table)
    ├── channels/page.tsx         # 渠道 CRUD
    └── providers/page.tsx        # Provider + Key Pool 管理
```

## 认证流程

### Layer 1: Middleware (`middleware.ts`)
```
每个请求 → 匹配路由 pattern → 读取 high_api_session cookie
  → jose.decodeJwt(token)  // 客户端验证
  → 公开路径 + 已登录 → 重定向到 /
  → 受保护路径 + 未登录 → 重定向到 /login
  → Admin 路径 + 非 admin → 重定向到 /
  → 注入 X-User-ID, X-User-Role headers
```

### Layer 2: AuthContext (`lib/auth/AuthContext.tsx`)
```
<AuthProvider>
  onMount → GET /api/auth/me → { user_id, email, balance, role }
  状态: { user, isLoading, isAuthenticated, refetch, logout }
  - isLoading=true: 显示 loading
  - user=null: 未登录状态 (不主动跳转，由 middleware 处理)
  - 401: 清除 user (网络错误保留当前状态)
  - logout(): POST /auth/logout → 清除 user + TanStack cache
```

### Layer 3: API calls
```
fetch(url, { credentials: "include" })
  → 自动附加 high_api_session cookie
  → Next.js rewrite → backend
  → 后端验证 cookie → 返回数据
```

## 组件模式

### 标准页面模式
```tsx
// "use client" 页面
export default function SomePage() {
  return (
    <div className="container mx-auto px-4 py-8">
      <h1>页面标题</h1>
      <SomeDataComponent />
    </div>
  )
}
```

### API Hook 模式 (TanStack Query)
```tsx
// lib/api/something.ts
export function useSomething() {
  return useQuery({
    queryKey: ["something"],
    queryFn: () => apiClient<SomethingType>("/something"),
    staleTime: 30_000,
  })
}

export function useDoSomething() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: InputType) =>
      apiClient<OutputType>("/something", { method: "POST", body: data }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["something"] })
    },
  })
}
```

### 表单模式 (react-hook-form + zod)
```tsx
const schema = z.object({
  email: z.string().email("请输入有效的邮箱"),
  password: z.string().min(1, "请输入密码"),
})

type FormData = z.infer<typeof schema>

function MyForm() {
  const { register, handleSubmit, formState: { errors } } = useForm<FormData>({
    resolver: zodResolver(schema),
  })
  const mutation = useSomeMutation()

  return (
    <form onSubmit={handleSubmit(data => mutation.mutate(data))}>
      <Input {...register("email")} error={errors.email?.message} />
      <Button type="submit" loading={mutation.isPending}>提交</Button>
    </form>
  )
}
```

### 错误处理模式
```tsx
const mutation = useMutation({
  mutationFn: doSomething,
  onError: (error) => {
    if (error instanceof ApiClientError) {
      // error.code → 针对特定错误码处理
      // error.message → 用户可见错误信息
    }
  },
})
```

### 条件渲染模式
```tsx
if (isLoading) return <LoadingSpinner />
if (error) return <ErrorMessage error={error} />
if (!data || data.length === 0) return <EmptyState />
return <DataView data={data} />
```

## API Client

### apiClient<T>(path, options)
```typescript
// 所有 API 调用的统一入口
const data = await apiClient<UserResponse>("/auth/me")
// → fetch("/api/auth/me", { credentials: "include" })
// → Next.js rewrite → http://localhost:8082/api/auth/me
```

- `API_BASE = "/api"` 自动前缀
- `credentials: "include"` 自动发送 cookie
- 非 OK 响应 → 解析 JSON error body → 抛出 `ApiClientError`
- `ApiClientError` 包含 `code`, `status`, `message` 字段

### 代理配置 (`next.config.ts`)
```typescript
rewrites: () => [{
  source: "/api/:path*",
  destination: "http://localhost:8082/api/:path*"
}]
```

## UI 组件库

基于 shadcn/ui + Radix UI + Tailwind CSS 4:

| 组件 | 用途 |
|------|------|
| `Button` | 按钮 (primary/secondary/ghost/destructive + sizes) |
| `Input` | 输入框 (带 error 状态) |
| `Card` | 卡片容器 (CardHeader/CardTitle/CardContent) |
| `Dialog` | 模态框 (Radix Dialog) |
| `Select` | 下拉选择 (Radix Select) |
| `Table` | 数据表格 |
| `Badge` | 状态标签 (success/error/warning/muted) |
| `Label` | 表单标签 |
| `Textarea` | 多行输入 |

## 样式系统

### CSS 自定义属性 (`globals.css`)
```css
:root {
  --color-primary-base: #6366f1;      /* Indigo */
  --color-primary-light: #818cf8;
  --color-neutral-bg: #fafafa;
  --color-neutral-surface: #ffffff;
  --color-neutral-border: #e5e7eb;
  --color-neutral-text-primary: #111827;
  /* ... */
  --radius-md: 0.375rem;
  --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1);
}
```

### Tailwind 4 配置 (`tailwind.config.ts`)
使用 `@theme` 内联变量。color palette 按 primary/neutral/semantic 分组。

### cn() 工具 (`lib/utils/cn.ts`)
```typescript
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
```
所有组件使用 `cn()` 合并类名，支持条件类和 tailwind 冲突合并。

## 常见开发场景

### 新增页面
1. `app/(user)/new-page/page.tsx` → 创建页面组件
2. 需要数据 → `lib/api/xxx.ts` → TanStack Query hooks
3. 需要表单 → `components/forms/XxxForm.tsx` → react-hook-form + zod
4. 需要导航入口 → `app/(user)/layout.tsx` → nav links

### 新增 Admin 功能
1. `app/admin/new-feature/page.tsx`
2. `lib/api/admin/new-feature.ts` → hooks
3. `app/admin/layout.tsx` → sidebar links

### 新增表单
1. `components/forms/XxxForm.tsx`
2. zod schema 定义验证规则
3. 使用 `useMutation` 提交
4. `onSuccess` 中 invalidateQueries 刷新关联数据

### 修改认证逻辑
1. `middleware.ts` → 路由守卫
2. `lib/auth/AuthContext.tsx` → 用户状态
3. `lib/api/auth.ts` → auth hooks

### API 代理端口变更
修改 `frontend/next.config.ts`:
```typescript
destination: "http://localhost:<新端口>/api/:path*"
```

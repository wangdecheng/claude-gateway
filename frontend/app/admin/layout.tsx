"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth/AuthContext";
import { cn } from "@/lib/utils/cn";
import {
  Box,
  Server,
  Sliders,
  Users,
  Ticket,
  BarChart3,
  FileText,
  Search,
} from "lucide-react";

const SIDEBAR_GROUPS = [
  {
    label: "配置中心",
    icon: Box,
    items: [
      { href: "/admin/models", label: "模型管理", icon: Box },
      { href: "/admin/providers", label: "供应商管理", icon: Server },
      { href: "/admin/channels", label: "渠道配置", icon: Sliders },
    ],
  },
  {
    label: "运营中心",
    icon: Users,
    items: [
      { href: "/admin/users", label: "用户管理", icon: Users },
      { href: "/admin/redemption", label: "兑换码管理", icon: Ticket },
    ],
  },
  {
    label: "数据",
    icon: BarChart3,
    items: [
      { href: "/admin/dashboard", label: "业务概览", icon: BarChart3 },
      { href: "/admin/reconciliation", label: "供应商对账", icon: FileText },
      { href: "/admin/logs", label: "请求日志", icon: Search },
    ],
  },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!isLoading && (!user || user.role !== "admin")) {
      router.replace("/");
    }
  }, [user, isLoading, router]);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-sm text-neutral-text-secondary">加载中...</div>
      </div>
    );
  }

  if (!user || user.role !== "admin") {
    return null; // Will redirect via useEffect
  }

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="fixed left-0 top-0 z-20 flex h-screen w-[240px] flex-col bg-slate-900 text-slate-300">
        {/* Logo */}
        <div className="flex h-14 items-center gap-2 border-b border-slate-800 px-5">
          <Link
            href="/admin/models"
            className="text-lg font-semibold text-white"
          >
            high-api
          </Link>
          <span className="rounded bg-slate-700 px-1.5 py-0.5 text-xs text-slate-400">
            Admin
          </span>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-4">
          {SIDEBAR_GROUPS.map((group) => (
            <div key={group.label} className="mb-2">
              <div className="flex items-center gap-2 px-5 py-2 text-xs font-medium uppercase tracking-wider text-slate-500">
                <group.icon className="h-3.5 w-3.5" />
                {group.label}
              </div>
              {group.items.map((item) => {
                const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      "flex items-center gap-3 mx-3 px-3 py-2 rounded-md text-sm transition-colors",
                      isActive
                        ? "bg-slate-800 text-white"
                        : "text-slate-400 hover:bg-slate-800/50 hover:text-slate-200"
                    )}
                  >
                    <item.icon className="h-4 w-4" />
                    {item.label}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        {/* Footer */}
        <div className="border-t border-slate-800 p-4">
          <Link
            href="/"
            className="flex items-center gap-2 text-sm text-slate-500 hover:text-slate-300 transition-colors"
          >
            ← 返回用户端
          </Link>
        </div>
      </aside>

      {/* Main content */}
      <div className="ml-[240px] flex-1">
        <main className="p-6">{children}</main>
      </div>
    </div>
  );
}

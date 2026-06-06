"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ApiClientError } from "@/lib/api/client";
import {
  useAdminUsers,
  useToggleUserStatus,
  type AdminUserItem,
} from "@/lib/api/admin/users";
import { useAuth } from "@/lib/auth/AuthContext";
import { formatDate, formatPrice } from "@/lib/utils/format";

export default function AdminUsersPage() {
  const { user: currentUser } = useAuth();
  const { data: users, isLoading, error } = useAdminUsers();
  const toggleMutation = useToggleUserStatus();

  const [toggleTarget, setToggleTarget] = useState<AdminUserItem | null>(null);
  const [toggleError, setToggleError] = useState<string | null>(null);

  const handleToggle = async () => {
    if (!toggleTarget) return;
    setToggleError(null);
    try {
      await toggleMutation.mutateAsync(toggleTarget.id);
      setToggleTarget(null);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setToggleError(err.message);
      } else {
        setToggleError("操作失败，请重试");
      }
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-sm text-neutral-text-secondary">加载中...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-md bg-red-50 p-6 text-sm text-red-600">
        加载失败: {(error as ApiClientError).message || "未知错误"}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-neutral-text-primary">
          用户管理
        </h1>
        <p className="mt-1 text-sm text-neutral-text-secondary">
          查看用户账号、余额和登录状态
        </p>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white">
        <table className="w-full">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50 text-left text-sm text-neutral-text-secondary">
              <th className="px-4 py-3 font-medium">邮箱</th>
              <th className="px-4 py-3 text-right font-medium">余额</th>
              <th className="px-4 py-3 font-medium">角色</th>
              <th className="px-4 py-3 font-medium">状态</th>
              <th className="px-4 py-3 font-medium">注册时间</th>
              <th className="px-4 py-3 text-right font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {(!users || users.length === 0) && (
              <tr>
                <td
                  colSpan={6}
                  className="px-4 py-12 text-center text-sm text-neutral-text-secondary"
                >
                  暂无用户数据
                </td>
              </tr>
            )}
            {users?.map((item) => {
              const isSelf = currentUser?.user_id === item.id;
              const isActive = item.status === "active";
              return (
                <tr
                  key={item.id}
                  className="border-b border-slate-100 text-sm hover:bg-slate-50/50"
                >
                  <td className="px-4 py-3 font-medium text-neutral-text-primary">
                    {item.email}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-sm">
                    {formatPrice(item.balance)}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={item.role === "admin" ? "warning" : "muted"}>
                      {item.role === "admin" ? "管理员" : "用户"}
                    </Badge>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={isActive ? "success" : "error"}>
                      {isActive ? "启用" : "禁用"}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-neutral-text-secondary">
                    {formatDate(item.createdAt)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={isSelf || toggleMutation.isPending}
                      onClick={() => {
                        setToggleTarget(item);
                        setToggleError(null);
                      }}
                    >
                      {isActive ? "禁用" : "启用"}
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <Dialog
        open={!!toggleTarget}
        onOpenChange={() => {
          setToggleTarget(null);
          setToggleError(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {toggleTarget?.status === "active" ? "禁用用户" : "启用用户"}
            </DialogTitle>
            <DialogDescription>
              确定要{toggleTarget?.status === "active" ? "禁用" : "启用"}{" "}
              <strong>{toggleTarget?.email}</strong> 吗？
            </DialogDescription>
          </DialogHeader>
          {toggleError && (
            <div className="rounded-md bg-red-50 p-3 text-sm text-red-600">
              {toggleError}
            </div>
          )}
          <DialogFooter>
            <Button variant="secondary" onClick={() => setToggleTarget(null)}>
              取消
            </Button>
            <Button
              variant={toggleTarget?.status === "active" ? "destructive" : "primary"}
              onClick={handleToggle}
              disabled={toggleMutation.isPending}
            >
              {toggleMutation.isPending ? "处理中..." : "确认"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

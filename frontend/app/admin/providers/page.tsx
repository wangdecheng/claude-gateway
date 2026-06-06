"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ProviderEditForm } from "@/components/forms/ProviderEditForm";
import { Badge } from "@/components/ui/badge";
import { Plus, Trash2, Key, ChevronDown, ChevronRight } from "lucide-react";
import {
  useAdminProviders,
  useCreateProvider,
  useUpdateProvider,
  useToggleProviderStatus,
  useProviderKeys,
  useAddProviderKeys,
  useRevokeProviderKey,
  useDeleteProvider,
  type AdminProviderItem,
  type ProviderCreateInput,
  type ProviderUpdateInput,
  type ProviderKeyItem,
} from "@/lib/api/admin/providers";
import { ApiClientError } from "@/lib/api/client";

export default function AdminProvidersPage() {
  const { data: providers, isLoading, error } = useAdminProviders();
  const createMutation = useCreateProvider();
  const updateMutation = useUpdateProvider();
  const toggleMutation = useToggleProviderStatus();
  const deleteMutation = useDeleteProvider();

  // Delete confirmation state
  const [deleteTarget, setDeleteTarget] = useState<AdminProviderItem | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editingProvider, setEditingProvider] = useState<AdminProviderItem | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  // Expanded provider for key management
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const openCreate = () => {
    setEditingProvider(null);
    setFormError(null);
    setFormOpen(true);
  };

  const openEdit = (p: AdminProviderItem) => {
    setEditingProvider(p);
    setFormError(null);
    setFormOpen(true);
  };

  const handleSubmit = async (data: ProviderCreateInput | ProviderUpdateInput) => {
    setFormError(null);
    try {
      if (editingProvider) {
        await updateMutation.mutateAsync({
          id: editingProvider.id,
          data: data as ProviderUpdateInput,
        });
      } else {
        await createMutation.mutateAsync(data as ProviderCreateInput);
      }
      setFormOpen(false);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setFormError(err.message);
      } else {
        setFormError("操作失败，请重试");
      }
    }
  };

  const handleToggle = async (id: number) => {
    try {
      await toggleMutation.mutateAsync(id);
    } catch {
      // error handled by TanStack Query
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleteError(null);
    try {
      await deleteMutation.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setDeleteError(err.message);
      } else {
        setDeleteError("删除失败，请重试");
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
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-neutral-text-primary">
            供应商管理
          </h1>
          <p className="mt-1 text-sm text-neutral-text-secondary">
            管理上游 AI 供应商及其 API Key 池
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="mr-2 h-4 w-4" />
          添加供应商
        </Button>
      </div>

      {/* Table */}
      <div className="rounded-lg border border-slate-200 bg-white">
        <table className="w-full">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50 text-left text-sm text-neutral-text-secondary">
              <th className="w-8 px-4 py-3" />
              <th className="px-4 py-3 font-medium">名称</th>
              <th className="px-4 py-3 font-medium">API Base URL</th>
              <th className="px-4 py-3 font-medium">适配器</th>
              <th className="px-4 py-3 font-medium text-right">Keys</th>
              <th className="px-4 py-3 font-medium">状态</th>
              <th className="px-4 py-3 font-medium text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            {(!providers || providers.length === 0) && (
              <tr>
                <td colSpan={7} className="px-4 py-12 text-center text-sm text-neutral-text-secondary">
                  还没有供应商，点击"添加供应商"开始
                </td>
              </tr>
            )}
            {providers?.map((p) => (
              <ProviderRow
                key={p.id}
                provider={p}
                isExpanded={expandedId === p.id}
                onToggleExpand={() =>
                  setExpandedId(expandedId === p.id ? null : p.id)
                }
                onEdit={() => openEdit(p)}
                onToggle={() => handleToggle(p.id)}
                onDelete={() => { setDeleteTarget(p); setDeleteError(null); }}
                isToggling={toggleMutation.isPending}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* Form Dialog */}
      <ProviderEditForm
        open={formOpen}
        onOpenChange={setFormOpen}
        onSubmit={handleSubmit}
        provider={editingProvider}
        isSubmitting={createMutation.isPending || updateMutation.isPending}
        error={formError}
      />

      {/* Delete Confirmation Dialog */}
      <Dialog open={!!deleteTarget} onOpenChange={() => { setDeleteTarget(null); setDeleteError(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除供应商</DialogTitle>
            <DialogDescription>
              确定要删除 <strong>{deleteTarget?.name}</strong> 吗？
              <br />
              删除后将无法通过该供应商转发 API 请求。
            </DialogDescription>
          </DialogHeader>
          {deleteError && (
            <div className="rounded-md bg-red-50 p-3 text-sm text-red-600">
              {deleteError}
            </div>
          )}
          <DialogFooter>
            <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? "删除中..." : "确认删除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/** A single provider row with expandable key management. */
function ProviderRow({
  provider,
  isExpanded,
  onToggleExpand,
  onEdit,
  onToggle,
  onDelete,
  isToggling,
}: {
  provider: AdminProviderItem;
  isExpanded: boolean;
  onToggleExpand: () => void;
  onEdit: () => void;
  onToggle: () => void;
  onDelete: () => void;
  isToggling: boolean;
}) {
  return (
    <>
      <tr className="border-b border-slate-100 text-sm hover:bg-slate-50/50">
        <td className="px-4 py-3">
          <button
            onClick={onToggleExpand}
            className="text-neutral-text-secondary hover:text-neutral-text-primary"
          >
            {isExpanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </button>
        </td>
        <td className="px-4 py-3 font-medium text-neutral-text-primary">
          {provider.name}
        </td>
        <td className="px-4 py-3 font-mono text-xs text-neutral-text-secondary max-w-[240px] truncate">
          {provider.apiBaseUrl}
        </td>
        <td className="px-4 py-3">
          <Badge variant="muted">
            {provider.adapter === "anthropic-messages" ? "Anthropic" : "OpenAI"}
          </Badge>
        </td>
        <td className="px-4 py-3 text-right font-mono text-sm">
          <span className="text-neutral-text-primary">{provider.activeKeyCount}</span>
          <span className="text-neutral-text-secondary">
            /{provider.keyCount}
          </span>
        </td>
        <td className="px-4 py-3">
          <Badge variant={provider.status === "active" ? "success" : "muted"}>
            {provider.status === "active" ? "启用" : "停用"}
          </Badge>
        </td>
        <td className="px-4 py-3 text-right">
          <div className="flex items-center justify-end gap-1">
            <Button variant="ghost" size="sm" onClick={onEdit}>
              编辑
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={onToggle}
              disabled={isToggling}
            >
              {provider.status === "active" ? "停用" : "启用"}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={onDelete}
              className="text-red-500 hover:text-red-600"
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </td>
      </tr>
      {isExpanded && (
        <tr key={`keys-${provider.id}`}>
          <td colSpan={7} className="border-b border-slate-100 bg-slate-50/30 px-8 py-4">
            <KeyManager providerId={provider.id} providerName={provider.name} />
          </td>
        </tr>
      )}
    </>
  );
}

/** Key pool management panel shown when a provider row is expanded. */
function KeyManager({
  providerId,
  providerName,
}: {
  providerId: number;
  providerName: string;
}) {
  const { data: keys, isLoading, error } = useProviderKeys(providerId);
  const addKeysMutation = useAddProviderKeys();
  const revokeMutation = useRevokeProviderKey();

  const [newKeys, setNewKeys] = useState("");
  const [adding, setAdding] = useState(false);
  const [revokeConfirm, setRevokeConfirm] = useState<ProviderKeyItem | null>(null);

  const handleAddKeys = async () => {
    const keyList = newKeys
      .split("\n")
      .map((k) => k.trim())
      .filter(Boolean);
    if (keyList.length === 0) return;

    try {
      await addKeysMutation.mutateAsync({ providerId, keys: keyList });
      setNewKeys("");
      setAdding(false);
    } catch {
      // handled by TanStack Query
    }
  };

  const handleRevoke = async () => {
    if (!revokeConfirm) return;
    try {
      await revokeMutation.mutateAsync({
        providerId,
        keyId: revokeConfirm.id,
      });
      setRevokeConfirm(null);
    } catch {
      // handled by TanStack Query
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm font-medium text-neutral-text-primary">
        <Key className="h-4 w-4" />
        {providerName} 的 API Key 池
      </div>

      {/* Key list */}
      {isLoading && (
        <div className="text-sm text-neutral-text-secondary">加载 Key 列表...</div>
      )}
      {error && (
        <div className="text-sm text-red-500">
          加载失败: {(error as ApiClientError).message}
        </div>
      )}

      {keys && keys.length === 0 && !isLoading && (
        <div className="text-sm text-neutral-text-secondary">
          还没有添加任何 Key，请先添加。
        </div>
      )}

      {keys && keys.length > 0 && (
        <div className="rounded-md border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50 text-xs text-neutral-text-secondary">
                <th className="px-3 py-2 text-left font-medium">Key (脱敏)</th>
                <th className="px-3 py-2 text-left font-medium">状态</th>
                <th className="px-3 py-2 text-left font-medium">创建时间</th>
                <th className="px-3 py-2 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.id} className="border-b border-slate-50 last:border-0">
                  <td className="px-3 py-2 font-mono text-xs text-neutral-text-primary">
                    {k.keyPrefix}
                  </td>
                  <td className="px-3 py-2">
                    <Badge variant={k.status === "active" ? "success" : "muted"}>
                      {k.status === "active" ? "可用" : "已移除"}
                    </Badge>
                  </td>
                  <td className="px-3 py-2 text-xs text-neutral-text-secondary">
                    {new Date(k.createdAt).toLocaleString("zh-CN")}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {k.status === "active" && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-red-500 hover:text-red-600"
                        onClick={() => setRevokeConfirm(k)}
                      >
                        <Trash2 className="mr-1 h-3 w-3" />
                        移除
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Add keys section */}
      {adding ? (
        <div className="space-y-2 rounded-md border border-slate-200 bg-white p-3">
          <Label htmlFor="newKeys" className="text-xs">
            新增 Key（每行一把）
          </Label>
          <Textarea
            id="newKeys"
            rows={3}
            className="font-mono text-xs"
            placeholder="sk-ant-api03-xxxxx&#10;sk-ant-api03-yyyyy"
            value={newKeys}
            onChange={(e) => setNewKeys(e.target.value)}
          />
          <div className="flex gap-2">
            <Button
              size="sm"
              onClick={handleAddKeys}
              disabled={addKeysMutation.isPending}
            >
              {addKeysMutation.isPending ? "保存中..." : "保存"}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setAdding(false);
                setNewKeys("");
              }}
            >
              取消
            </Button>
          </div>
        </div>
      ) : (
        <Button variant="secondary" size="sm" onClick={() => setAdding(true)}>
          <Plus className="mr-1 h-3 w-3" />
          添加 Key
        </Button>
      )}

      {/* Revoke confirmation dialog */}
      <Dialog
        open={revokeConfirm !== null}
        onOpenChange={(open) => !open && setRevokeConfirm(null)}
      >
        <DialogContent className="sm:max-w-[400px]">
          <DialogHeader>
            <DialogTitle>移除 Key</DialogTitle>
            <DialogDescription>
              确定要移除此 Key 吗？该操作不可撤销，移除后将立即停止用于 API 转发。
            </DialogDescription>
          </DialogHeader>
          {revokeConfirm && (
            <div className="rounded-md bg-slate-100 p-3 font-mono text-sm">
              {revokeConfirm.keyPrefix}
            </div>
          )}
          <DialogFooter>
            <Button
              variant="secondary"
              onClick={() => setRevokeConfirm(null)}
              disabled={revokeMutation.isPending}
            >
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={handleRevoke}
              disabled={revokeMutation.isPending}
            >
              {revokeMutation.isPending ? "移除中..." : "确认移除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Plus, Trash2 } from "lucide-react";
import { ApiClientError } from "@/lib/api/client";
import {
  useAdminChannels,
  useCreateChannel,
  useUpdateChannel,
  useToggleChannelStatus,
  useDeleteChannel,
  type AdminChannelItem,
} from "@/lib/api/admin/channels";
import { useAdminModels, useAdminProviders } from "@/lib/api/admin/models";

export default function AdminChannelsPage() {
  const { data: channels, isLoading, error } = useAdminChannels();
  const createMutation = useCreateChannel();
  const updateMutation = useUpdateChannel();
  const toggleMutation = useToggleChannelStatus();
  const deleteMutation = useDeleteChannel();

  const [formOpen, setFormOpen] = useState(false);
  const [editingChannel, setEditingChannel] = useState<AdminChannelItem | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [toggleConfirm, setToggleConfirm] = useState<AdminChannelItem | null>(null);

  // Delete confirmation
  const [deleteTarget, setDeleteTarget] = useState<AdminChannelItem | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const openCreate = () => {
    setEditingChannel(null);
    setFormError(null);
    setFormOpen(true);
  };

  const openEdit = (channel: AdminChannelItem) => {
    setEditingChannel(channel);
    setFormError(null);
    setFormOpen(true);
  };

  const handleSubmit = async (data: ChannelFormValues) => {
    setFormError(null);
    try {
      if (editingChannel) {
        await updateMutation.mutateAsync({
          id: editingChannel.id,
          data: {
            name: data.name || undefined,
            providerModelId: data.providerModelId || undefined,
            multiplier: data.multiplier,
            isDefault: data.isDefault,
          },
        });
      } else {
        await createMutation.mutateAsync({
          modelId: data.modelId,
          providerId: data.providerId,
          name: data.name,
          providerModelId: data.providerModelId,
          multiplier: data.multiplier,
          isDefault: data.isDefault,
        });
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

  const handleToggle = async () => {
    if (!toggleConfirm) return;
    try {
      await toggleMutation.mutateAsync(toggleConfirm.id);
      setToggleConfirm(null);
    } catch {
      // handled by TanStack Query
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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-neutral-text-primary">
            渠道倍率配置
          </h1>
          <p className="mt-1 text-sm text-neutral-text-secondary">
            为每个供应商-模型组合配置上游模型 ID、倍率和默认渠道
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="mr-2 h-4 w-4" />
          添加渠道
        </Button>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white">
        <table className="w-full">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50 text-left text-sm text-neutral-text-secondary">
              <th className="px-4 py-3 font-medium">模型</th>
              <th className="px-4 py-3 font-medium">供应商</th>
              <th className="px-4 py-3 font-medium">渠道名称</th>
              <th className="px-4 py-3 font-medium">上游模型 ID</th>
              <th className="px-4 py-3 text-right font-medium">倍率</th>
              <th className="px-4 py-3 font-medium">默认</th>
              <th className="px-4 py-3 font-medium">渠道状态</th>
              <th className="px-4 py-3 font-medium">模型/供应商</th>
              <th className="px-4 py-3 text-right font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {(!channels || channels.length === 0) && (
              <tr>
                <td colSpan={9} className="px-4 py-12 text-center text-sm text-neutral-text-secondary">
                  还没有渠道配置，点击"添加渠道"开始
                </td>
              </tr>
            )}
            {channels?.map((channel) => (
              <tr key={channel.id} className="border-b border-slate-100 text-sm hover:bg-slate-50/50">
                <td className="px-4 py-3 font-mono text-xs text-neutral-text-primary">
                  {channel.modelName}
                </td>
                <td className="px-4 py-3 text-neutral-text-primary">
                  {channel.providerName}
                </td>
                <td className="px-4 py-3 text-neutral-text-primary">
                  {channel.name}
                </td>
                <td className="px-4 py-3">
                  <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
                    {channel.providerModelId}
                  </code>
                </td>
                <td className="px-4 py-3 text-right font-mono text-sm">
                  {channel.multiplier.toFixed(2)}x
                </td>
                <td className="px-4 py-3">
                  {channel.isDefault ? <Badge variant="success">默认</Badge> : <span className="text-neutral-text-muted">—</span>}
                </td>
                <td className="px-4 py-3">
                  <Badge variant={channel.status === "active" ? "success" : "muted"}>
                    {channel.status === "active" ? "启用" : "停用"}
                  </Badge>
                </td>
                <td className="px-4 py-3">
                  <div className="flex gap-1">
                    <Badge variant={channel.modelStatus === "active" ? "success" : "muted"}>
                      模型{channel.modelStatus === "active" ? "上架" : "下架"}
                    </Badge>
                    <Badge variant={channel.providerStatus === "active" ? "success" : "muted"}>
                      供应商{channel.providerStatus === "active" ? "启用" : "停用"}
                    </Badge>
                  </div>
                </td>
                <td className="px-4 py-3 text-right">
                  <div className="flex justify-end gap-1">
                    <Button variant="ghost" size="sm" onClick={() => openEdit(channel)}>
                      编辑
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setToggleConfirm(channel)}
                      disabled={toggleMutation.isPending}
                    >
                      {channel.status === "active" ? "停用" : "启用"}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => { setDeleteTarget(channel); setDeleteError(null); }}
                      className="text-red-500 hover:text-red-600"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ChannelFormDialog
        open={formOpen}
        onOpenChange={setFormOpen}
        channel={editingChannel}
        onSubmit={handleSubmit}
        isSubmitting={createMutation.isPending || updateMutation.isPending}
        error={formError}
      />

      {/* Toggle confirmation dialog */}
      <Dialog open={toggleConfirm !== null} onOpenChange={(open) => !open && setToggleConfirm(null)}>
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader>
            <DialogTitle>{toggleConfirm?.status === "active" ? "停用渠道" : "启用渠道"}</DialogTitle>
            <DialogDescription>
              {toggleConfirm?.status === "active"
                ? "停用后，用户新建 sk 时不再展示该渠道。"
                : "启用后，用户可再次选择该渠道。"}
            </DialogDescription>
          </DialogHeader>
          {toggleConfirm && (
            <div className="rounded-md bg-slate-100 p-3 text-sm">
              <span className="font-mono">{toggleConfirm.modelName}</span> → {toggleConfirm.providerName}
            </div>
          )}
          <DialogFooter>
            <Button variant="secondary" onClick={() => setToggleConfirm(null)}>
              取消
            </Button>
            <Button onClick={handleToggle} disabled={toggleMutation.isPending}>
              {toggleMutation.isPending ? "处理中..." : "确认"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={!!deleteTarget} onOpenChange={() => { setDeleteTarget(null); setDeleteError(null); }}>
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader>
            <DialogTitle>删除渠道</DialogTitle>
            <DialogDescription>
              确定要删除此渠道配置吗？
              <br />
              删除后该供应商-模型组合将不再可用。
            </DialogDescription>
          </DialogHeader>
          {deleteTarget && (
            <div className="rounded-md bg-slate-100 p-3 text-sm">
              <span className="font-mono">{deleteTarget.modelName}</span> → {deleteTarget.providerName}
            </div>
          )}
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

interface ChannelFormValues {
  modelId: number;
  providerId: number;
  name: string;
  providerModelId: string;
  multiplier: number;
  isDefault: boolean;
}

function ChannelFormDialog({
  open,
  onOpenChange,
  channel,
  onSubmit,
  isSubmitting,
  error,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  channel: AdminChannelItem | null;
  onSubmit: (data: ChannelFormValues) => Promise<void>;
  isSubmitting: boolean;
  error: string | null;
}) {
  const { data: models } = useAdminModels();
  const { data: providers } = useAdminProviders();

  const [modelId, setModelId] = useState(channel?.modelId ?? 0);
  const [providerId, setProviderId] = useState(channel?.providerId ?? 0);
  const [name, setName] = useState(channel?.name ?? "");
  const [providerModelId, setProviderModelId] = useState(channel?.providerModelId ?? "");
  const [multiplier, setMultiplier] = useState(channel?.multiplier ?? 1.0);
  const [isDefault, setIsDefault] = useState(channel?.isDefault ?? false);

  useEffect(() => {
    if (open) {
      setModelId(channel?.modelId ?? 0);
      setProviderId(channel?.providerId ?? 0);
      setName(channel?.name ?? "");
      setProviderModelId(channel?.providerModelId ?? "");
      setMultiplier(channel?.multiplier ?? 1.0);
      setIsDefault(channel?.isDefault ?? false);
    }
  }, [open, channel]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await onSubmit({ modelId, providerId, name, providerModelId, multiplier, isDefault });
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          setModelId(0);
          setProviderId(0);
          setName("");
          setProviderModelId("");
          setMultiplier(1.0);
          setIsDefault(false);
        }
        onOpenChange(nextOpen);
      }}
    >
      <DialogContent className="sm:max-w-[520px]">
        <form onSubmit={handleSubmit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>{channel ? "编辑渠道" : "添加渠道"}</DialogTitle>
            <DialogDescription>
              配置模型与供应商之间的上游模型 ID、倍率和默认渠道。
            </DialogDescription>
          </DialogHeader>

          {error && <div className="rounded-md bg-red-50 p-3 text-sm text-red-600">{error}</div>}

          <div className="space-y-2">
            <Label>模型</Label>
            <Select
              value={modelId ? String(modelId) : ""}
              onValueChange={(value) => setModelId(Number(value))}
              disabled={Boolean(channel)}
            >
              <SelectTrigger>
                <SelectValue placeholder="选择模型" />
              </SelectTrigger>
              <SelectContent>
                {models?.map((model) => (
                  <SelectItem key={model.id} value={String(model.id)}>
                    {model.publicName}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>供应商</Label>
            <Select
              value={providerId ? String(providerId) : ""}
              onValueChange={(value) => setProviderId(Number(value))}
              disabled={Boolean(channel)}
            >
              <SelectTrigger>
                <SelectValue placeholder="选择供应商" />
              </SelectTrigger>
              <SelectContent>
                {providers?.map((provider) => (
                  <SelectItem key={provider.id} value={String(provider.id)}>
                    {provider.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="channelName">
              渠道名称 <span className="text-red-500">*</span>
            </Label>
            <Input
              id="channelName"
              placeholder="如 主力线路、Anthropic 官方"
              maxLength={50}
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="providerModelId">
              上游模型 ID <span className="text-red-500">*</span>
            </Label>
            <Input
              id="providerModelId"
              placeholder="如 deepseekV4-pro"
              maxLength={200}
              value={providerModelId}
              onChange={(event) => setProviderModelId(event.target.value)}
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="multiplier">倍率</Label>
            <Input
              id="multiplier"
              type="number"
              min="0.01"
              step="0.01"
              className="font-mono"
              value={multiplier}
              onChange={(event) => {
                const parsed = parseFloat(event.target.value);
                setMultiplier(isNaN(parsed) ? 0 : parsed);
              }}
              required
            />
          </div>

          <label className="flex items-center gap-2 text-sm text-neutral-text-primary">
            <input
              type="checkbox"
              checked={isDefault}
              onChange={(event) => setIsDefault(event.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            设为默认渠道
          </label>

          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
              取消
            </Button>
            <Button
              type="submit"
              disabled={
                isSubmitting ||
                !modelId ||
                !providerId ||
                !name.trim() ||
                !providerModelId.trim() ||
                multiplier <= 0
              }
            >
              {isSubmitting ? "保存中..." : "保存"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

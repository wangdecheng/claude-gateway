"use client";

import { useEffect } from "react";
import { useForm } from "react-hook-form";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { AdminProviderItem, ProviderCreateInput, ProviderUpdateInput } from "@/lib/api/admin/providers";

interface ProviderEditFormProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (data: ProviderCreateInput | ProviderUpdateInput) => Promise<void>;
  provider?: AdminProviderItem | null; // null = create mode
  isSubmitting: boolean;
  error?: string | null;
}

interface FormValues {
  name: string;
  apiBaseUrl: string;
  authHeader: string;
  adapter: string;
  keys: string;
}

export function ProviderEditForm({
  open,
  onOpenChange,
  onSubmit,
  provider,
  isSubmitting,
  error,
}: ProviderEditFormProps) {
  const isEdit = !!provider;

  const {
    register,
    handleSubmit,
    reset,
    setValue,
    watch,
    formState: { errors },
  } = useForm<FormValues>({
    defaultValues: {
      name: "",
      apiBaseUrl: "",
      authHeader: "Authorization",
      adapter: "openai-chat-completions",
      keys: "",
    },
  });

  const adapterValue = watch("adapter");

  useEffect(() => {
    if (open) {
      if (provider) {
        reset({
          name: provider.name,
          apiBaseUrl: provider.apiBaseUrl,
          authHeader: provider.authHeader,
          adapter: provider.adapter,
          keys: "",
        });
      } else {
        reset({
          name: "",
          apiBaseUrl: "",
          authHeader: "Authorization",
          adapter: "openai-chat-completions",
          keys: "",
        });
      }
    }
  }, [open, provider, reset]);

  const onFormSubmit = async (values: FormValues) => {
    const keyList = values.keys
      .split("\n")
      .map((k) => k.trim())
      .filter(Boolean);

    if (isEdit) {
      const data: ProviderUpdateInput = {
        name: values.name,
        apiBaseUrl: values.apiBaseUrl,
        authHeader: values.authHeader,
        adapter: values.adapter,
      };
      await onSubmit(data);
    } else {
      const data: ProviderCreateInput = {
        name: values.name,
        apiBaseUrl: values.apiBaseUrl,
        authHeader: values.authHeader,
        adapter: values.adapter,
        keys: keyList.length > 0 ? keyList : undefined,
      };
      await onSubmit(data);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>{isEdit ? "编辑供应商" : "添加供应商"}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? "修改供应商的基本信息和认证配置。"
              : "添加一个新的上游 AI 供应商。"}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onFormSubmit)} className="space-y-4">
          {/* Name */}
          <div className="space-y-2">
            <Label htmlFor="name">供应商名称 *</Label>
            <Input
              id="name"
              placeholder="如 Anthropic、DeepSeek"
              {...register("name", { required: "请输入供应商名称" })}
            />
            {errors.name && (
              <p className="text-sm text-red-500">{errors.name.message}</p>
            )}
          </div>

          {/* API Base URL */}
          <div className="space-y-2">
            <Label htmlFor="apiBaseUrl">API Base URL *</Label>
            <Input
              id="apiBaseUrl"
              placeholder="https://api.anthropic.com"
              className="font-mono text-sm"
              {...register("apiBaseUrl", { required: "请输入 API Base URL" })}
            />
            {errors.apiBaseUrl && (
              <p className="text-sm text-red-500">{errors.apiBaseUrl.message}</p>
            )}
          </div>

          {/* Auth Header + Adapter */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="authHeader">认证头</Label>
              <Select
                value={watch("authHeader")}
                onValueChange={(v) => setValue("authHeader", v)}
              >
                <SelectTrigger id="authHeader">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="Authorization">Authorization (Bearer)</SelectItem>
                  <SelectItem value="x-api-key">x-api-key</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="adapter">协议适配器</Label>
              <Select
                value={adapterValue}
                onValueChange={(v) => setValue("adapter", v)}
              >
                <SelectTrigger id="adapter">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="openai-chat-completions">
                    OpenAI Chat Completions
                  </SelectItem>
                  <SelectItem value="anthropic-messages">
                    Anthropic Messages
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Keys — create mode only */}
          {!isEdit && (
            <div className="space-y-2">
              <Label htmlFor="keys">
                上游 API Key（可选，每行一把 Key）
              </Label>
              <Textarea
                id="keys"
                rows={3}
                placeholder={"sk-ant-api03-xxxxx\ndeepseek-api-key-xxxxx"}
                className="font-mono text-sm"
                {...register("keys")}
              />
              <p className="text-xs text-neutral-text-secondary">
                Key 将使用 AES-256-GCM 加密存储，后续可在 Key 管理中继续添加。
              </p>
            </div>
          )}

          {error && (
            <div className="rounded-md bg-red-50 p-3 text-sm text-red-600">
              {error}
            </div>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => onOpenChange(false)}
              disabled={isSubmitting}
            >
              取消
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "保存中..." : isEdit ? "保存修改" : "添加供应商"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

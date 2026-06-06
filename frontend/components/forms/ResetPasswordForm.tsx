"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useResetPassword } from "@/lib/api/auth";
import { ApiClientError } from "@/lib/api/client";

const schema = z
  .object({
    newPassword: z.string().min(8, "密码至少8位"),
    confirmNewPassword: z.string().min(1, "请确认新密码"),
  })
  .refine((data) => data.newPassword === data.confirmNewPassword, {
    message: "两次密码不一致",
    path: ["confirmNewPassword"],
  });

type FormData = z.infer<typeof schema>;

export function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") || "";

  const mutation = useResetPassword();

  const {
    register,
    handleSubmit,
    formState: { errors },
    setError,
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  const onSubmit = async (data: FormData) => {
    if (!token) {
      setError("root", { message: "缺少重置令牌，请从邮箱链接进入" });
      return;
    }
    try {
      await mutation.mutateAsync({
        token,
        newPassword: data.newPassword,
        confirmNewPassword: data.confirmNewPassword,
      });
    } catch (err) {
      if (err instanceof ApiClientError) {
        setError("root", { message: err.message });
      } else {
        setError("root", { message: "重置失败，请稍后重试" });
      }
    }
  };

  if (mutation.isSuccess) {
    return (
      <Card className="w-full max-w-md mx-auto">
        <CardHeader>
          <CardTitle>密码重置成功</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-[#16a34a]">
            密码已重置，请使用新密码登录。
          </p>
          <Button
            variant="primary"
            size="md"
            className="w-full"
            onClick={() => router.push("/login")}
          >
            前往登录
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="w-full max-w-md mx-auto">
      <CardHeader>
        <CardTitle>重置密码</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="newPassword">新密码</Label>
            <Input
              id="newPassword"
              type="password"
              placeholder="至少8位"
              autoComplete="new-password"
              error={!!errors.newPassword}
              {...register("newPassword")}
            />
            {errors.newPassword && (
              <p className="text-sm text-[#dc2626]">{errors.newPassword.message}</p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="confirmNewPassword">确认新密码</Label>
            <Input
              id="confirmNewPassword"
              type="password"
              placeholder="再次输入新密码"
              autoComplete="new-password"
              error={!!errors.confirmNewPassword}
              {...register("confirmNewPassword")}
            />
            {errors.confirmNewPassword && (
              <p className="text-sm text-[#dc2626]">{errors.confirmNewPassword.message}</p>
            )}
          </div>

          {errors.root && (
            <p className="text-sm text-[#dc2626]">{errors.root.message}</p>
          )}

          <Button type="submit" variant="primary" size="md" className="w-full" disabled={mutation.isPending}>
            {mutation.isPending ? "重置中..." : "重置密码"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

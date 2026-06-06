"use client";

import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useChangePassword } from "@/lib/api/auth";
import { ApiClientError } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/AuthContext";

const schema = z
  .object({
    currentPassword: z.string().min(1, "请输入当前密码"),
    newPassword: z.string().min(8, "密码至少8位"),
    confirmNewPassword: z.string().min(1, "请确认新密码"),
  })
  .refine((data) => data.newPassword === data.confirmNewPassword, {
    message: "两次密码不一致",
    path: ["confirmNewPassword"],
  });

type FormData = z.infer<typeof schema>;

export function ChangePasswordForm() {
  const router = useRouter();
  const { refetch } = useAuth();
  const mutation = useChangePassword();

  const {
    register,
    handleSubmit,
    formState: { errors },
    setError,
    reset,
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  const onSubmit = async (data: FormData) => {
    try {
      await mutation.mutateAsync({
        currentPassword: data.currentPassword,
        newPassword: data.newPassword,
        confirmNewPassword: data.confirmNewPassword,
      });
      reset();
      await refetch();
    } catch (err) {
      if (err instanceof ApiClientError) {
        if (err.code === "WRONG_PASSWORD") {
          setError("currentPassword", { message: err.message });
        } else {
          setError("root", { message: err.message });
        }
      } else {
        setError("root", { message: "修改失败，请稍后重试" });
      }
    }
  };

  return (
    <Card className="w-full max-w-md mx-auto">
      <CardHeader>
        <CardTitle>修改密码</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="currentPassword">当前密码</Label>
            <Input
              id="currentPassword"
              type="password"
              autoComplete="current-password"
              error={!!errors.currentPassword}
              {...register("currentPassword")}
            />
            {errors.currentPassword && (
              <p className="text-sm text-[#dc2626]">{errors.currentPassword.message}</p>
            )}
          </div>

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

          {mutation.isSuccess && (
            <p className="text-sm text-[#16a34a]">密码修改成功</p>
          )}

          <Button type="submit" variant="primary" size="md" className="w-full" disabled={mutation.isPending}>
            {mutation.isPending ? "修改中..." : "修改密码"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

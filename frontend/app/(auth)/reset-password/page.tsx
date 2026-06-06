import { Suspense } from "react";
import { ResetPasswordForm } from "@/components/forms/ResetPasswordForm";

export default function ResetPasswordPage() {
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <Suspense fallback={<div>加载中...</div>}>
        <ResetPasswordForm />
      </Suspense>
    </div>
  );
}

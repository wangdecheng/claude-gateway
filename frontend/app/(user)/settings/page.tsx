import { ChangePasswordForm } from "@/components/forms/ChangePasswordForm";

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">账号设置</h1>
      <ChangePasswordForm />
    </div>
  );
}

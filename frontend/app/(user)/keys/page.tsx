import { KeyList } from "@/components/data/KeyList";
import { CreateKeyForm } from "@/components/forms/CreateKeyForm";

export default function KeysPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">sk 管理</h1>
      <CreateKeyForm />
      <KeyList />
    </div>
  );
}

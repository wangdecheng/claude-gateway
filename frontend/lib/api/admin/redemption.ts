import { useMutation } from "@tanstack/react-query";
import { apiClient, ApiClientError } from "../client";

export interface AdminRedemptionCreateInput {
  amount: number;
  expiresInDays?: number;
}

export interface AdminRedemptionCreateResult {
  id: number;
  code: string;
  codePrefix: string;
  amount: number;
  status: string;
  expiresAt: string;
  createdAt: string;
}

export function useCreateAdminRedemptionCode() {
  return useMutation<
    AdminRedemptionCreateResult,
    ApiClientError,
    AdminRedemptionCreateInput
  >({
    mutationFn: (data) =>
      apiClient<AdminRedemptionCreateResult>("/admin/redemption", {
        method: "POST",
        body: JSON.stringify(data),
      }),
  });
}

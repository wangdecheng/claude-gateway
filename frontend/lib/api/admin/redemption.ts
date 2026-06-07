import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

export interface AdminRedemptionListItem {
  id: number;
  codePrefix: string;
  amount: number;
  /** Effective status: 'issued' | 'used' | 'expired'. */
  status: string;
  expiresAt: string;
  createdAt: string;
  createdByEmail: string | null;
  usedByEmail: string | null;
  usedAt: string | null;
}

const LIST_QUERY_KEY = ["admin", "redemption", "list"] as const;

export function useCreateAdminRedemptionCode() {
  const queryClient = useQueryClient();
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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: LIST_QUERY_KEY });
    },
  });
}

export function useAdminRedemptionList() {
  return useQuery<AdminRedemptionListItem[], ApiClientError>({
    queryKey: LIST_QUERY_KEY,
    queryFn: () => apiClient<AdminRedemptionListItem[]>("/admin/redemption"),
  });
}

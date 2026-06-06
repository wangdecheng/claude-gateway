import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient, ApiClientError } from "./client";

interface RedeemRequest {
  code: string;
}

interface RedeemResponse {
  amount: number;
  balance: number;
  message: string;
}

interface RedemptionHistoryItem {
  id: number;
  codeMasked: string;
  amount: number;
  createdAt: string;
}

interface RedemptionHistoryResponse {
  items: RedemptionHistoryItem[];
}

export function useRedeem() {
  const queryClient = useQueryClient();
  return useMutation<RedeemResponse, ApiClientError, RedeemRequest>({
    mutationFn: (data) =>
      apiClient<RedeemResponse>("/redeem", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
      queryClient.invalidateQueries({ queryKey: ["redemption", "history"] });
    },
  });
}

export function useRedemptionHistory() {
  return useQuery<RedemptionHistoryResponse, ApiClientError>({
    queryKey: ["redemption", "history"],
    queryFn: () =>
      apiClient<RedemptionHistoryResponse>("/redeem/history"),
    staleTime: 30 * 1000,
  });
}

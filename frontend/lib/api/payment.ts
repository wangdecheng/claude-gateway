import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient, ApiClientError } from "./client";

// --- Types ---

interface CreateOrderRequest {
  amount: number;
  method: "alipay" | "wechat";
}

interface CreateOrderResponse {
  orderId: number;
  amount: number;
  method: string;
  status: string;
  payUrl: string;
  createdAt: string;
}

interface PaymentHistoryItem {
  id: number;
  amount: number;
  method: string;
  status: string;
  transactionId: string | null;
  createdAt: string;
}

interface PaymentHistoryResponse {
  items: PaymentHistoryItem[];
  total: number;
  page: number;
  pageSize: number;
}

// --- Hooks ---

export function useCreateOrder() {
  const queryClient = useQueryClient();
  return useMutation<CreateOrderResponse, ApiClientError, CreateOrderRequest>({
    mutationFn: (data) =>
      apiClient<CreateOrderResponse>("/payment/orders", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
      queryClient.invalidateQueries({ queryKey: ["payment", "history"] });
    },
  });
}

export function usePaymentHistory(page: number = 1) {
  return useQuery<PaymentHistoryResponse, ApiClientError>({
    queryKey: ["payment", "history", page],
    queryFn: () =>
      apiClient<PaymentHistoryResponse>(
        `/payment/history?page=${page}&page_size=20`
      ),
    staleTime: 30 * 1000,
  });
}

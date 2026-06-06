import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient, ApiClientError } from "../client";

export interface AdminUserItem {
  id: number;
  email: string;
  balance: number;
  role: "user" | "admin";
  status: "active" | "disabled" | string;
  createdAt: string;
}

export function useAdminUsers() {
  return useQuery<AdminUserItem[], ApiClientError>({
    queryKey: ["admin", "users"],
    queryFn: () => apiClient<AdminUserItem[]>("/admin/users"),
  });
}

export function useToggleUserStatus() {
  const queryClient = useQueryClient();

  return useMutation<AdminUserItem, ApiClientError, number>({
    mutationFn: (id) =>
      apiClient<AdminUserItem>(`/admin/users/${id}/status`, {
        method: "PATCH",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
    },
  });
}

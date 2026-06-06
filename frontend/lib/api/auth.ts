import { useMutation, useQuery } from "@tanstack/react-query";
import { apiClient, ApiClientError } from "./client";

interface RegisterRequest {
  email: string;
  password: string;
  confirmPassword: string;
}

interface AuthResponse {
  user_id: number;
  email: string;
  balance: number;
  role: string;
}

export function useRegister() {
  return useMutation<AuthResponse, ApiClientError, RegisterRequest>({
    mutationFn: (data) =>
      apiClient<AuthResponse>("/auth/register", {
        method: "POST",
        body: JSON.stringify(data),
      }),
  });
}

export function useLogin() {
  return useMutation<AuthResponse, ApiClientError, { email: string; password: string }>(
    {
      mutationFn: (data) =>
        apiClient<AuthResponse>("/auth/login", {
          method: "POST",
          body: JSON.stringify(data),
        }),
    }
  );
}

export function useMe() {
  return useQuery<AuthResponse, ApiClientError>({
    queryKey: ["auth", "me"],
    queryFn: () => apiClient<AuthResponse>("/auth/me"),
    retry: false,
    staleTime: 60 * 1000,
  });
}

export function useLogout() {
  return useMutation<{ message: string }, ApiClientError, void>({
    mutationFn: () =>
      apiClient<{ message: string }>("/auth/logout", { method: "POST" }),
  });
}

export function useChangePassword() {
  return useMutation<
    { message: string },
    ApiClientError,
    { currentPassword: string; newPassword: string; confirmNewPassword: string }
  >({
    mutationFn: (data) =>
      apiClient<{ message: string }>("/auth/change-password", {
        method: "POST",
        body: JSON.stringify(data),
      }),
  });
}

export function useForgotPassword() {
  return useMutation<
    { message: string; token?: string },
    ApiClientError,
    { email: string }
  >({
    mutationFn: (data) =>
      apiClient<{ message: string; token?: string }>("/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify(data),
      }),
  });
}

export function useResetPassword() {
  return useMutation<
    { message: string },
    ApiClientError,
    { token: string; newPassword: string; confirmNewPassword: string }
  >({
    mutationFn: (data) =>
      apiClient<{ message: string }>("/auth/reset-password", {
        method: "POST",
        body: JSON.stringify(data),
      }),
  });
}

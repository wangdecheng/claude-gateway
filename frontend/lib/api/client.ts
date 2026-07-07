const API_BASE = "/api";

interface FetchOptions extends RequestInit {
  params?: Record<string, string>;
}

interface ApiError {
  error: string;
  code: string;
  status: number;
}

export class ApiClientError extends Error {
  code: string;
  status: number;

  constructor({ error, code, status }: ApiError) {
    super(error);
    this.name = "ApiClientError";
    this.code = code;
    this.status = status;
  }
}

export async function apiClient<T = unknown>(
  path: string,
  options: FetchOptions = {}
): Promise<T> {
  const { params, ...fetchOptions } = options;

  let url = `${API_BASE}${path}`;
  if (params) {
    const searchParams = new URLSearchParams(params);
    url += `?${searchParams.toString()}`;
  }

  const response = await fetch(url, {
    credentials: "include",
    headers: {
      ...(fetchOptions.body && !(fetchOptions.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...fetchOptions.headers,
    },
    ...fetchOptions,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiClientError({
      error: body.error || "请求失败",
      code: body.code || "UNKNOWN_ERROR",
      status: response.status,
    });
  }

  // 204 No Content — nothing to parse, return undefined
  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}

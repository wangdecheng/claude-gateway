import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { ProviderEditForm } from "@/components/forms/ProviderEditForm";
import type { AdminProviderItem } from "@/lib/api/admin/providers";

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    );
  };
}

const MOCK_PROVIDER: AdminProviderItem = {
  id: 1,
  name: "anthropic",
  channelName: "主力线路",
  multiplier: 1.0,
  apiBaseUrl: "https://api.anthropic.com",
  authHeader: "Authorization",
  adapter: "anthropic-messages",
  keyCount: 2,
  activeKeyCount: 2,
  status: "active",
  createdAt: "2025-01-01T00:00:00Z",
};

describe("ProviderEditForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows both provider name and channel name in edit mode", () => {
    render(
      <ProviderEditForm
        open
        onOpenChange={vi.fn()}
        onSubmit={vi.fn()}
        provider={MOCK_PROVIDER}
        isSubmitting={false}
      />,
      { wrapper: createWrapper() }
    );

    const nameInput = screen.getByLabelText(/供应商名称/) as HTMLInputElement;
    const channelInput = screen.getByLabelText(/渠道名/) as HTMLInputElement;

    expect(nameInput).toBeInTheDocument();
    expect(nameInput.value).toBe("anthropic");
    expect(channelInput).toBeInTheDocument();
    expect(channelInput.value).toBe("主力线路");
  });

  it("renders provider name as read-only in edit mode", () => {
    render(
      <ProviderEditForm
        open
        onOpenChange={vi.fn()}
        onSubmit={vi.fn()}
        provider={MOCK_PROVIDER}
        isSubmitting={false}
      />,
      { wrapper: createWrapper() }
    );

    const nameInput = screen.getByLabelText(/供应商名称/) as HTMLInputElement;
    expect(nameInput.readOnly).toBe(true);
  });

  it("blocks editing of the provider name input in edit mode", () => {
    render(
      <ProviderEditForm
        open
        onOpenChange={vi.fn()}
        onSubmit={vi.fn()}
        provider={MOCK_PROVIDER}
        isSubmitting={false}
      />,
      { wrapper: createWrapper() }
    );

    const nameInput = screen.getByLabelText(/供应商名称/) as HTMLInputElement;
    // readOnly prevents user typing — guards against SK-binding breakage
    expect(nameInput.readOnly).toBe(true);
  });

  it("allows entering provider name in create mode", () => {
    render(
      <ProviderEditForm
        open
        onOpenChange={vi.fn()}
        onSubmit={vi.fn()}
        provider={null}
        isSubmitting={false}
      />,
      { wrapper: createWrapper() }
    );

    const nameInput = screen.getByLabelText(/供应商名称/) as HTMLInputElement;
    expect(nameInput.readOnly).toBe(false);
  });
});

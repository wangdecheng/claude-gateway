import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { ModelCard } from "@/components/data/ModelCard";
import type { ModelWithChannels } from "@/lib/api/models";

// Mock next/navigation
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
  }),
}));

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    );
  };
}

const MOCK_MODEL: ModelWithChannels = {
  id: 1,
  publicName: "claude-sonnet-4-6",
  description: "速度、性能与成本的平衡之选",
  inputPrice: 3_000,
  outputPrice: 15_000,
  channels: [
    { id: 1, providerName: "Anthropic", multiplier: 1.0, isDefault: true },
    { id: 2, providerName: "RightCodes", multiplier: 1.2, isDefault: false },
  ],
};

const MOCK_SINGLE_CHANNEL: ModelWithChannels = {
  id: 2,
  publicName: "gpt-4o-mini",
  description: "经济实惠的小型模型",
  inputPrice: 150,
  outputPrice: 600,
  channels: [
    { id: 3, providerName: "OpenAI", multiplier: 1.0, isDefault: true },
  ],
};

describe("ModelCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders model name and description", () => {
    render(<ModelCard model={MOCK_MODEL} />, { wrapper: createWrapper() });

    expect(screen.getByText("claude-sonnet-4-6")).toBeInTheDocument();
    expect(screen.getByText("速度、性能与成本的平衡之选")).toBeInTheDocument();
  });

  it("shows default channel in selector", () => {
    render(<ModelCard model={MOCK_MODEL} />, { wrapper: createWrapper() });

    const select = screen.getByRole("combobox");
    expect(select).toBeInTheDocument();
    // Default channel should be selected
    expect(screen.getByText(/Anthropic.*默认/)).toBeInTheDocument();
  });

  it("shows multi-channel badge when multiple channels exist", () => {
    render(<ModelCard model={MOCK_MODEL} />, { wrapper: createWrapper() });

    expect(screen.getByText("2 渠道")).toBeInTheDocument();
  });

  it("shows channel selector even for single channel", () => {
    render(<ModelCard model={MOCK_SINGLE_CHANNEL} />, { wrapper: createWrapper() });

    // Channel label should still appear
    expect(screen.getByText("渠道")).toBeInTheDocument();
    // But no multi-channel badge
    expect(screen.queryByText("2 渠道")).not.toBeInTheDocument();
    expect(screen.queryByText("1 渠道")).not.toBeInTheDocument();
  });

  it("displays estimated price for default channel", () => {
    render(<ModelCard model={MOCK_MODEL} />, { wrapper: createWrapper() });

    // Default: output 15000 micro-yuan → ¥0.015
    expect(screen.getByText("输出 ¥0.015")).toBeInTheDocument();
  });

  it("updates price display when channel changes", async () => {
    const user = userEvent.setup();
    render(<ModelCard model={MOCK_MODEL} />, { wrapper: createWrapper() });

    const select = screen.getByRole("combobox");
    await user.selectOptions(select, "2");

    // After switching to RightCodes (1.2x): output 15000 * 1.2 = 18000 micro-yuan → ¥0.018
    expect(screen.getByText("输出 ¥0.018")).toBeInTheDocument();
  });
});

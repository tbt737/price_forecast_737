import type { Provider } from "@/widgets/ai-chat/providers";

/** localStorage keys for the BYOK chat config — shared by the chat + Kinh Dịch expert. */
export const LS = {
  provider: "cqp.ai.provider",
  model: (p: Provider) => `cqp.ai.model.${p}`,
  key: (p: Provider) => `cqp.ai.key.${p}`,
};

export function loadLS(k: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(k);
  } catch {
    return null;
  }
}

export function saveLS(k: string, v: string) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(k, v);
  } catch {
    /* ignore quota/availability */
  }
}

// Static catalog hints shared by the Model tab cards (2026-10-15).
// The provider directory itself is server-driven: the Cloud provider card
// renders whatever GET /api/settings/llm-providers returns (7 vendors as of
// 2026-10-15, grok/muse included). These tables are only datalist suggestions
// and labels for surfaces whose endpoint returns no directory (ua-mode).

/** Default model hints per vendor for datalists — suggestions only; the inputs
 * accept any model name and the current model is always merged in. */
export const MODEL_SUGGESTIONS: Record<string, string[]> = {
  qwen: ["qwen3.8-flash", "qwen3.8-plus", "qwen3-max"],
  openai: ["gpt-5.2", "gpt-5.2-mini", "gpt-5.2-pro"],
  claude: ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5"],
  gemini: ["gemini-3-flash", "gemini-3-pro"],
  deepseek: ["deepseek-v4-flash", "deepseek-v4-pro"],
  grok: ["grok-4.7"],
  muse: ["muse-spark-1.3"],
};

/** The seven vendors the UA analysis mode can target (GET /api/settings/ua-mode
 * returns only the current triple, no catalog, so the labels live here). */
export const UA_PROVIDERS: Array<{ id: string; label: string }> = [
  { id: "qwen", label: "Qwen · Alibaba Bailian" },
  { id: "openai", label: "OpenAI" },
  { id: "claude", label: "Claude · Anthropic" },
  { id: "gemini", label: "Gemini · Google" },
  { id: "deepseek", label: "DeepSeek" },
  { id: "grok", label: "Grok · xAI" },
  { id: "muse", label: "Muse · Meta" },
];

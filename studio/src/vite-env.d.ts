/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "true" → features serve offline fixtures instead of calling companion-api. */
  readonly VITE_STUDIO_FIXTURES?: string;
  /** Optional absolute API origin; default is same-origin (/api via the Vite proxy or companion). */
  readonly VITE_STUDIO_API_BASE?: string;
}

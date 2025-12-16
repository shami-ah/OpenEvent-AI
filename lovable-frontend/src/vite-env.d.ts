/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_BACKEND_BASE: string
  readonly VITE_VERBALIZER_TONE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

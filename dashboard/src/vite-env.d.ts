/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Teacher code used to auto-login the dashboard in dev mode. */
  readonly VITE_DEV_AUTO_LOGIN_CODE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

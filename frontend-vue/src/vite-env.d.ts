/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string
  // 필요한 환경 변수들을 여기에 추가
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

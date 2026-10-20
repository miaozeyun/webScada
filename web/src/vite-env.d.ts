/// <reference types="vite/client" />

/** 构建期注入的产品版本号（vite.config define，取 package.json version） */
declare const __APP_VERSION__: string

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}

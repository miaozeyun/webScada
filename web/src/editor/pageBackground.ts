/**
 * 页面背景样式（唯一实现点）：编辑画布 CanvasStage 与运行态 RuntimeStage 共用。
 *
 * - 底色留在页面元素上；图片单独一层——直接给页面 opacity 会把组件内容一起变淡。
 * - 旧 doc 没有 imageFit/imageOpacity 时按 cover / 1 处理；image 为空串/null 视为无图。
 * - 图片 URL 进 url("…") 前转义引号与反斜杠，防外链里的特殊字符截断整条样式。
 */
import type { PageBackground } from '@/types/doc'

// token-exempt: doc 页面底色缺省（内容口径，非 UI chrome；与 RuntimeStage 既有兜底一致）
export const DEFAULT_PAGE_BACKGROUND = '#0b1220'

export function pageBaseStyle(bg?: PageBackground | null): { backgroundColor: string } {
  return { backgroundColor: bg?.color || DEFAULT_PAGE_BACKGROUND }
}

export function pageImageStyle(bg?: PageBackground | null): Record<string, string | number> | null {
  const image = (bg?.image ?? '').trim()
  if (!image) return null
  const escaped = image.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
  return {
    backgroundImage: `url("${escaped}")`,
    backgroundSize:
      bg?.imageFit === 'contain' ? 'contain' : bg?.imageFit === 'stretch' ? '100% 100%' : 'cover',
    backgroundPosition: 'center',
    backgroundRepeat: 'no-repeat',
    opacity: typeof bg?.imageOpacity === 'number' ? bg.imageOpacity : 1,
  }
}

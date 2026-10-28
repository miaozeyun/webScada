/**
 * 预置大屏背景（纯矢量，随 Web 构建产物发布）。
 * 放 public/bg/ 而非 assets/：URL 稳定（无构建哈希），doc 里存相对路径即可跨部署复用；
 * 不占 doc 体积，任意分辨率清晰，无第三方素材授权问题。
 */
export interface BackgroundPreset {
  id: string
  label: string
  url: string
}

export const BACKGROUND_PRESETS: BackgroundPreset[] = [
  { id: 'tech-grid', label: '科技网格', url: '/bg/tech-grid.svg' },
  { id: 'glow-center', label: '中心光晕', url: '/bg/glow-center.svg' },
  { id: 'dot-matrix', label: '点阵光带', url: '/bg/dot-matrix.svg' },
  { id: 'circuit', label: '电路走线', url: '/bg/circuit.svg' },
  { id: 'scanline', label: '斜纹扫描', url: '/bg/scanline.svg' },
]

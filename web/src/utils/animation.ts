/** 组件动画 class/style 计算（M4）：blink/flow/rotate 三类，编辑器与运行态共用。 */
import type { ComponentAnimations } from '@/types/doc'

export function animationOf(animations?: ComponentAnimations | null): {
  cls: string[]
  style: Record<string, string>
} {
  const cls: string[] = []
  const style: Record<string, string> = {}
  if (!animations) return { cls, style }

  if (animations.blink?.enabled) {
    cls.push('ws-anim-blink')
    style['--blink-ms'] = `${animations.blink.intervalMs}ms`
    style.animationDuration = `var(--blink-ms)`
  }
  if (animations.rotate?.enabled) {
    cls.push('ws-anim-rotate')
    style['--rotate-ms'] = `${animations.rotate.periodMs}ms`
    style.animationDuration = `var(--rotate-ms)`
    style.animationDirection = animations.rotate.clockwise === false ? 'reverse' : 'normal'
  }
  if (animations.flow?.enabled) {
    cls.push('ws-anim-flow')
    // speed 像素/秒 → 28px 周期时长
    const ms = Math.max(100, (28 / Math.max(1, animations.flow.speed)) * 1000)
    style['--flow-ms'] = `${ms}ms`
  }
  return { cls, style }
}

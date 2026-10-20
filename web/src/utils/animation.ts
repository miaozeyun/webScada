/** 组件动画 class/style 计算（M4/M7）：blink/flow/rotate/move 四类，编辑器与运行态共用。
 * M7：运行态 anim.* 绑定覆盖（rotateOn/rotatePeriod/flowOn/blinkOn）在此与静态配置合并
 * （优先级：绑定覆盖 > 静态 animations，符合 K12 口径）。 */
import type { ComponentAnimations } from '@/types/doc'

export interface AnimOverride {
  rotateOn?: boolean
  rotatePeriod?: number
  flowOn?: boolean
  blinkOn?: boolean
  moveOn?: boolean
}

export function animationOf(animations?: ComponentAnimations | null, override?: AnimOverride): {
  cls: string[]
  style: Record<string, string>
} {
  const cls: string[] = []
  const style: Record<string, string> = {}
  if (!animations && !override) return { cls, style }

  const blinkOn = override?.blinkOn ?? animations?.blink?.enabled ?? false
  if (blinkOn) {
    cls.push('ws-anim-blink')
    const ms = animations?.blink?.intervalMs ?? 1000
    style['--blink-ms'] = `${ms}ms`
    style.animationDuration = `var(--blink-ms)`
  }

  const flowOn = override?.flowOn ?? animations?.flow?.enabled ?? false
  if (flowOn) {
    cls.push('ws-anim-flow')
    // speed 像素/秒 → 28px 周期时长
    const speed = Math.max(1, animations?.flow?.speed ?? 40)
    const ms = Math.max(100, (28 / speed) * 1000)
    style['--flow-ms'] = `${ms}ms`
    style.animationDuration = `var(--flow-ms)`
  }

  const rotateOn = override?.rotateOn ?? animations?.rotate?.enabled ?? false
  if (rotateOn) {
    cls.push('ws-anim-rotate')
    // 绑定 rotatePeriod 覆盖静态周期（变量驱动转速）
    const ms = override?.rotatePeriod || animations?.rotate?.periodMs || 4000
    style['--rotate-ms'] = `${ms}ms`
    style.animationDuration = `var(--rotate-ms)`
    style.animationDirection = animations?.rotate?.clockwise === false ? 'reverse' : 'normal'
  }

  const moveOn = override?.moveOn ?? animations?.move?.enabled ?? false
  if (moveOn && animations?.move?.path) {
    cls.push('ws-anim-move')
    style['--move-path'] = `path('${animations.move.path.replace(/'/g, '')}')`
    style['--move-ms'] = `${animations.move.periodMs}ms`
    style['--move-dir'] = animations.move.mode === 'pingpong' ? 'alternate' : 'normal'
  }
  return { cls, style }
}

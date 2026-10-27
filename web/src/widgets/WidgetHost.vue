<script setup lang="ts">
/**
 * 组件统一挂载点：应用 ComponentStyle 并分发到 registry 渲染器。
 * 几何定位（x/y/w/h/rotate）由外层容器承担；本组件只负责内容与外观。
 * 运行态绑定求值装配（K12 优先级唯一实现点）：runtime.overrides 中的
 * props/style 覆盖编辑值（编辑态 runtime 未启动，零影响）。
 * M8：S2 报警态渲染（02 §2.12 优先级契约的唯一实现点）——
 * 报警态覆盖组件填充色为 levelColors[level] 并叠加闪烁，恢复后自动回落 S1/S0；
 * 多条报警取最高 level（critical > warn > info），未知 level 用 --ws-alert 兜底色；
 * 显隐绑定（visibility）优先于报警，由外层 PreviewNode 按覆盖层判定，本组件不突破显隐。
 */
import { computed } from 'vue'
import type { ComponentNode, ComponentStyle } from '@/types/doc'
import { useRuntimeStore } from '@/runtime/store'
import { useEditorStore } from '@/stores/editor'
import { registry } from './registry'
import { resolveLevelColors } from '@/api/alarms'

const props = defineProps<{ node: ComponentNode }>()

const runtime = useRuntimeStore()
const editor = useEditorStore()
const meta = computed(() => registry.get(props.node.type))

/** 运行态覆盖（绑定求值结果），编辑态恒为 undefined */
const ov = computed(() => runtime.overrides.get(props.node.id))

const mergedProps = computed<Record<string, unknown>>(() => ({
  ...props.node.props,
  ...ov.value?.props,
}))

// ---- S2 报警态（M8）：事件流兼容前端引擎事件与 M8 服务端帧映射两种来源 ----

/** 报警事件宽松形态：前端引擎 AlarmEvent 之外，兼容服务端帧携带的 status/alarmId/variableKey 等扩展 */
interface AlarmEventLike {
  id: string | number
  type?: 'active' | 'recovered'
  level?: string
  status?: string
  variableKey?: string
  variableId?: string
  ruleId?: string
  alarmId?: number
  ackedAt?: number
}

/** 未知 level 的报警强调兜底色：输出令牌引用（内联 style 绘制时解析、随换肤联动，
 *  非默认主题下不再落回 electric 主题的 #c2410c 造成错色） */

const LEVEL_RANK: Record<string, number> = { critical: 3, warn: 2, info: 1 }

/** 活动中判定：服务端状态机（triggered/acked 未恢复）或前端引擎事件（type=active） */
function isAlarmActive(e: AlarmEventLike): boolean {
  if (e.status) return e.status === 'triggered' || e.status === 'acked'
  return e.type === 'active'
}

/** 事件 → 变量 id：优先显式字段；variableKey 经运行时索引反查；仅 ruleId 时经编辑器 doc 规则反查 */
function resolveAlarmVarId(e: AlarmEventLike): string | undefined {
  if (e.variableId) return e.variableId
  if (e.variableKey) {
    const id = runtime.varByKey.get(e.variableKey)
    if (id) return id
  }
  const ruleId = e.ruleId ?? (typeof e.id === 'string' ? e.id : undefined)
  return editor.doc?.alarmRules.find((r) => r.id === ruleId)?.variableId
}

const levelColors = computed(() => resolveLevelColors(editor.doc?.settings.alarm.levelColors))

/** 当前组件绑定变量上的最高级别活动报警（null=无报警，回落 S1/S0 呈现） */
const alarm = computed<{ hit: boolean; level: string; color: string } | null>(() => {
  const boundIds = new Set((props.node.bindings ?? []).map((b) => b.variableId))
  if (boundIds.size === 0) return null
  let hit = false
  let bestRank = -1
  let bestLevel = ''
  for (const ev of runtime.activeAlarms.values()) {
    const e = ev as unknown as AlarmEventLike
    if (!isAlarmActive(e)) continue
    const varId = resolveAlarmVarId(e)
    if (!varId || !boundIds.has(varId)) continue
    hit = true
    const rank = LEVEL_RANK[e.level ?? ''] ?? -1
    if (rank > bestRank) {
      bestRank = rank
      bestLevel = e.level ?? ''
    }
  }
  if (!hit) return null
  const known = bestLevel === 'info' || bestLevel === 'warn' || bestLevel === 'critical'
  return {
    hit: true,
    level: bestLevel,
    // 已知级别取工程配置色；未知级别灰显不合适（报警须强调），统一安全橙兜底
    color: known ? levelColors.value[bestLevel as 'info' | 'warn' | 'critical'] : 'var(--ws-alert)',
  }
})

/** 闪烁周期：接管组件 animations.blink 通道参数；未配置按 1s */
const blinkMs = computed(() => {
  const ms = props.node.animations?.blink?.intervalMs
  return typeof ms === 'number' && ms > 0 ? ms : 1000
})

// ---- 质量位灰显（M8 契约 03 §2.10 q∈good|stale|bad）----
/** 绑定变量处于 stale（断数源超时，值保留）/ bad（数据不可信）→ 叠灰标记；
 *  返回最差质量态（bad > stale），null=正常。S2 报警优先，避免双态叠加混淆。
 *  实现收敛于 WidgetHost（K12 唯一装配点）：PreviewNode 的内容渲染经此组件，全部运行态节点覆盖。 */
const degraded = computed<'bad' | 'stale' | null>(() => {
  if (alarm.value) return null
  let worst: 'bad' | 'stale' | null = null
  for (const b of props.node.bindings ?? []) {
    const q = runtime.degradedVars.get(b.variableId)
    if (q === 'bad') return 'bad'
    if (q === 'stale') worst = 'stale'
  }
  return worst
})

const degradedTip = computed(() =>
  degraded.value === 'bad'
    ? '数据质量异常（bad）：数值不可信'
    : degraded.value === 'stale'
      ? '数据超时（stale）：显示为最后有效值'
      : undefined,
)

const contentStyle = computed(() => {
  // opacity 为运行态绑定目标（协议 ComponentStyle 之外的运行通道）
  const s: ComponentStyle & { opacity?: number } = {
    ...(props.node.style ?? {}),
    ...(ov.value?.style as (ComponentStyle & { opacity?: number }) | undefined),
  }
  // S2 报警态覆盖填充色（优先级 S2 > S1 绑定求值 > S0 静态样式，02 §2.12）
  const fill = alarm.value ? alarm.value.color : s.fill
  const style: Record<string, string | undefined> = {
    // 圆形等自绘形状不吃宿主矩形背景（否则 fill 被画成方块），改由组件经 --ws-fill 取色
    background: props.node.type === 'circle' ? undefined : (fill ?? undefined),
    color: s.color ?? undefined,
    fontSize: s.fontSize !== undefined ? `${s.fontSize}px` : undefined,
    fontWeight: s.fontWeight !== undefined ? String(s.fontWeight) : undefined,
    textAlign: s.textAlign ?? undefined,
    borderRadius: s.borderRadius !== undefined ? `${s.borderRadius}px` : undefined,
    border: s.stroke ? `${s.strokeWidth ?? 1}px solid ${s.stroke}` : undefined,
    opacity: s.opacity !== undefined ? String(s.opacity) : undefined,
    // 设备 SVG 组件经 CSS 变量取色（.dev-svg { color: var(--dev-color, 默认) }）
    '--dev-color': s.color ?? undefined,
    // 自绘形状的填充色（circle 用 border-radius 裁切，避免矩形底铺满组件框）
    '--ws-fill': fill ?? undefined,
    // 报警闪烁周期（组件 blink.intervalMs 接管）
    '--ws-alarm-blink-ms': `${blinkMs.value}ms`,
  }
  // 无覆盖时返回空对象，避免空 style 属性
  return Object.values(style).some((v) => v !== undefined) ? style : {}
})
</script>

<template>
  <div
    class="widget-host"
    :class="{ 'alarm-blink': alarm !== null, 'data-degraded': degraded !== null }"
    :style="contentStyle"
    :title="degradedTip"
  >
    <component :is="meta!.renderer" v-if="meta && node.type !== 'group'" :node-props="mergedProps" />
    <!-- group 由外层递归渲染 children，无自身渲染器 -->
  </div>
</template>

<style scoped>
.widget-host {
  width: 100%;
  height: 100%;
  overflow: hidden;
  box-sizing: border-box;
}

/* S2 报警闪烁：叠加于报警填充色之上（keyframes wsBlink 为 theme.css 全局定义），
   报警恢复后 class 随之移除，自动回落 S1/S0 呈现 */
.widget-host.alarm-blink {
  animation: wsBlink var(--ws-alarm-blink-ms, 1s) steps(2, jump-none) infinite;
}

/* 质量位灰显（03 §2.10）：stale/bad 滤镜去色 + 半透明叠灰（theme.css 灰阶口径），
   恢复 good 后 class 移除自动复原；与 S2 报警互斥（报警优先不灰显） */
.widget-host.data-degraded {
  filter: grayscale(1);
  opacity: 0.45;
}
</style>

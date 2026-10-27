<script setup lang="ts">
/** 状态组件（M7，对齐 业界主流组态「状态」）：变量值 → 枚举文本 + 前景/背景色。
 * states 为 JSON 数组 [{value, text, color, background}]；绑 props.value 匹配。 */
import { computed } from 'vue'

interface StateItem {
  value: string | number | boolean
  text: string
  color?: string
  background?: string
}

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const states = computed<StateItem[]>(() => {
  try {
    const arr = typeof props.nodeProps.states === 'string' ? JSON.parse(props.nodeProps.states) : props.nodeProps.states
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
})

const current = computed<StateItem | null>(() => {
  const v = props.nodeProps.value
  if (v === undefined || v === null) return null
  return states.value.find((s) => String(s.value) === String(v)) ?? null
})
</script>

<template>
  <div
    class="state-text"
    :style="{
      color: current?.color ?? 'inherit',
      background: current?.background ?? 'transparent',
    }"
  >
    {{ current?.text ?? String(nodeProps.value ?? nodeProps.defaultText ?? '--') }}
  </div>
</template>

<style scoped>
.state-text {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.05em;
  font-weight: 600;
  border-radius: 4px;
  overflow: hidden;
  white-space: nowrap;
  transition: color var(--ws-duration-base) var(--ws-ease), background var(--ws-duration-base) var(--ws-ease);
}
</style>

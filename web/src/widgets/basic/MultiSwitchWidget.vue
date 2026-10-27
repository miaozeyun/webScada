<script setup lang="ts">
/** 多档开关（M7 反控，对齐 业界主流组态「多档开关」）：levels JSON [{value,label}]，
 * 当前档 = 变量值匹配；点档位写值。编辑态静态展示且不可操作。 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRuntimeApi } from '@/runtime/actions'

interface Level {
  value: string | number | boolean
  label: string
}

const props = defineProps<{ nodeProps: Record<string, unknown> }>()
const api = useRuntimeApi()
const busy = ref(false)

const variableId = computed(() => String(props.nodeProps.variableId ?? ''))

const levels = computed<Level[]>(() => {
  try {
    const arr = typeof props.nodeProps.levels === 'string' ? JSON.parse(props.nodeProps.levels) : props.nodeProps.levels
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
})

const activeIdx = computed(() => {
  if (!api || !variableId.value) return -1
  const v = api.valueOf(variableId.value)
  const idx = levels.value.findIndex((l) => String(l.value) === String(v))
  return idx
})

async function pick(level: Level, ev?: Event): Promise<void> {
  if (!api || !variableId.value || busy.value) return
  ev?.stopPropagation() // 仅运行态拦截（编辑态放行给画布选中）
  busy.value = true
  try {
    await api.write(variableId.value, level.value)
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="multi-switch" :class="{ disabled: !api || !variableId }">
    <button
      v-for="(l, i) in levels"
      :key="i"
      type="button"
      class="level"
      :class="{ active: i === activeIdx }"
      @click="pick(l, $event)"
    >
      {{ l.label }}
    </button>
  </div>
</template>

<style scoped>
.multi-switch {
  width: 100%;
  height: 100%;
  display: flex;
  gap: 4px;
  align-items: stretch;
}

.disabled .level {
  cursor: not-allowed;
}

.level {
  flex: 1;
  min-width: 0;
  border: 1px solid rgba(148, 163, 184, 0.5);
  background: rgba(71, 85, 105, 0.35);
  color: inherit;
  font-size: 0.85em;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: background var(--ws-duration-base) var(--ws-ease), border-color var(--ws-duration-base) var(--ws-ease);
}

.level.active {
  background: #0b7285;
  border-color: #0b7285;
  color: #fff;
  font-weight: 600;
}

.level:not(.active):hover {
  background: rgba(11, 114, 133, 0.25);
}
</style>

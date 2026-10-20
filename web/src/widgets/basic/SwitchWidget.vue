<script setup lang="ts">
/** 开关（M7 反控，对齐 BY「开关」）：读写一体的变量控制组件。
 * 显示态 = runtime.values[variableId] 与 onValue 宽松相等；点击写 on/off 值（经写中心校验 writable）。
 * 编辑态（无 RuntimeApi provider）显示 off 态且不可操作。 */
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRuntimeApi } from '@/runtime/actions'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()
const api = useRuntimeApi()

const variableId = computed(() => String(props.nodeProps.variableId ?? ''))
const onValue = computed(() => (props.nodeProps.onValue ?? 1) as string | number | boolean)
const offValue = computed(() => (props.nodeProps.offValue ?? 0) as string | number | boolean)
const busy = ref(false)

function looseEq(a: unknown, b: unknown): boolean {
  if (a === b) return true
  const an = typeof a === 'number' || typeof a === 'boolean'
  const bn = typeof b === 'number' || typeof b === 'boolean'
  if (an && bn) return Number(a) === Number(b)
  return String(a) === String(b)
}

const on = computed(() => {
  if (!api || !variableId.value) return false
  return looseEq(api.valueOf(variableId.value), onValue.value)
})

async function toggle(ev?: Event): Promise<void> {
  if (!api || !variableId.value || busy.value) return
  ev?.stopPropagation() // 仅运行态拦截（编辑态放行给画布选中）
  if (props.nodeProps.confirm === true) {
    try {
      await ElMessageBox.confirm(`确定写入 ${on.value ? offValue.value : onValue.value} 到 ${variableId.value}？`, '反控确认', { type: 'warning' })
    } catch {
      return
    }
  }
  busy.value = true
  try {
    await api.write(variableId.value, on.value ? offValue.value : onValue.value)
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="ctrl-switch" :class="{ on, disabled: !api || !variableId, busy }" @click="toggle">
    <span class="knob" />
    <span v-if="nodeProps.label" class="label">{{ nodeProps.label }}</span>
  </div>
</template>

<style scoped>
.ctrl-switch {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
}

.ctrl-switch.disabled {
  cursor: not-allowed;
  opacity: 0.8;
}

.ctrl-switch.busy {
  pointer-events: none;
}

/* 轨道 + 滑块（自带视觉，不吃 --dev-color） */
.ctrl-switch {
  position: relative;
}

.ctrl-switch::before {
  content: '';
  width: 2.2em;
  height: 1.15em;
  border-radius: 1em;
  background: #909399;
  transition: background 0.25s;
  flex-shrink: 0;
}

.knob {
  position: absolute;
  left: 0.12em;
  width: 0.95em;
  height: 0.95em;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
  transition: transform 0.25s;
  transform: translateY(0.1em);
}

.on::before {
  background: #67c23a;
}

.on .knob {
  transform: translateX(1.1em) translateY(0.1em);
}

.label {
  font-size: 0.9em;
  color: inherit;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>

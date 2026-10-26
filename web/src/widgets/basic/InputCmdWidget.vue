<script setup lang="ts">
/** 输入框指令（M7 反控，对齐 业界主流组态「提交画面输入框指令」）：输入值 → 提交按钮 → 写变量。 */
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRuntimeApi } from '@/runtime/actions'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()
const api = useRuntimeApi()
const input = ref('')
const busy = ref(false)

async function submit(ev?: Event): Promise<void> {
  const variableId = String(props.nodeProps.variableId ?? '')
  if (!api || !variableId || busy.value) return
  ev?.stopPropagation() // 仅运行态拦截（编辑态放行给画布选中）
  if (input.value === '') {
    ElMessage.warning('请输入设定值')
    return
  }
  busy.value = true
  try {
    // 数字变量转数值写入；布尔识别 true/false；其余按字符串
    let value: number | boolean | string = input.value
    if (input.value !== '' && !Number.isNaN(Number(input.value))) value = Number(input.value)
    else if (input.value === 'true' || input.value === 'false') value = input.value === 'true'
    await api.write(variableId, value)
    if (props.nodeProps.clearAfter !== false) input.value = ''
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="input-cmd" :class="{ disabled: !api || !nodeProps.variableId }">
    <el-input
      v-model="input"
      size="small"
      :placeholder="String(nodeProps.placeholder ?? '输入设定值')"
      :disabled="!api || !nodeProps.variableId"
      @click="api && $event.stopPropagation()"
      @keyup.enter="submit"
    >
      <template v-if="nodeProps.unit" #append>{{ nodeProps.unit }}</template>
    </el-input>
    <el-button size="small" type="primary" :loading="busy" @click="submit">
      {{ nodeProps.buttonText ?? '提交' }}
    </el-button>
  </div>
</template>

<style scoped>
.input-cmd {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  gap: 6px;
}

.input-cmd .el-input {
  flex: 1;
  min-width: 0;
}
</style>

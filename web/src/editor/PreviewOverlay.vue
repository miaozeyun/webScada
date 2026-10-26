<script setup lang="ts">
/**
 * 编辑器内运行态预览（M4）：RuntimeStage 薄壳。
 * Esc 退出；预览期间在 document capture 阶段拦截按键，避免编辑器快捷键误改 doc。
 * 2026-10-26：预览默认只读（writable=false）——预览连的是真实 WS，服务端只校验角色与
 * 变量 writable，误点控制组件会写真实设备。反控调试走仿真台/专用测试通道。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useEditorStore } from '@/stores/editor'
import RuntimeStage from './RuntimeStage.vue'

const emit = defineEmits<{ (e: 'close'): void }>()

const editor = useEditorStore()

/** 默认只读；用户点「允许控制」后以 writable=true 重新挂载（provideRuntime 在 setup 时固定） */
const writable = ref(false)

/** capture 拦截全部按键：Esc 关闭，其余阻断（编辑器快捷键在预览态不生效） */
function onKeydown(e: KeyboardEvent): void {
  e.stopImmediatePropagation()
  if (e.key === 'Escape') emit('close')
}

onMounted(() => {
  editor.clearSelection()
  editor.setEditing('')
  document.addEventListener('keydown', onKeydown, true)
})
onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown, true))
</script>

<template>
  <RuntimeStage
    v-if="editor.doc"
    :key="writable ? 'write' : 'readonly'"
    :doc="editor.doc"
    :title="`${editor.projectName} · 预览`"
    :report-project-id="editor.projectId"
    :writable="writable"
    closable
    @close="emit('close')"
    @enable-write="writable = true"
  />
</template>

<script setup lang="ts">
/**
 * 编辑器内运行态预览（M4）：RuntimeStage 薄壳。
 * Esc 退出；预览期间在 document capture 阶段拦截按键，避免编辑器快捷键误改 doc。
 */
import { onBeforeUnmount, onMounted } from 'vue'
import { useEditorStore } from '@/stores/editor'
import RuntimeStage from './RuntimeStage.vue'

const emit = defineEmits<{ (e: 'close'): void }>()

const editor = useEditorStore()

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
    :doc="editor.doc"
    :title="`${editor.projectName} · 预览`"
    :report-project-id="editor.projectId"
    closable
    @close="emit('close')"
  />
</template>

<script setup lang="ts">
/**
 * 我的图元缩略渲染（M9 批次2）：节点集静态平铺（无引擎），按包围盒等比缩进盒内。
 * 节点已展平（无 group）；chart 类静态渲染即占位视觉。
 */
import { computed } from 'vue'
import type { ComponentNode } from '@/types/doc'
import { registry } from '@/widgets/registry'

const props = defineProps<{ nodes: ComponentNode[] }>()

const layout = computed(() => {
  if (props.nodes.length === 0) return null
  const maxX = Math.max(...props.nodes.map((n) => n.x + n.w))
  const maxY = Math.max(...props.nodes.map((n) => n.y + n.h))
  const s = Math.min(64 / Math.max(maxX, 1), 54 / Math.max(maxY, 1))
  return { w: maxX, h: maxY, s }
})

const items = computed(() =>
  props.nodes
    .map((n) => ({ node: n, meta: registry.get(n.type) }))
    .filter((i) => i.meta !== undefined)
    .sort((a, b) => a.node.z - b.node.z),
)
</script>

<template>
  <span v-if="layout" class="my-sym-thumb" :style="{ width: `${layout.w * layout.s}px`, height: `${layout.h * layout.s}px` }">
    <span
      v-for="it in items"
      :key="it.node.id"
      class="cell"
      :style="{
        left: `${it.node.x * layout.s}px`,
        top: `${it.node.y * layout.s}px`,
        width: `${it.node.w * layout.s}px`,
        height: `${it.node.h * layout.s}px`,
      }"
    >
      <component :is="it.meta!.renderer" :node-props="it.node.props" :style="{ color: it.node.style?.color ?? undefined }" />
    </span>
  </span>
</template>

<style scoped>
.my-sym-thumb {
  position: relative;
  display: inline-block;
  overflow: hidden;
  padding: 4px;
  border: 1px solid var(--ws-steel-2);
  border-radius: var(--ws-radius);
  background: var(--ws-steel-0);
  color: var(--ws-text-2);
  flex-shrink: 0;
}

.cell {
  position: absolute;
  overflow: hidden;
  display: flex;
}

.cell > * {
  width: 100%;
  height: 100%;
}
</style>

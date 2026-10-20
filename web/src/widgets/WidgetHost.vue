<script setup lang="ts">
/**
 * 组件统一挂载点：应用 ComponentStyle 并分发到 registry 渲染器。
 * 几何定位（x/y/w/h/rotate）由外层容器承担；本组件只负责内容与外观。
 * M4 起：绑定求值装配与报警态叠加（K12 优先级唯一实现点）在此扩展。
 */
import { computed } from 'vue'
import type { ComponentNode } from '@/types/doc'
import { registry } from './registry'

const props = defineProps<{ node: ComponentNode }>()

const meta = computed(() => registry.get(props.node.type))

const contentStyle = computed(() => {
  const s = props.node.style
  if (!s) return {}
  return {
    background: s.fill ?? undefined,
    color: s.color ?? undefined,
    fontSize: s.fontSize !== undefined ? `${s.fontSize}px` : undefined,
    fontWeight: s.fontWeight !== undefined ? String(s.fontWeight) : undefined,
    textAlign: s.textAlign ?? undefined,
    borderRadius: s.borderRadius !== undefined ? `${s.borderRadius}px` : undefined,
    border: s.stroke ? `${s.strokeWidth ?? 1}px solid ${s.stroke}` : undefined,
  }
})
</script>

<template>
  <div class="widget-host" :style="contentStyle">
    <component :is="meta!.renderer" v-if="meta && node.type !== 'group'" :node-props="node.props" />
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
</style>

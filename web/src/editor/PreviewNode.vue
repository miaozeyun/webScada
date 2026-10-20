<script setup lang="ts">
/** 预览节点（只读递归）：几何/旋转/透明度定位，内容渲染委托 WidgetHost，组递归 children。
 * 运行态：消费 override 的 visible/opacity（props/style 由 WidgetHost 装配，K12）。 */
import { computed } from 'vue'
import type { ComponentNode } from '@/types/doc'
import { useRuntimeStore } from '@/runtime/store'
import { animationOf } from '@/utils/animation'
import WidgetHost from '@/widgets/WidgetHost.vue'

const props = defineProps<{ node: ComponentNode }>()

const runtime = useRuntimeStore()
const ov = computed(() => runtime.overrides.get(props.node.id))
const anim = computed(() => animationOf(props.node.animations))

const visible = computed(() => props.node.visible !== false && ov.value?.visible !== false)

const boxStyle = computed(() => ({
  left: `${props.node.x}px`,
  top: `${props.node.y}px`,
  width: `${props.node.w}px`,
  height: `${props.node.h}px`,
  transform: props.node.rotate ? `rotate(${props.node.rotate}deg)` : undefined,
  zIndex: props.node.z,
  opacity: (ov.value?.style?.opacity as number | undefined) ?? props.node.opacity ?? 1,
  ...anim.value.style,
}))
</script>

<template>
  <div v-if="visible" class="preview-node" :class="anim.cls" :style="boxStyle">
    <WidgetHost :node="node" />
    <PreviewNode v-for="child in node.children ?? []" :key="child.id" :node="child" />
  </div>
</template>

<style scoped>
.preview-node {
  position: absolute;
  box-sizing: border-box;
  user-select: none;
  -webkit-user-select: none;
  -webkit-user-drag: none;
}
</style>

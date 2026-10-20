<script setup lang="ts">
/**
 * 组件统一挂载点：应用 ComponentStyle 并分发到 registry 渲染器。
 * 几何定位（x/y/w/h/rotate）由外层容器承担；本组件只负责内容与外观。
 * 运行态绑定求值装配（K12 优先级唯一实现点）：runtime.overrides 中的
 * props/style 覆盖编辑值（编辑态 runtime 未启动，零影响）。
 */
import { computed } from 'vue'
import type { ComponentNode, ComponentStyle } from '@/types/doc'
import { useRuntimeStore } from '@/runtime/store'
import { registry } from './registry'

const props = defineProps<{ node: ComponentNode }>()

const runtime = useRuntimeStore()
const meta = computed(() => registry.get(props.node.type))

/** 运行态覆盖（绑定求值结果），编辑态恒为 undefined */
const ov = computed(() => runtime.overrides.get(props.node.id))

const mergedProps = computed<Record<string, unknown>>(() => ({
  ...props.node.props,
  ...ov.value?.props,
}))

const contentStyle = computed(() => {
  // opacity 为运行态绑定目标（协议 ComponentStyle 之外的运行通道）
  const s: ComponentStyle & { opacity?: number } = {
    ...(props.node.style ?? {}),
    ...(ov.value?.style as (ComponentStyle & { opacity?: number }) | undefined),
  }
  const style: Record<string, string | undefined> = {
    // 圆形等自绘形状不吃宿主矩形背景（否则 fill 被画成方块），改由组件经 --ws-fill 取色
    background: props.node.type === 'circle' ? undefined : (s.fill ?? undefined),
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
    '--ws-fill': s.fill ?? undefined,
  }
  // 无覆盖时返回空对象，避免空 style 属性
  return Object.values(style).some((v) => v !== undefined) ? style : {}
})
</script>

<template>
  <div class="widget-host" :style="contentStyle">
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
</style>

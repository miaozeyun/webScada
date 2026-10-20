<script setup lang="ts">
/** 预览节点（只读递归）：几何/旋转/透明度定位，内容渲染委托 WidgetHost，组递归 children。
 * 运行态（M7 扩展）：
 * - 消费 override 的 visible/opacity/anim（props/style 由 WidgetHost 装配，K12）
 * - 事件与行为：click/dblclick/contextmenu → RUNTIME_EVENTS 注入的执行器
 * - 悬停信息：tooltip 模板 {变量key} 实时替换
 * - 弹框组：popup 配置的 group 运行态默认隐藏，override.visible 控制显隐；显示时带遮罩 */
import { computed } from 'vue'
import type { ComponentNode, EventTrigger } from '@/types/doc'
import { useRuntimeStore } from '@/runtime/store'
import { useNodeEventRunner } from '@/runtime/actions'
import { animationOf } from '@/utils/animation'
import WidgetHost from '@/widgets/WidgetHost.vue'

const props = defineProps<{ node: ComponentNode }>()

const runtime = useRuntimeStore()
const runEvents = useNodeEventRunner()

const ov = computed(() => runtime.overrides.get(props.node.id))
const anim = computed(() => animationOf(props.node.animations, ov.value?.anim))

const isPopup = computed(() => !!props.node.popup)

/** 显隐优先级（K12 口径）：弹框组运行态由 override 独占（默认隐藏）；
 *  普通组件 override 存在即生效（可覆盖静态 visible:false，供事件 toggleVisible 使用） */
const visible = computed(() => {
  if (isPopup.value && runtime.running) return ov.value?.visible === true
  const forced = ov.value?.visible
  if (forced !== undefined) return forced
  return props.node.visible !== false
})

const boxStyle = computed(() => ({
  left: `${props.node.x}px`,
  top: `${props.node.y}px`,
  width: `${props.node.w}px`,
  height: `${props.node.h}px`,
  transform: props.node.rotate ? `rotate(${props.node.rotate}deg)` : undefined,
  // 弹框组运行态抬到普通内容之上（9000 段），遮罩随之覆盖整页
  zIndex: isPopup.value && runtime.running ? 9000 + props.node.z : props.node.z,
  opacity: (ov.value?.style?.opacity as number | undefined) ?? props.node.opacity ?? 1,
  ...anim.value.style,
}))

// ---- 事件与行为 ----
const hasEvent = (trigger: EventTrigger): boolean =>
  !!props.node.events?.some((e) => e.trigger === trigger)

function fire(trigger: EventTrigger, ev?: Event): void {
  if (!runEvents || !hasEvent(trigger)) return
  ev?.stopPropagation()
  if (trigger === 'contextmenu') ev?.preventDefault()
  runEvents(props.node, trigger)
}

// ---- 悬停信息：模板 {key} → 变量当前值 ----
const tooltipEnabled = computed(() => runtime.running && props.node.tooltip?.enabled === true && !!props.node.tooltip?.template)

const tooltipContent = computed(() => {
  const tpl = props.node.tooltip?.template ?? ''
  return tpl.replace(/\{([A-Za-z0-9_.\-]+)\}/g, (_, key: string) => {
    const id = runtime.varByKey.get(key)
    if (!id) return key
    const v = runtime.values.get(id)
    return v === undefined ? '--' : String(v)
  })
})

// ---- 弹框遮罩（dialog 半透明 / menu 透明仅拦截外点关闭） ----
function closePopup(): void {
  if (props.node.popup) runtime.overrides.set(props.node.id, { ...(ov.value ?? {}), visible: false })
}
</script>

<template>
  <el-tooltip
    :disabled="!tooltipEnabled"
    :content="tooltipContent"
    placement="top"
    :show-after="300"
  >
    <div
      v-if="visible"
      class="preview-node"
      :class="[anim.cls, { 'ws-popup-open': isPopup && runtime.running }]"
      :style="boxStyle"
      @click="fire('click', $event)"
      @dblclick="fire('dblclick', $event)"
      @contextmenu="fire('contextmenu', $event)"
    >
      <!-- 弹框遮罩：fixed 于最近 transformed 祖先（stage-page），点击关闭。
           z-index:-1（父级已建栈上下文）确保永远在弹框内容之下，否则会吞掉按钮点击 -->
      <div
        v-if="isPopup && runtime.running"
        class="ws-popup-mask"
        :class="{ menu: node.popup!.style === 'menu' }"
        @click.stop="closePopup"
        @contextmenu.prevent.stop="closePopup"
      />
      <div v-if="isPopup && node.popup!.title" class="popup-title">{{ node.popup!.title }}</div>
      <WidgetHost :node="node" />
      <PreviewNode v-for="child in node.children ?? []" :key="child.id" :node="child" />
    </div>
  </el-tooltip>
</template>

<style scoped>
.preview-node {
  position: absolute;
  box-sizing: border-box;
  user-select: none;
  -webkit-user-select: none;
  -webkit-drag: none;
}

/* 弹框组运行态：内容层抬到遮罩之上并自带面板外观 */
.ws-popup-open {
  z-index: 9000;
}

.popup-title {
  position: absolute;
  top: -30px;
  left: 0;
  color: #f1f5f9;
  font-size: 14px;
  font-weight: 600;
  white-space: nowrap;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
  pointer-events: none;
}
</style>

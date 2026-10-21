<script setup lang="ts">
/**
 * 行业图元（M9 批次1）：渲染 assets/symbols 资产库的自绘 SVG。
 * 颜色走 --dev-color（style.color / color 绑定 / 报警态驱动），与设备类组件同一取色通道。
 * SVG 为构建期内置自绘资产（v-html 无外部输入面），symbolId 缺失时灰显占位。
 */
import { computed } from 'vue'
import { getSymbol } from '@/assets/symbols'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const asset = computed(() => getSymbol(String(props.nodeProps.symbolId ?? '')))
</script>

<template>
  <div v-if="asset" class="symbol-svg" v-html="asset.svg" />
  <div v-else class="symbol-missing">图元缺失</div>
</template>

<style scoped>
.symbol-svg {
  width: 100%;
  height: 100%;
  color: var(--dev-color, #909399);
}

.symbol-svg :deep(svg) {
  width: 100%;
  height: 100%;
  display: block;
}

.symbol-missing {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed var(--ws-steel-3);
  border-radius: var(--ws-radius);
  font-size: 12px;
  color: var(--ws-text-3);
  background: var(--ws-panel);
}
</style>

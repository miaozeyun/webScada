<script setup lang="ts">
/** 按钮（参照 visual-drag-demo VButton）：文字与配色（fill=背景 / color=文字）可经属性面板调整。 */
import { computed } from 'vue'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const text = computed(() => String(props.nodeProps.text ?? '按钮'))
</script>

<template>
  <button class="v-button" type="button">{{ text }}</button>
</template>

<style scoped>
.v-button {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 4px;
  background: #409eff;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  /* WidgetHost inline（fill/color）覆盖默认配色 */
}
</style>

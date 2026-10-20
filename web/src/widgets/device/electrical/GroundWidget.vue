<script setup lang="ts">
/** 接地（M7 二次接线）：竖线 + 三道递减横线。 */
</script>

<template>
  <svg class="dev-svg ele-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
    <line x1="50" y1="0" x2="50" y2="55" stroke="currentColor" stroke-width="5" />
    <line x1="30" y1="55" x2="70" y2="55" stroke="currentColor" stroke-width="5" />
    <line x1="37" y1="70" x2="63" y2="70" stroke="currentColor" stroke-width="5" />
    <line x1="44" y1="85" x2="56" y2="85" stroke="currentColor" stroke-width="5" />
  </svg>
</template>

<style scoped>
.dev-svg {
  width: 100%;
  height: 100%;
  display: block;
  color: var(--dev-color, #909399);
}
</style>

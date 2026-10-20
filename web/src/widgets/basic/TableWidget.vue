<script setup lang="ts">
/** 简易表格：data 为二维数组 JSON（首行表头），参照 visual-drag-demo VTable 的属性形态。 */
import { computed } from 'vue'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const rows = computed<string[][]>(() => {
  try {
    const parsed = JSON.parse(String(props.nodeProps.data ?? '[]'))
    if (!Array.isArray(parsed)) return []
    return parsed.map((r) => (Array.isArray(r) ? r.map((c) => String(c)) : [String(r)]))
  } catch {
    return []
  }
})
</script>

<template>
  <div class="table-widget">
    <table>
      <thead v-if="rows.length">
        <tr><th v-for="(c, i) in rows[0]" :key="i">{{ c }}</th></tr>
      </thead>
      <tbody>
        <tr v-for="(row, ri) in rows.slice(1)" :key="ri">
          <td v-for="(c, ci) in row" :key="ci">{{ c }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.table-widget {
  width: 100%;
  height: 100%;
  overflow: auto;
  box-sizing: border-box;
  background: transparent;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

th,
td {
  border: 1px solid rgba(148, 163, 184, 0.35);
  padding: 4px 8px;
  text-align: center;
  white-space: nowrap;
  color: inherit;
}

th {
  background: rgba(64, 158, 255, 0.12);
  font-weight: 600;
}
</style>

<script setup lang="ts">
/**
 * 分享管理对话框（2026-10-26 重做）：发布=冻结快照，必须让用户看清「客户看到的是哪一版」。
 * - 新建链接：默认 30 天有效期（不再默认永不过期），可选 7/30/90 天或永久
 * - 每条链接：复制、打开预览、刷新快照、撤销；展示创建/刷新/最近访问时间
 * - 发布状态：refreshedAt 落后于工程 updatedAt 时提示「有未发布变更」
 * 二维码不在此实现：在线生成会把内网链接发给第三方，需本地 qrcode 依赖后再补。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument, Link, Refresh, Delete, View } from '@element-plus/icons-vue'
import {
  createShare,
  listShares,
  refreshShare,
  revokeShare,
  type ShareItem,
} from '@/api/shares'

const props = defineProps<{
  modelValue: boolean
  projectId: string
  projectName: string
  /** 工程最后保存时间（doc.project.updatedAt）：用于判断分享画面是否落后 */
  projectUpdatedAt?: string
}>()

const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const items = ref<ShareItem[]>([])
const loading = ref(false)
const creating = ref(false)
const busyToken = ref('')
const refreshingAll = ref(false)

type ExpiryChoice = '7' | '30' | '90' | 'never'
const expiry = ref<ExpiryChoice>('30')
const EXPIRY_OPTIONS: { value: ExpiryChoice; label: string }[] = [
  { value: '7', label: '7 天有效' },
  { value: '30', label: '30 天有效（推荐）' },
  { value: '90', label: '90 天有效' },
  { value: 'never', label: '永不过期（不推荐）' },
]

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

function fmt(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number): string => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 已过期（后端列表不返回过期标记，前端按 expiresAt 判定） */
function isExpired(item: ShareItem): boolean {
  return !!item.expiresAt && new Date(item.expiresAt).getTime() <= Date.now()
}

/** 已撤销/过期状态 */
function stateOf(item: ShareItem): { label: string; cls: string } {
  if (item.revokedAt) return { label: '已撤销', cls: 'is-off' }
  if (isExpired(item)) return { label: '已过期', cls: 'is-off' }
  return { label: '有效', cls: 'is-on' }
}

/** 该链接的快照是否落后于工程最后一次保存（失效链接不提示「待发布」） */
function isStale(item: ShareItem): boolean {
  if (item.revokedAt || isExpired(item)) return false
  if (!item.refreshedAt || !props.projectUpdatedAt) return false
  return new Date(item.refreshedAt).getTime() < new Date(props.projectUpdatedAt).getTime()
}

const activeItems = computed(() => items.value.filter((i) => !i.revokedAt))
const hasStale = computed(() => activeItems.value.some((i) => isStale(i)))

async function load(): Promise<void> {
  if (!props.projectId) return
  loading.value = true
  try {
    const resp = await listShares(props.projectId)
    items.value = resp.items ?? []
  } catch {
    /* http 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

watch(
  () => props.modelValue,
  (v) => {
    if (v) void load()
  },
)

function expiresAtFor(choice: ExpiryChoice): string | null {
  if (choice === 'never') return null
  const d = new Date()
  d.setDate(d.getDate() + Number(choice))
  return d.toISOString()
}

async function onCreate(): Promise<void> {
  creating.value = true
  try {
    const share = await createShare(props.projectId, { expiresAt: expiresAtFor(expiry.value) })
    await load()
    // 与列表复制同一口径：用当前地址拼，避免反代 Host 配置不当把内网地址发出去
    await copy(publicUrl(share.token), '分享链接已创建并复制')
  } catch {
    /* 失败提示由 http 拦截器统一给出（含 403/422 服务端 message），此处不再叠一条 */
  } finally {
    creating.value = false
  }
}

function publicUrl(token: string): string {
  // 服务端 url 依赖 PUBLIC_BASE_URL/请求头；前端始终用当前地址拼，避免反代配置错误
  return `${location.origin}/s/${token}`
}

function absoluteUrl(item: ShareItem): string {
  return publicUrl(item.token)
}

async function copy(text: string, okMsg = '链接已复制'): Promise<void> {
  // navigator.clipboard 只在安全上下文（HTTPS / localhost）可用；局域网 http://<IP> 入口下为
  // undefined，直接调用抛 TypeError。回落 execCommand 同步复制（已废弃但全场景可用）。
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      ElMessage.success(okMsg)
      return
    } catch {
      /* 权限拒绝等：继续走 execCommand 兜底 */
    }
  }
  if (copyFallback(text)) {
    ElMessage.success(okMsg)
    return
  }
  ElMessageBox.alert(text, '复制失败，请手动复制', { confirmButtonText: '关闭' })
}

/** execCommand 兜底：临时 textarea + select，复制后立刻移除（不污染页面） */
function copyFallback(text: string): boolean {
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.top = '-9999px'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

function onOpen(item: ShareItem): void {
  window.open(absoluteUrl(item), '_blank', 'noopener')
}

async function onRefresh(item: ShareItem): Promise<void> {
  busyToken.value = item.token
  try {
    await refreshShare(item.token)
    ElMessage.success('已刷新分享画面（客户刷新后看到最新版）')
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    busyToken.value = ''
  }
}

/** 一键刷新所有「待发布」快照：改完工程后常见的多链接场景，不用逐条点 */
async function onRefreshAllStale(): Promise<void> {
  const stale = activeItems.value.filter(isStale)
  if (!stale.length) return
  refreshingAll.value = true
  let ok = 0
  let fail = 0
  for (const item of stale) {
    try {
      await refreshShare(item.token)
      ok++
    } catch {
      fail++
    }
  }
  refreshingAll.value = false
  if (fail) ElMessage.warning(`已刷新 ${ok} 个，${fail} 个失败（可重试）`)
  else ElMessage.success(`已刷新 ${ok} 个分享画面`)
  await load()
}

async function onRevoke(item: ShareItem): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '撤销后该链接立即失效，已打开的大屏会被断开。确定撤销？',
      '撤销分享链接',
      { type: 'warning', confirmButtonText: '撤销', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  busyToken.value = item.token
  try {
    await revokeShare(item.token)
    ElMessage.success('链接已撤销')
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    busyToken.value = ''
  }
}
</script>

<template>
  <el-dialog v-model="visible" :title="`分享与发布 · ${projectName}`" width="min(860px, 94vw)" append-to-body>
    <div class="publish-row">
      <el-select v-model="expiry" size="small" class="expiry" aria-label="有效期">
        <el-option v-for="o in EXPIRY_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
      </el-select>
      <el-button type="primary" size="small" :loading="creating" @click="onCreate">
        新建分享链接
      </el-button>
      <span class="hint">分享=冻结当前画面；修改工程后需「刷新快照」客户才会看到新版。</span>
    </div>

    <div v-if="hasStale" class="stale-row">
      <el-alert
        class="stale-alert"
        type="warning"
        :closable="false"
        show-icon
        title="有未发布的修改：分享画面仍是旧版，点击「全部刷新」或对应链接的「刷新」更新。"
      />
      <el-button
        size="small"
        type="warning"
        plain
        :icon="Refresh"
        :loading="refreshingAll"
        @click="onRefreshAllStale"
      >
        全部刷新
      </el-button>
    </div>

    <el-table v-loading="loading" :data="items" size="small" empty-text="还没有分享链接" max-height="420">
      <el-table-column label="链接" min-width="150">
        <template #default="{ row }">
          <span class="token" :title="publicUrl(row.token)">{{ row.token.slice(0, 10) }}…</span>
          <el-tag size="small" :class="stateOf(row).cls" effect="plain">{{ stateOf(row).label }}</el-tag>
          <el-tag v-if="isStale(row)" size="small" type="warning" effect="plain" class="stale-tag">待发布</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="发布时间" width="130">
        <template #default="{ row }">{{ fmt(row.refreshedAt || row.createdAt) }}</template>
      </el-table-column>
      <el-table-column label="有效期至" width="104">
        <template #default="{ row }">{{ row.expiresAt ? fmt(row.expiresAt) : '永久' }}</template>
      </el-table-column>
      <el-table-column label="最近访问" width="116">
        <template #default="{ row }">{{ fmt(row.lastAccessAt) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="250" align="right">
        <template #default="{ row }">
          <template v-if="!row.revokedAt">
            <el-button link type="primary" size="small" :icon="CopyDocument" @click="copy(absoluteUrl(row))">
              复制
            </el-button>
            <el-button link size="small" :icon="View" @click="onOpen(row)">打开</el-button>
            <el-button
              link
              type="warning"
              size="small"
              :icon="Refresh"
              :loading="busyToken === row.token"
              :disabled="refreshingAll"
              @click="onRefresh(row)"
            >
              刷新
            </el-button>
            <el-button link type="danger" size="small" :icon="Delete" @click="onRevoke(row)">撤销</el-button>
          </template>
          <span v-else class="revoked-hint">已失效</span>
        </template>
      </el-table-column>
    </el-table>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.publish-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.expiry {
  width: 150px;
}

.hint {
  flex: 1;
  min-width: 220px;
  color: var(--ws-text-3);
  font-size: 12px;
}

.stale-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.stale-row .stale-alert {
  flex: 1;
  min-width: 0;
}

.token {
  margin-right: 6px;
  font-family: var(--ws-font-tech);
  color: var(--ws-text-2);
}

.is-on {
  color: var(--ws-ok);
  border-color: var(--ws-ok);
}

.is-off {
  color: var(--ws-text-3);
}

.stale-tag {
  margin-left: 4px;
}

.revoked-hint {
  color: var(--ws-text-3);
  font-size: 12px;
}
</style>

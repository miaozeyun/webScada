<script setup lang="ts">
/**
 * 图片选择器（属性面板）：本地上传 + URL 双入口。
 * - single：值为单个 URL；上传/粘贴均可
 * - multiple：值以换行分隔（轮播），可多选上传、逐张移除
 * 上传走 /api/v1/uploads（服务端校验魔数/体积），返回相对 URL 与分享页同口径可匿名加载。
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Close, Plus, Upload } from '@element-plus/icons-vue'
import { uploadImage } from '@/api/uploads'

const props = defineProps<{
  modelValue: string
  /** true = 换行分隔的 URL 列表（轮播） */
  multiple?: boolean
}>()

const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>()

const ACCEPT = 'image/png,image/jpeg,image/gif,image/webp'
/** 与服务端 UPLOAD_MAX_BYTES 同口径（避免大文件白跑一趟网络） */
const MAX_BYTES = 5 * 1024 * 1024

const items = computed(() =>
  props.multiple
    ? String(props.modelValue ?? '').split('\n').map((s) => s.trim()).filter(Boolean)
    : (String(props.modelValue ?? '').trim() ? [String(props.modelValue).trim()] : []),
)

const fileEl = ref<HTMLInputElement>()
const uploading = ref(0)

function pick(): void {
  fileEl.value?.click()
}

async function onFiles(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const files = [...(input.files ?? [])]
  input.value = '' // 允许连续选择同一文件
  if (!files.length) return
  const chosen = props.multiple ? files : files.slice(0, 1)
  const added: string[] = []
  for (const f of chosen) {
    if (f.size > MAX_BYTES) {
      ElMessage.warning(`「${f.name}」超过 5MB，已跳过`)
      continue
    }
    uploading.value++
    try {
      const r = await uploadImage(f)
      added.push(r.url)
    } catch {
      /* http 层已提示 */
    } finally {
      uploading.value--
    }
  }
  if (!added.length) return
  if (props.multiple) emit('update:modelValue', [...items.value, ...added].join('\n'))
  else emit('update:modelValue', added[0])
}

function removeAt(i: number): void {
  if (props.multiple) {
    emit('update:modelValue', items.value.filter((_, k) => k !== i).join('\n'))
  } else {
    emit('update:modelValue', '')
  }
}

function setUrl(v: string): void {
  emit('update:modelValue', v.trim())
}
</script>

<template>
  <div class="image-picker">
    <input ref="fileEl" class="file" type="file" :accept="ACCEPT" :multiple="multiple" @change="onFiles" />

    <div v-if="items.length" class="thumbs" :class="{ multi: multiple }">
      <div v-for="(src, i) in items" :key="`${src}-${i}`" class="thumb">
        <img :src="src" alt="" draggable="false" />
        <button class="del" type="button" title="移除" @click="removeAt(i)">
          <el-icon :size="10"><Close /></el-icon>
        </button>
      </div>
      <button v-if="multiple" class="add" type="button" title="继续上传" :disabled="uploading > 0" @click="pick">
        <el-icon :size="14"><Plus /></el-icon>
      </button>
    </div>

    <div class="bar">
      <button class="upload-btn" type="button" :disabled="uploading > 0" @click="pick">
        <el-icon :size="13"><Upload /></el-icon>
        <span>{{ uploading > 0 ? '上传中…' : multiple ? '上传图片' : items.length ? '更换图片' : '上传图片' }}</span>
      </button>
      <span class="hint">PNG / JPG / GIF / WEBP ≤ 5MB</span>
    </div>

    <!-- 单图保留 URL 入口（外链图片仍可用）；轮播逐行列表由上传维护 -->
    <el-input
      v-if="!multiple"
      :model-value="modelValue"
      size="small"
      placeholder="或粘贴图片 URL"
      @change="setUrl"
    />
    <div v-else class="hint">已选 {{ items.length }} 张，按顺序轮播</div>
  </div>
</template>

<style scoped>
.image-picker {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.file {
  display: none;
}

.thumbs {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(52px, 1fr));
  gap: 6px;
}

.thumb {
  position: relative;
  aspect-ratio: 1 / 1;
  border: 1px solid var(--ws-steel-3);
  border-radius: var(--ws-radius);
  overflow: hidden;
  background: var(--ws-steel-0);
}

.thumb img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.del {
  position: absolute;
  top: 1px;
  right: 1px;
  width: 15px;
  height: 15px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 50%;
  background: rgba(15, 23, 42, 0.66);
  color: #fff;
  cursor: pointer;
}

.del:hover {
  background: var(--ws-alert);
}

.add {
  aspect-ratio: 1 / 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed var(--ws-steel-3);
  border-radius: var(--ws-radius);
  background: var(--ws-steel-0);
  color: var(--ws-text-3);
  cursor: pointer;
}

.add:hover {
  border-color: var(--ws-signal);
  color: var(--ws-signal);
}

.bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.upload-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 24px;
  padding: 0 10px;
  border: 1px solid var(--ws-steel-3);
  border-radius: var(--ws-radius);
  background: var(--ws-panel);
  color: var(--ws-text-2);
  font-size: 11px;
  font-family: inherit;
  cursor: pointer;
}

.upload-btn:hover:not(:disabled) {
  border-color: var(--ws-signal);
  color: var(--ws-signal);
  background: var(--ws-signal-soft);
}

.upload-btn:disabled {
  cursor: default;
  opacity: 0.6;
}

.hint {
  font-size: 10px;
  color: var(--ws-text-3);
  line-height: 1.4;
}
</style>

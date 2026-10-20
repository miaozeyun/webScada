<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({ username: 'admin', password: '' })

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function onSubmit(): Promise<void> {
  await formRef.value?.validate()
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    router.push((route.query.redirect as string) || '/projects')
  } catch {
    /* 拦截器已提示（统一文案防枚举） */
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <template #header>
        <div class="login-title">webScada 组态监控平台</div>
      </template>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @keyup.enter="onSubmit">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="用户名" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" placeholder="密码" show-password autocomplete="current-password" />
        </el-form-item>
        <el-button type="primary" class="login-btn" :loading="loading" @click="onSubmit">登 录</el-button>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.login-wrap {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%);
}

.login-card {
  width: 360px;
}

.login-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--ws-primary);
  text-align: center;
}

.login-btn {
  width: 100%;
}
</style>

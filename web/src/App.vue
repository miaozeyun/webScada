<script setup lang="ts">
// 根组件：Element Plus 中文化（原 app.use(ElementPlus, { locale }) 全局注册，
// 改按需引入后由 config-provider 承接）+ 路由视图
import zhCn from 'element-plus/es/locale/lang/zh-cn'
</script>

<template>
  <el-config-provider :locale="zhCn">
    <router-view />
  </el-config-provider>
</template>

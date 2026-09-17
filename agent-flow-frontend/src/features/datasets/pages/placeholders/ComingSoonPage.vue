<template>
  <div class="coming-soon">
    <h2>{{ title }}</h2>
    <p>{{ hint }}</p>
    <el-button @click="$router.back()">返回</el-button>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, default: '即将推出' },
  hint: { type: String, default: '' },
})
</script>

<style scoped>
.coming-soon {
  padding: 48px 24px;
  text-align: center;
  color: #475467;
}
.coming-soon h2 {
  margin: 0 0 8px;
  font-size: 20px;
  color: #101828;
}
.coming-soon p {
  margin: 0 0 20px;
  font-size: 14px;
}
</style>

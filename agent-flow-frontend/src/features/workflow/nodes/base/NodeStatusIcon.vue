<!-- src/views/copilot/components/workflow/node/base/NodeStatusIcon.vue -->
<template>
  <div v-if="status" class="node-status-icon">
    <el-icon v-if="status === 'running'" class="is-loading status-running"><Loading /></el-icon>
    <el-icon v-else-if="status === 'succeeded'" class="status-success"><CircleCheckFilled /></el-icon>
    <el-icon v-else-if="status === 'failed'" class="status-failed"><CircleCloseFilled /></el-icon>
    <el-icon v-else-if="status === 'exception'" class="status-warning"><WarningFilled /></el-icon>
    <el-icon v-else-if="status === 'paused'" class="status-warning"><WarningFilled /></el-icon>
  </div>
</template>

<script setup>
import { Loading, CircleCheckFilled, CircleCloseFilled, WarningFilled } from '@element-plus/icons-vue'

defineProps({
  status: { type: String, default: '' }
})
</script>

<style scoped>
.node-status-icon {
  display: inline-flex;
  align-items: center;
  margin-left: 6px;
  font-size: 16px;
}
.status-running { color: #409EFF; }
.status-success { color: #67C23A; }
.status-failed { color: #F56C6C; }
.status-warning { color: #E6A23C; }
</style>

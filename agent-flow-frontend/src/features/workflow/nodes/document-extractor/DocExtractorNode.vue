<!-- src/views/copilot/components/workflow/node/document-extractor/DocExtractorNode.vue -->
<template>
  <BaseNode :id="id" :data="data" :selected="selected">
    <div v-if="hasVariable" class="doc-node-content">
      <div class="input-var-title">输入变量</div>
      <div class="var-badge">
        <svg class="var-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M13.9986 8.76189C14.6132 8.04115 15.5117 7.625 16.459 7.625H16.5486C17.1009 7.625 17.5486 8.07272 17.5486 8.625C17.5486 9.17728 17.1009 9.625 16.5486 9.625H16.459C16.0994 9.625 15.7564 9.78289 15.5205 10.0595L13.1804 12.8039L13.9213 15.4107C13.9372 15.4666 13.9859 15.5 14.0355 15.5H15.4296C15.9819 15.5 16.4296 15.9477 16.4296 16.5C16.4296 17.0523 15.9819 17.5 15.4296 17.5H14.0355C13.0858 17.5 12.2562 16.8674 11.9975 15.9575L11.621 14.6328L10.1457 16.3631C9.5311 17.0839 8.63257 17.5 7.68532 17.5H7.59564C7.04336 17.5 6.59564 17.0523 6.59564 16.5C6.59564 15.9477 7.04336 15.5 7.59564 15.5H7.68532C8.04487 15.5 8.38789 15.3421 8.62379 15.0655L10.964 12.3209L10.2231 9.71433C10.2072 9.65839 10.1586 9.625 10.1089 9.625H8.71484C8.16256 9.625 7.71484 9.17728 7.71484 8.625C7.71484 8.07272 8.16256 7.625 8.71484 7.625H10.1089C11.0586 7.625 11.8883 8.25756 12.1469 9.16754L12.5234 10.4921L13.9986 8.76189Z" fill="currentColor"/>
          <path d="M5.429 3C3.61372 3 2.143 4.47071 2.143 6.286V10.4428L1.29289 11.2929C1.10536 11.4804 1 11.7348 1 12C1 12.2652 1.10536 12.5196 1.29289 12.7071L2.143 13.5572V17.714C2.143 19.5293 3.61372 21 5.429 21C5.98128 21 6.429 20.5523 6.429 20C6.429 19.4477 5.98128 19 5.429 19C4.71828 19 4.143 18.4247 4.143 17.714V13.143C4.143 12.8778 4.03764 12.6234 3.85011 12.4359L3.41421 12L3.85011 11.5641C4.03764 11.3766 4.143 11.1222 4.143 10.857V6.286C4.143 5.57528 4.71828 5 5.429 5C5.98128 5 6.429 4.55228 6.429 4C6.429 3.44772 5.98128 3 5.429 3Z" fill="currentColor"/>
          <path d="M18.5708 3C18.0185 3 17.5708 3.44772 17.5708 4C17.5708 4.55228 18.0185 5 18.5708 5C19.2815 5 19.8568 5.57529 19.8568 6.286V10.857C19.8568 11.1222 19.9622 11.3766 20.1497 11.5641L20.5856 12L20.1497 12.4359C19.9622 12.6234 19.8568 12.8778 19.8568 13.143V17.714C19.8568 18.4244 19.2808 19 18.5708 19C18.0185 19 17.5708 19.4477 17.5708 20C17.5708 20.5523 18.0185 21 18.5708 21C20.3848 21 21.8568 19.5296 21.8568 17.714V13.5572L22.7069 12.7071C23.0974 12.3166 23.0974 11.6834 22.7069 11.2929L21.8568 10.4428V6.286C21.8568 4.47071 20.3861 3 18.5708 3Z" fill="currentColor"/>
        </svg>
        <span class="var-name font-mono">{{ formattedVariable }}</span>
      </div>
    </div>
  </BaseNode>
</template>

<script setup>
import { computed } from 'vue'
import BaseNode from '../base/BaseNode.vue'

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false }
})

const hasVariable = computed(() => {
  const sel = props.data?.variable_selector
  return Array.isArray(sel) ? sel.length > 0 : Boolean(sel)
})

const formattedVariable = computed(() => {
  const sel = props.data?.variable_selector
  if (!sel) return ''
  if (Array.isArray(sel)) return sel.join('.')
  return String(sel)
})
</script>

<style scoped>
.doc-node-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 2px 0;
}

.input-var-title {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  color: #667085;
  letter-spacing: 0.3px;
}

.var-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #f8fafc;
  border: 1px solid #eaecf0;
  border-radius: 6px;
  padding: 2px 8px;
  width: fit-content;
  max-width: 100%;
  box-sizing: border-box;
}

.var-icon {
  width: 13px;
  height: 13px;
  flex-shrink: 0;
}

.var-name {
  font-size: 11px;
  color: #155eef;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>

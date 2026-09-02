<template>
  <div class="comments-layer" aria-label="工作流评论">
    <article
      v-for="comment in visibleComments"
      :key="comment.id"
      class="comment-bubble"
      :style="positionStyle(comment)"
      data-comment-input
    >
      <header>
        <strong>{{ comment.author || '协作者' }}</strong>
        <div>
          <button type="button" @click="$emit('resolve', comment.id)">解决</button>
          <button type="button" aria-label="删除评论" @click="$emit('delete', comment.id)">×</button>
        </div>
      </header>
      <textarea
        :value="comment.text"
        name="workflow-comment"
        autocomplete="off"
        placeholder="输入评论…"
        @input="$emit('update', { id: comment.id, text: $event.target.value })"
      ></textarea>
    </article>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  comments: { type: Array, default: () => [] },
  viewport: { type: Object, default: () => ({ x: 0, y: 0, zoom: 1 }) },
})

defineEmits(['update', 'resolve', 'delete'])

const visibleComments = computed(() => props.comments.filter(comment => !comment.resolved))

function positionStyle(comment) {
  const zoom = props.viewport.zoom || 1
  return {
    left: `${comment.position.x * zoom + (props.viewport.x || 0)}px`,
    top: `${comment.position.y * zoom + (props.viewport.y || 0)}px`,
    transform: `scale(${zoom})`,
  }
}
</script>

<style scoped>
.comments-layer {
  position: absolute;
  inset: 0;
  z-index: 35;
  pointer-events: none;
}

.comment-bubble {
  position: absolute;
  width: 260px;
  overflow: hidden;
  transform-origin: 0 0;
  border: 1px solid var(--components-panel-border, rgba(16, 24, 40, 0.08));
  border-radius: 10px;
  background: var(--components-panel-bg, #fff);
  pointer-events: auto;
}

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 9px;
  border-bottom: 1px solid var(--components-panel-border, rgba(16, 24, 40, 0.08));
}

header strong {
  color: var(--text-primary, #101828);
  font-size: 11px;
}

header div {
  display: flex;
  gap: 2px;
}

button {
  padding: 3px 5px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--text-tertiary, #667085);
  font-size: 10px;
  cursor: pointer;
}

button:hover,
button:focus-visible {
  outline: none;
  background: var(--components-actionbar-item-bg-hover, #f2f4f7);
}

textarea {
  display: block;
  width: 100%;
  min-height: 76px;
  box-sizing: border-box;
  resize: vertical;
  border: 0;
  background: transparent;
  padding: 9px;
  color: var(--text-secondary, #354052);
  font: 12px/1.5 inherit;
}

textarea:focus-visible {
  outline: 2px solid var(--state-accent-border, #0033ff);
  outline-offset: -2px;
}
</style>

<template>
  <nav class="top-navigation" aria-label="Primary navigation">
    <ul class="navigation-list">
      <li v-for="item in navigationItems" :key="item.id">
        <RouterLink
          :to="item.to"
          class="navigation-link"
          :class="{ 'is-active': activeId === item.id }"
          :aria-current="activeId === item.id ? 'page' : undefined"
        >
          <NavigationIcon :id="item.id" />
          <span class="navigation-label">{{ item.label }}</span>
        </RouterLink>
      </li>
    </ul>
  </nav>
</template>

<script setup>
import { h } from 'vue'
import { RouterLink } from 'vue-router'
import { navigationItems } from '../navigation.js'

defineProps({
  activeId: {
    type: String,
    required: true,
  },
})

const NavigationIcon = (_, { attrs }) => {
  const common = {
    class: 'navigation-icon',
    xmlns: 'http://www.w3.org/2000/svg',
    fill: 'none',
    viewBox: '0 0 24 24',
    'stroke-width': '1.5',
    stroke: 'currentColor',
    'aria-hidden': 'true',
  }

  if (attrs.id === 'integrations') {
    return h('svg', common, [h('path', {
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
      d: 'M15 13.5H9m4.06-7.19-2.12-2.12a1.5 1.5 0 0 0-1.061-.44H4.5A2.25 2.25 0 0 0 2.25 6v12a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9a2.25 2.25 0 0 0-2.25-2.25h-5.379a1.5 1.5 0 0 1-1.06-.44Z',
    })])
  }

  if (attrs.id === 'knowledge') {
    return h('svg', common, [h('path', {
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
      d: 'M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125',
    })])
  }

  return h('svg', common, [h('path', {
    'stroke-linecap': 'round',
    'stroke-linejoin': 'round',
    d: 'm2.25 12 8.954-8.955a1.126 1.126 0 0 1 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75',
  })])
}
</script>

<style scoped>
.top-navigation {
  width: 100%;
}

.navigation-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 0;
  margin: 0;
  list-style: none;
}

.navigation-list li {
  width: 100%;
}

.navigation-link {
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  width: 100%;
  box-sizing: border-box;
  height: 40px;
  padding: 0 12px;
  border: 1px solid transparent;
  border-radius: var(--af-radius-sm);
  color: var(--af-text-muted);
  outline: none;
  text-decoration: none;
  transition: color var(--af-transition), background-color var(--af-transition), border-color var(--af-transition), transform var(--af-transition);
}

.navigation-link:hover {
  color: var(--af-text-primary);
  background: var(--af-surface);
}

.navigation-link.is-active {
  color: var(--af-brand-strong);
  border-color: transparent;
  background: var(--af-brand-soft);
}

.navigation-link:focus-visible {
  box-shadow: 0 0 0 3px var(--af-focus-ring);
}

.navigation-link:active {
  transform: translateY(1px);
}

.navigation-icon {
  width: 19px;
  height: 19px;
  flex: 0 0 auto;
}

.navigation-label {
  font-size: 14px;
  font-weight: 550;
  line-height: 1;
  white-space: nowrap;
}

</style>

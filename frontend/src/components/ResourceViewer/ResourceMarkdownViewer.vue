<template>
  <article class="markdown-body" v-html="html" />
</template>

<script setup lang="ts">
import { marked } from 'marked'
import { computed } from 'vue'

const props = defineProps<{
  content: string
}>()

const html = computed(() => marked.parse(props.content))
</script>

<style scoped>
.markdown-body {
  line-height: 1.75;
}

.markdown-body :deep(pre) {
  overflow: auto;
  border-radius: 8px;
  background: #101828;
  color: #f8fafc;
  padding: 14px;
}
</style>

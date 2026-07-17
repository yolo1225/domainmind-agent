<template>
  <div class="flow-shell">
    <VueFlow
      :nodes="nodes"
      :edges="edges"
      :fit-view-on-init="true"
      :fit-view-options="{ padding: 0.12 }"
      :min-zoom="0.25"
      :max-zoom="1.4"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { VueFlow, type Edge, type Node } from '@vue-flow/core'

const props = defineProps<{
  activeStep?: string
  hasRevisionLoop?: boolean
  waitingHuman?: boolean
}>()
const compact = window.innerWidth <= 600

const steps = [
  ['prepare_task', '任务准备', '路由触发来源'],
  ['interpret_feedback', '反馈识别', '首次生成时跳过'],
  ['analyze_profile', '画像分析', '证据驱动更新'],
  ['retrieve_knowledge', '知识检索', '召回可追溯来源'],
  ['generate_resource', '并行生成', '三类学习资源'],
  ['review_resource', '双路审核', '独立模型交叉检查'],
  ['human_review', '人工复核', '仅冲突时进入'],
  ['finalize_task', '任务收尾', '确定性发布与持久化'],
] as const

const positions = [
  [20, 65], [210, 65], [400, 65], [590, 65],
  [590, 220], [400, 220], [210, 220], [20, 220],
]
const compactPositions = [
  [0, 20], [175, 20], [175, 150], [0, 150],
  [0, 280], [175, 280], [175, 410], [0, 410],
]

const nodes = computed<Node[]>(() =>
  steps.map(([id, label, caption], index) => {
    const active = props.activeStep === id || (id === 'human_review' && props.waitingHuman)
    return {
      id,
      position: {
        x: (compact ? compactPositions : positions)[index][0],
        y: (compact ? compactPositions : positions)[index][1],
      },
      data: { label: `${label}\n${caption}` },
      style: {
        border: `2px solid ${active ? '#2563eb' : '#d4dbe5'}`,
        borderRadius: '8px',
        padding: '10px 12px',
        color: '#172033',
        background: active ? '#eef5ff' : '#fff',
        width: '145px',
        whiteSpace: 'pre-line',
        textAlign: 'center',
        lineHeight: '1.45',
        boxShadow: active ? '0 4px 10px rgb(37 99 235 / 0.18)' : 'none',
      },
    }
  }),
)

const edges = computed<Edge[]>(() => {
  const main: Edge[] = [
    ['prepare_task', 'interpret_feedback'],
    ['interpret_feedback', 'analyze_profile'],
    ['analyze_profile', 'retrieve_knowledge'],
    ['retrieve_knowledge', 'generate_resource'],
    ['generate_resource', 'review_resource'],
    ['review_resource', 'human_review'],
    ['review_resource', 'finalize_task'],
    ['human_review', 'finalize_task'],
  ].map(([source, target]) => ({
    id: `${source}-${target}`,
    source,
    target,
    animated: true,
    style: { stroke: '#98a5b6' },
  }))
  if (props.hasRevisionLoop) {
    main.push({
      id: 'revision-loop',
      source: 'finalize_task',
      target: 'retrieve_knowledge',
      animated: true,
      label: '修订回路（最多 2 次）',
      style: { stroke: '#c26a0a', strokeWidth: 2 },
      labelStyle: { fill: '#8a4b08', fontWeight: 700 },
    })
  }
  return main
})
</script>

<style scoped>
.flow-shell {
  height: 390px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  overflow: hidden;
  background: #f8fafc;
}

@media (max-width: 600px) {
  .flow-shell { height: 560px; }
}
</style>

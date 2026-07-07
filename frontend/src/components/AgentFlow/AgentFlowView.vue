<template>
  <div class="flow-shell">
    <VueFlow :nodes="nodes" :edges="edges" fit-view />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { VueFlow, type Edge, type Node } from '@vue-flow/core'

const props = defineProps<{
  activeStep?: string
  hasRevisionLoop?: boolean
  currentRound?: number
}>()

const steps = [
  ['load_profile', '学情画像', '读取画像和目标'],
  ['retrieve_knowledge', '知识检索', '召回知识来源'],
  ['generate_resource', '资源生成', '生成三类资源'],
  ['review_resource', '审核校验', '事实和溯源检查'],
  ['decide_next_step', '协同决策', '通过、修订或拦截'],
  ['persist_resource', '资源入库', '展示给学习者'],
]

const nodes = computed<Node[]>(() =>
  steps.map(([id, label, caption], index) => {
    const active = props.activeStep === id
    const doneIndex = steps.findIndex(([stepId]) => stepId === props.activeStep)
    const done = doneIndex > index
    return {
      id,
      position: { x: index * 185, y: index % 2 === 0 ? 70 : 190 },
      data: { label: `${label}\n${caption}` },
      style: {
        border: `2px solid ${active ? '#2563eb' : done ? '#16a34a' : '#dbe4ef'}`,
        borderRadius: '10px',
        padding: '11px 12px',
        color: '#172033',
        background: active ? '#eef5ff' : '#fff',
        width: '138px',
        whiteSpace: 'pre-line',
        textAlign: 'center',
        lineHeight: '1.45',
        boxShadow: active ? '0 4px 8px rgb(37 99 235 / 0.16)' : 'none',
      },
    }
  }),
)

const edges = computed<Edge[]>(() => {
  const mainEdges = steps.slice(0, -1).map(([id], index) => ({
    id: `${id}-${steps[index + 1][0]}`,
    source: id,
    target: steps[index + 1][0],
    animated: true,
    style: { stroke: '#9aa9bc' },
  }))
  if (!props.hasRevisionLoop) {
    return mainEdges
  }
  return [
    ...mainEdges,
    {
      id: 'revision-loop',
      source: 'decide_next_step',
      target: 'retrieve_knowledge',
      animated: true,
      label: `第 ${props.currentRound || 2} 轮修订`,
      style: { stroke: '#d97706', strokeWidth: 2 },
      labelStyle: { fill: '#92400e', fontWeight: 700 },
    },
  ]
})
</script>

<style scoped>
.flow-shell {
  height: 370px;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  overflow: hidden;
  background:
    linear-gradient(90deg, rgb(37 99 235 / 0.05) 1px, transparent 1px),
    linear-gradient(180deg, rgb(37 99 235 / 0.05) 1px, transparent 1px),
    #f8fafc;
  background-size: 28px 28px;
}
</style>

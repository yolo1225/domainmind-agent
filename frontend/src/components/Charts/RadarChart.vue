<template>
  <div ref="chartRef" class="chart" />
</template>

<script setup lang="ts">
import * as echarts from 'echarts'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps<{
  values: number[]
}>()

const chartRef = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

function renderChart() {
  if (!chartRef.value) return
  chart ??= echarts.init(chartRef.value)
  chart.setOption({
    color: ['#2563eb'],
    tooltip: {},
    radar: {
      radius: '66%',
      indicator: [
        { name: '理论基础', max: 100 },
        { name: '实操能力', max: 100 },
        { name: '问题解决', max: 100 },
        { name: '知识广度', max: 100 },
        { name: '学习速度', max: 100 },
      ],
      splitArea: {
        areaStyle: {
          color: ['#f8fafc', '#eef5ff'],
        },
      },
    },
    series: [
      {
        type: 'radar',
        data: [{ value: props.values, name: '当前画像' }],
        areaStyle: { opacity: 0.18 },
        lineStyle: { width: 2 },
        symbolSize: 5,
      },
    ],
  })
}

function resizeChart() {
  chart?.resize()
}

onMounted(() => {
  renderChart()
  window.addEventListener('resize', resizeChart)
})
watch(() => props.values, renderChart)
onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeChart)
  chart?.dispose()
})
</script>

<style scoped>
.chart {
  width: 100%;
  min-height: 330px;
}
</style>

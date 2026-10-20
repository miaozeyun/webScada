/**
 * 图表组件共用默认样式：画面内容不随界面主题，固定一档中性灰 + 信号青
 * （#909399/#c0c4cc 在深浅画布底上都可读；此前各图表复制的字面量统一收敛于此）。
 */

/** 单色基础色板（序列/指针/标题） */
export const CHART = {
  text: '#909399',
  axis: '#c0c4cc',
  split: 'rgba(148, 163, 184, 0.2)',
  signal: '#1ba7b8',
  ok: '#67c23a',
  signalArea: 'rgba(27, 167, 184, 0.18)',
  okArea: 'rgba(103, 194, 58, 0.15)',
}

/** 坐标轴公共样式（x/y 通用） */
export const AXIS = {
  axisLabel: { color: CHART.text },
  axisLine: { lineStyle: { color: CHART.axis } },
  splitLine: { lineStyle: { color: CHART.split } },
}

/** 标题文字样式 */
export const TITLE_STYLE = { color: CHART.text, fontSize: 14 }

/** 多序列调色板（饼图/后续多序列图共用） */
export const PALETTE: string[] = ['#1ba7b8', '#67c23a', '#e6a23c', '#f56c6c', '#909399']

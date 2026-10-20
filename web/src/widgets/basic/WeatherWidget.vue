<script setup lang="ts">
/** 天气（M7，对齐 BY「天气和时间」）：open-meteo 免费接口（无 key），按经纬度取实况。
 * 10 分钟刷新；失败静默保留旧值（首次失败显示 '--'）。 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const REFRESH_MS = 10 * 60 * 1000

/** WMO weather code → 文本/图标（只取常用段） */
const WMO: Record<number, { text: string; icon: string }> = {
  0: { text: '晴', icon: '☀️' },
  1: { text: '基本晴', icon: '🌤️' },
  2: { text: '多云', icon: '⛅' },
  3: { text: '阴', icon: '☁️' },
  45: { text: '雾', icon: '🌫️' },
  48: { text: '冻雾', icon: '🌫️' },
  51: { text: '毛毛雨', icon: '🌦️' },
  53: { text: '毛毛雨', icon: '🌦️' },
  55: { text: '浓毛毛雨', icon: '🌧️' },
  61: { text: '小雨', icon: '🌦️' },
  63: { text: '中雨', icon: '🌧️' },
  65: { text: '大雨', icon: '🌧️' },
  71: { text: '小雪', icon: '🌨️' },
  73: { text: '中雪', icon: '🌨️' },
  75: { text: '大雪', icon: '❄️' },
  80: { text: '阵雨', icon: '🌦️' },
  81: { text: '强阵雨', icon: '🌧️' },
  82: { text: '暴雨', icon: '⛈️' },
  95: { text: '雷雨', icon: '⛈️' },
  96: { text: '雷雨冰雹', icon: '⛈️' },
  99: { text: '强雷雨冰雹', icon: '⛈️' },
}

const weather = ref<{ temp: number; humidity: number; wind: number; code: number } | null>(null)
let timer: ReturnType<typeof setInterval> | null = null

async function fetchWeather(): Promise<void> {
  const lat = Number(props.nodeProps.lat ?? 39.9)
  const lon = Number(props.nodeProps.lon ?? 116.4)
  try {
    const resp = await fetch(
      `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}` +
        '&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m',
      { signal: AbortSignal.timeout(8000) },
    )
    if (!resp.ok) return
    const json = (await resp.json()) as {
      current?: { temperature_2m?: number; relative_humidity_2m?: number; weather_code?: number; wind_speed_10m?: number }
    }
    const c = json.current
    if (c && typeof c.temperature_2m === 'number') {
      weather.value = {
        temp: c.temperature_2m,
        humidity: c.relative_humidity_2m ?? 0,
        wind: c.wind_speed_10m ?? 0,
        code: c.weather_code ?? 0,
      }
    }
  } catch {
    /* 网络失败保留旧值 */
  }
}

const wmo = computed(() => WMO[weather.value?.code ?? 0] ?? { text: '—', icon: '🌡️' })

onMounted(() => {
  void fetchWeather()
  timer = setInterval(fetchWeather, REFRESH_MS)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="weather-widget">
    <div class="main">
      <span class="icon">{{ wmo.icon }}</span>
      <span class="temp">{{ weather ? weather.temp.toFixed(1) : '--' }}<span class="deg">℃</span></span>
    </div>
    <div class="meta">
      <span v-if="nodeProps.city" class="city">{{ nodeProps.city }}</span>
      <span>{{ wmo.text }}</span>
      <span>💧{{ weather?.humidity ?? '--' }}%</span>
      <span>🌬️{{ weather?.wind ?? '--' }}m/s</span>
    </div>
  </div>
</template>

<style scoped>
.weather-widget {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  overflow: hidden;
}

.main {
  display: flex;
  align-items: center;
  gap: 10px;
}

.icon {
  font-size: 1.8em;
}

.temp {
  font-size: 1.7em;
  font-weight: 700;
  font-family: 'DIN Alternate', Consolas, monospace;
}

.deg {
  font-size: 0.45em;
  margin-left: 2px;
  opacity: 0.7;
}

.meta {
  display: flex;
  gap: 10px;
  font-size: 0.7em;
  opacity: 0.8;
  white-space: nowrap;
}

.city {
  font-weight: 600;
}
</style>

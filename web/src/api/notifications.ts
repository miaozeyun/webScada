/** 通知投递记录（2026-10-26）：outbox 可观测——sent/pending/sending/dead 全量。 */
import { http } from './http'

export type DeliveryStatus = 'pending' | 'sending' | 'sent' | 'dead'

export interface DeliveryOut {
  id: number
  alarmId: number | null
  event: string
  channelKind: string
  channelLabel: string
  status: DeliveryStatus
  attempts: number
  lastError: string | null
  message: string | null
  level: string | null
  createdAt: string
  sentAt: string | null
}

export const listDeliveries = (projectId: string, params: { limit?: number; status?: string } = {}) =>
  http.get<{ items: DeliveryOut[] }>(`/projects/${projectId}/notifications/deliveries`, { params })

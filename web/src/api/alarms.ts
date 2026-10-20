/** 报警记录接口（M5，03-接口清单 §2.9）。 */
import { http } from './http'

export interface AlarmRecordIn {
  ruleId: string
  variableKey: string
  level: 'info' | 'warn' | 'critical'
  message: string
  value: string | null
  status: 'active' | 'recovered'
}

export interface AlarmRecordOut extends AlarmRecordIn {
  id: number
  triggeredAt: string
  recoveredAt: string | null
}

export const addAlarmRecord = (projectId: string, data: AlarmRecordIn) =>
  http.post<void>(`/projects/${projectId}/alarm-records`, data)

export const listAlarmRecords = (projectId: string, params?: { page?: number; size?: number }) =>
  http.get<AlarmRecordOut[]>(`/projects/${projectId}/alarm-records`, { params })

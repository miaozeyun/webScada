/**
 * 数据源连通性测试（契约 03 §2.9）。
 * 带 projectId+datasourceId 时服务端对空/缺省敏感字段做凭证注回（PUT 空串=保留语义同源）；
 * 表单草稿测试（未保存）只传 type+config，用本次明文值。
 */
import { http } from './http'

export interface DatasourceTestResult {
  ok: boolean
  type: string
  latencyMs: number
  message: string
}

export async function testDatasource(body: {
  type: 'mqtt' | 'websocket' | 'rest' | 'mock' | 'modbus'
  config: Record<string, unknown>
  projectId?: string
  datasourceId?: string
}): Promise<DatasourceTestResult> {
  return http.post('/datasources/test', body)
}

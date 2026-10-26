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
  type: 'mqtt' | 'websocket' | 'rest' | 'mock' | 'modbus' | 'opcua'
  config: Record<string, unknown>
  projectId?: string
  datasourceId?: string
}): Promise<DatasourceTestResult> {
  return http.post('/datasources/test', body)
}

export interface OpcUaNode {
  nodeId: string
  browseName: string
}

export interface OpcUaBrowseResult {
  ok: boolean
  message: string
  nodes: OpcUaNode[]
  latencyMs: number
}

/** OPC UA 地址空间浏览（一层子节点，缺省 Objects 根）；编辑已存源时由服务端注回凭证 */
export function browseOpcUa(body: {
  endpoint: string
  username?: string | null
  password?: string | null
  nodeId?: string | null
  projectId?: string
  datasourceId?: string
}): Promise<OpcUaBrowseResult> {
  return http.post('/datasources/opcua/browse', body)
}

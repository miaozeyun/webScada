/** 图片上传（编辑器图片/轮播组件直传，落盘后返回相对 URL）。 */
import { http } from './http'

export interface UploadResult {
  url: string
  name: string
  size: number
}

/** 上传一张图片（png/jpg/gif/webp，服务端上限 5MB）；返回 /api/v1/uploads/xxx URL */
export function uploadImage(file: File): Promise<UploadResult> {
  const form = new FormData()
  form.append('file', file)
  return http.post<UploadResult>('/uploads', form)
}

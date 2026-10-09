import type { HttpMethod } from '../api'

export const METHODS: HttpMethod[] = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']

/** 方法标签的颜色：和 Postman / Apifox 的习惯一致，GET 绿、POST 蓝、PUT / PATCH 橙、DELETE 红 */
export const METHOD_TAG: Record<HttpMethod, 'success' | 'primary' | 'warning' | 'danger' | 'info'> = {
  GET: 'success',
  POST: 'primary',
  PUT: 'warning',
  PATCH: 'warning',
  DELETE: 'danger',
}

/** 方法的文字颜色，用在列表和请求栏 */
export const METHOD_COLOR: Record<HttpMethod, string> = {
  GET: '#1f8a3b',
  POST: '#2f6fd6',
  PUT: '#d9730d',
  PATCH: '#d9730d',
  DELETE: '#d03b3b',
}

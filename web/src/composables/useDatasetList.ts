import { ref } from 'vue'
import { datasetsApi, type Dataset } from '../api'
import { showError } from '../utils/feedback'

const datasets = ref<Dataset[]>([])
const loaded = ref(false)

/** 数据集列表（不含行数据），业务流程页和接口页共用一份 */
export function useDatasetList() {
  async function refresh(silent = false): Promise<void> {
    try {
      datasets.value = await datasetsApi.list()
      loaded.value = true
    } catch (e) {
      if (!silent) showError(e, '加载数据集失败')
    }
  }
  return { datasets, loaded, refresh }
}

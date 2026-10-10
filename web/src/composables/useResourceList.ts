import { onMounted, ref, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { ResourceApi } from '../api'
import { confirmAction, showError } from '../utils/feedback'

/** 定义类页面共用的「加载列表 + 确认后删除」。 */
export function useResourceList<T extends { id: number; name: string }, TInput>(
  api: ResourceApi<T, TInput>,
  label: string,
) {
  const items = ref([]) as Ref<T[]>
  const loading = ref(false)

  async function load(): Promise<void> {
    loading.value = true
    try {
      items.value = await api.list()
    } catch (e) {
      showError(e, `加载${label}失败`)
    } finally {
      loading.value = false
    }
  }

  /** confirmed：调用方已经确认过（例如在影响提示里点了删除），不再弹确认框 */
  async function remove(row: T, confirmed = false): Promise<void> {
    if (!confirmed && !(await confirmAction(`确定删除${label}「${row.name}」吗？`, `删除${label}`, true))) return
    try {
      await api.remove(row.id)
      ElMessage.success('已删除')
      await load()
    } catch (e) {
      showError(e, '删除失败')
    }
  }

  onMounted(load)

  return { items, loading, load, remove }
}

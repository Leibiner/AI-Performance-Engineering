import { onMounted, ref, type Ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { RefKind } from '../api'
import { confirmAction, showError } from '../utils/feedback'
import { confirmDelete } from '../utils/references'

/** 列表和删除用到的接口；数据集、文件这类不是统一增删改查的资源也能用 */
interface ListApi<T> {
  list(): Promise<T[]>
  remove(id: number): Promise<void>
}

/**
 * 定义类页面共用的「加载列表 + 确认后删除」。
 * kind：会被引用的种类（契约 §3.8）。给了就用标准的删除确认：被引用时列出会失效的引用，确认后只删这一个对象
 */
export function useResourceList<T extends { id: number; name: string }>(api: ListApi<T>, label: string, kind?: RefKind) {
  const items = ref([]) as Ref<T[]>
  const loading = ref(false)
  const router = useRouter()

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

  async function remove(row: T): Promise<void> {
    try {
      const ok = kind
        ? await confirmDelete(router, kind, row.id, row.name)
        : await confirmAction(`确定删除${label}「${row.name}」吗？`, `删除${label}`, true)
      if (!ok) return
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

import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { filesApi, type FileAsset } from '../api'
import { showError } from '../utils/feedback'
import { oversizeMessage, readFileBase64 } from '../utils/test-data'

const files = ref<FileAsset[]>([])
const loaded = ref(false)

/** 已上传的文件（只有元数据），接口编辑器的 form-data 文件项用 */
export function useFileList() {
  async function refresh(silent = false): Promise<void> {
    try {
      files.value = await filesApi.list()
      loaded.value = true
    } catch (e) {
      if (!silent) showError(e, '加载文件失败')
    }
  }

  async function upload(file: File): Promise<FileAsset | null> {
    const tooBig = oversizeMessage(file)
    if (tooBig) {
      ElMessage.error(tooBig)
      return null
    }
    try {
      const contentBase64 = await readFileBase64(file)
      const created = await filesApi.create({ name: file.name, contentType: file.type, note: '', contentBase64 })
      files.value = [...files.value.filter((f) => f.id !== created.id), created]
      return created
    } catch (e) {
      showError(e, '上传失败')
      return null
    }
  }

  return { files, loaded, refresh, upload }
}

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { apisApi, type ApiDef } from '../api'
import { useResourceList } from '../composables/useResourceList'
import { confirmAction, showError } from '../utils/feedback'
import { emptyForm, fromApi, snapshot, toInput, type ApiForm } from '../utils/api-form'
import type { CurlImport } from '../utils/curl'
import PageHeader from '../components/PageHeader.vue'
import ApiList from '../components/apis/ApiList.vue'
import ApiEditor from '../components/apis/ApiEditor.vue'
import CurlImportDialog from '../components/apis/CurlImportDialog.vue'

// 接口页：左栏列表，右栏工作台（编辑 + 发送 + 看响应）。像 Postman 一样，一个接口占满右栏，不用对话框。
const { items, loading, load, remove } = useResourceList(apisApi, '接口')

const selectedId = ref<number | null>(null)
/** 正在编辑的内容；null 表示既没选中也没在新建 */
const form = ref<ApiForm | null>(null)
/** 打开时的快照，用来判断有没有改动 */
const baseline = ref('')
const saving = ref(false)
const importVisible = ref(false)

const isNew = computed(() => form.value !== null && selectedId.value === null)
const dirty = computed(() => form.value !== null && snapshot(form.value) !== baseline.value)

// 列表第一次加载完成时自动打开第一个，页面打开就有东西可看
watch(items, (list) => {
  if (form.value === null && selectedId.value === null && list.length > 0) open(list[0])
})

function open(api: ApiDef): void {
  selectedId.value = api.id
  form.value = fromApi(api)
  baseline.value = snapshot(form.value)
}

async function guard(): Promise<boolean> {
  if (!dirty.value) return true
  return confirmAction('当前接口有未保存的修改，放弃这些修改吗？', '未保存的修改', true)
}

async function select(api: ApiDef): Promise<void> {
  if (api.id === selectedId.value) return
  if (!(await guard())) return
  open(api)
}

async function create(): Promise<void> {
  if (!(await guard())) return
  selectedId.value = null
  form.value = emptyForm()
  baseline.value = snapshot(form.value)
}

async function duplicate(): Promise<void> {
  if (!form.value) return
  if (!(await guard())) return
  const copy = fromApi(toInput(form.value))
  copy.name = `${copy.name}（副本）`
  selectedId.value = null
  form.value = copy
  baseline.value = '' // 副本一开始就算有改动，提醒保存
}

async function onImported(result: CurlImport): Promise<void> {
  if (!(await guard())) return
  selectedId.value = null
  form.value = fromApi(result.input)
  baseline.value = ''
  ElMessage.success(`已填入 ${result.input.method} ${result.input.path}，改好名字后保存`)
}

async function save(): Promise<void> {
  if (!form.value) return
  const input = toInput(form.value)
  if (!input.name) {
    ElMessage.warning('请填写接口名称')
    return
  }
  if (!input.path.startsWith('/')) {
    ElMessage.warning('路径必须以 / 开头')
    return
  }
  saving.value = true
  try {
    const saved = selectedId.value === null ? await apisApi.create(input) : await apisApi.update(selectedId.value, input)
    ElMessage.success('已保存')
    await load()
    open(saved)
  } catch (e) {
    showError(e, '保存失败')
  } finally {
    saving.value = false
  }
}

async function del(): Promise<void> {
  const api = items.value.find((a) => a.id === selectedId.value)
  if (!api) return
  await remove(api)
  // 被流程引用时删除会被拒绝（409），列表里还在；真删掉了才清空右栏
  if (!items.value.some((a) => a.id === api.id)) {
    selectedId.value = null
    form.value = null
    if (items.value.length > 0) open(items.value[0])
  }
}
</script>

<template>
  <div class="page apis-page">
    <PageHeader
      title="接口"
      description="被测系统的一个请求：描述“请求什么、期望什么、取出什么”。顺序在业务流程里编排。选好被测环境就能直接发送一次看响应。"
    />
    <div class="workbench">
      <ApiList
        class="workbench-list"
        :items="items"
        :selected-id="selectedId"
        :draft-new="isNew"
        :loading="loading"
        @select="select"
        @create="create"
        @import="importVisible = true"
      />
      <section class="workbench-main">
        <ApiEditor
          v-if="form"
          v-model="form"
          :is-new="isNew"
          :dirty="dirty"
          :saving="saving"
          @save="save"
          @duplicate="duplicate"
          @delete="del"
        />
        <div v-else class="workbench-empty">
          <p>选择左侧的接口，或点“新建”。</p>
          <p class="muted">也可以把浏览器开发者工具里“复制为 cURL”的命令粘进来，直接生成接口。</p>
        </div>
      </section>
    </div>
    <CurlImportDialog v-model="importVisible" @imported="onImported" />
  </div>
</template>

<style scoped>
.apis-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 60px);
}
.workbench {
  display: grid;
  flex: 1;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 16px;
  min-height: 0;
}
.workbench-list,
.workbench-main {
  min-height: 0;
  border: 1px solid var(--hairline);
  border-radius: 8px;
  background: #fff;
}
.workbench-main {
  overflow-y: auto;
}
.workbench-empty {
  padding: 80px 24px;
  text-align: center;
  line-height: 1.8;
}
.workbench-empty p {
  margin: 0;
}
@media (max-width: 960px) {
  .apis-page {
    height: auto;
  }
  .workbench {
    grid-template-columns: 1fr;
  }
  .workbench-list {
    max-height: 320px;
  }
}
</style>

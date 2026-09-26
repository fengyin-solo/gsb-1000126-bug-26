<template>
  <div v-if="open" class="modal-mask" @click.self="$emit('close')">
    <form class="modal-card" @submit.prevent="submit">
      <header class="modal-head">
        <h3>{{ mode === 'create' ? '登记质控样品' : '保存质控样品' }}</h3>
        <button class="btn ghost" type="button" :disabled="saving" @click="$emit('close')">关闭</button>
      </header>

      <div v-if="errorMessage" class="form-error" role="alert">{{ errorMessage }}</div>

      <div class="form-grid">
        <label v-for="field in fields" :key="field" class="form-item">
          <span>{{ field }}<em v-if="requiredFields.includes(field)">*</em></span>
          <input v-model.trim="form[field]" :disabled="saving" :placeholder="`请输入${field}`" />
        </label>
      </div>

      <footer class="modal-foot">
        <span class="version-text" v-if="mode === 'edit'">当前版本：{{ initialVersion ?? '未知' }}</span>
        <button class="btn" type="button" :disabled="saving" @click="$emit('close')">取消</button>
        <button class="btn primary" type="submit" :disabled="saving">
          {{ saving ? '保存中...' : '保存' }}
        </button>
      </footer>
    </form>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'

import { request } from '@/api/client'
import type { QcRow } from '@/stores/qc'

const props = defineProps<{
  open: boolean
  mode: 'create' | 'edit'
  entry?: QcRow | null
}>()

const emit = defineEmits<{
  close: []
  saved: [entry: QcRow]
  conflict: [entry: QcRow | null]
}>()

const fields = ['质控编号', '质控类别', '标准值', '允许偏差', '实测值', '判定结果', '检测日期']
const requiredFields = ['质控编号', '质控类别', '标准值']

type FormState = Record<string, string>
const emptyForm = (): FormState => Object.fromEntries(fields.map((field) => [field, '']))
const form = reactive<FormState>(emptyForm())
const saving = ref(false)
const errorMessage = ref('')
const initialVersion = ref<number | null>(null)
const submitId = ref('')

function hydrateForm() {
  errorMessage.value = ''
  saving.value = false
  if (props.mode === 'edit' && props.entry) {
    submitId.value = ''
    const nextForm = emptyForm()
    fields.forEach((field) => {
      const value = props.entry?.[field]
      nextForm[field] = value === null || value === undefined ? '' : String(value)
    })
    Object.assign(form, nextForm)
    const version = props.entry.version
    initialVersion.value = version === undefined || version === null ? null : Number(version)
    return
  }

  Object.assign(form, emptyForm())
  initialVersion.value = null
  submitId.value = ''
}

watch(
  () => [props.open, props.mode, props.entry?.id] as const,
  hydrateForm,
  { immediate: true },
)
watch(
  () => props.entry?.version,
  (version) => {
    if (!props.open || props.mode !== 'edit' || saving.value || version === undefined || version === null) return
    const nextVersion = Number(version)
    if (initialVersion.value !== nextVersion) initialVersion.value = nextVersion
  },
)

function refreshVersion(latest: QcRow) {
  const version = latest.version
  if (version !== undefined && version !== null) initialVersion.value = Number(version)
}

async function submit() {
  if (saving.value) return
  errorMessage.value = ''
  const missing = requiredFields.find((field) => !form[field])
  if (missing) {
    errorMessage.value = `请填写${missing}`
    return
  }

  saving.value = true
  try {
    const values = Object.fromEntries(fields.map((field) => [field, form[field] || null]))
    const url = props.mode === 'create' ? '/api/qc' : `/api/qc/${props.entry?.id}`
    const method = props.mode === 'create' ? 'POST' : 'PUT'
    const body: Record<string, unknown> = { values }
    if (props.mode === 'edit') body.expectedVersion = initialVersion.value
    if (!submitId.value) {
      submitId.value = globalThis.crypto?.randomUUID?.() ??
        `qc-${Date.now()}-${Math.random().toString(16).slice(2)}`
    }
    body.requestId = submitId.value
    const response = await request(url, { method, body: JSON.stringify(body) })
    const payload = await response.json().catch(() => null) as
      | { ok?: boolean; message?: string; entry?: QcRow }
      | null
    if (!response.ok || !payload?.ok || !payload.entry) {
      if (response.status === 409 && payload?.entry) {
        refreshVersion(payload.entry)
        emit('conflict', payload.entry)
      }
      throw new Error(payload?.message || `保存失败（${response.status}）`)
    }
    emit('saved', payload.entry)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '质控样品保存失败'
  } finally {
    saving.value = false
  }
}
</script>

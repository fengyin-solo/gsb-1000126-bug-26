<template>
  <section class="page" data-module="qc-detail">
    <header class="page-head">
      <div>
        <h2>质控样品详情</h2>
        <p class="page-desc">详情与列表读取同一条后端记录；保存成功前不回写本地数据。</p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn" to="/qc">返回列表</RouterLink>
      </div>
    </header>

    <div v-if="loading" class="detail-card">正在读取质控样品...</div>
    <div v-else-if="readFailed || !entry" class="detail-card error-text">{{ errorMessage || '质控样品不存在' }}</div>
    <template v-else>
      <div v-if="errorMessage" class="detail-banner error-text" role="alert">{{ errorMessage }}</div>

      <div class="detail-grid">
        <article v-for="item in detailItems" :key="item.label" class="detail-item">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </article>
        <article class="detail-item detail-item-wide">
          <span>记录版本</span>
          <strong>{{ Number(entry.version ?? 1) }} · 更新于 {{ formatTime(entry.updated_at) }}</strong>
        </article>
      </div>

      <div class="detail-actions">
        <button class="btn primary" type="button" :disabled="Boolean(actionSaving)" @click="formOpen = true">
          编辑质控样品
        </button>
        <button
          v-for="action in actions"
          :key="action"
          class="btn"
          type="button"
          :disabled="actionSaving !== ''"
          @click="runAction(action)"
        >
          {{ actionSaving === action ? `${action}中...` : action }}
        </button>
      </div>
    </template>

    <QcForm
      :open="formOpen"
      mode="edit"
      :entry="entry"
      @close="formOpen = false"
      @saved="handleSaved"
      @conflict="handleConflict"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'
import { useQcStore, type QcRow } from '@/stores/qc'
import QcForm from '@/views/qc/QcForm.vue'

const actions = ['检测质控', '确认受控', '标记失控']
const detailFields = [
  '质控编号',
  '质控类别',
  '标准值',
  '允许偏差',
  '实测值',
  '判定结果',
  '检测日期',
  '质控状态',
]

const route = useRoute()
const router = useRouter()
const store = useQcStore()
const loading = ref(true)
const readFailed = ref(false)
const actionSaving = ref('')
const formOpen = ref(false)
const errorMessage = ref('')

const entryId = computed(() => Number(route.params.id))
const entry = computed<QcRow | null>(() => store.getEntry(entryId.value) ?? null)
const detailItems = computed(() => detailFields.map((field) => ({
  label: field,
  value: formatValue(entry.value?.[field]),
})))

function formatValue(value: unknown) {
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

function formatTime(value: unknown) {
  return value ? String(value) : '未记录'
}

async function reload(showLoading = true) {
  if (showLoading) loading.value = true
  readFailed.value = false
  errorMessage.value = ''
  try {
    const response = await request(`/api/qc/${entryId.value}`)
    if (!response.ok) {
      throw new Error(`质控样品读取失败（${response.status}）`)
    }
    const latest = await response.json() as QcRow
    store.setEntry(latest)
  } catch (error) {
    readFailed.value = true
    errorMessage.value = error instanceof Error ? error.message : '质控样品读取失败'
    if (showLoading) store.clearEntry(entryId.value)
  } finally {
    loading.value = false
  }
}

function handleSaved(saved: QcRow) {
  store.setEntry(saved)
  formOpen.value = false
  errorMessage.value = ''
  void router.replace({ path: `/qc/${saved.id}`, query: { savedAt: String(saved.updated_at ?? '') } })
  void reload(false)
}

function handleConflict(latest: QcRow | null) {
  if (latest) store.setEntry(latest)
  void reload(false)
}

async function runAction(action: string) {
  if (!entry.value || actionSaving.value) return
  actionSaving.value = action
  errorMessage.value = ''
  try {
    const response = await request(`/api/qc/${entryId.value}/actions`, {
      method: 'POST',
      body: JSON.stringify({
        action,
        expectedVersion: Number(entry.value.version ?? 1),
        requestId: globalThis.crypto?.randomUUID?.() ?? `qc-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      }),
    })
    const payload = await response.json().catch(() => null) as
      | { ok?: boolean; message?: string; entry?: QcRow }
      | null
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '质量控制动作未生效')
    }
    if (payload.entry) store.setEntry(payload.entry)
    await reload(false)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '质量控制操作失败'
    await reload(false)
  } finally {
    actionSaving.value = ''
  }
}

onMounted(() => {
  void reload()
})
</script>

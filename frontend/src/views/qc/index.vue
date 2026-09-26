<template>
  <section class="page" data-module="qc">
    <header class="page-head">
      <div>
        <h2>质量控制管理</h2>
        <p class="page-desc">维护质控样品，围绕质控编号、质控类别、标准值、允许偏差做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记质控样品</button>
        <button class="btn" type="button" @click="exportRows">导出质量控制清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>质控编号</span>
        <input v-model="filters.keyword" placeholder="按质控编号检索" />
      </label>
      <label class="filter-item">
        <span>质控类别</span>
        <input v-model="filters.category" placeholder="按质控类别检索" />
      </label>
      <label class="filter-item">
        <span>质控状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>记录操作</th>
          <th>状态操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in store.rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ displayValue(row, column) }}</td>
          <td class="row-actions">
            <RouterLink class="link" :to="`/qc/${row.id}`">详情</RouterLink>
            <button class="link" type="button" @click="openEdit(row)">编辑</button>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :disabled="isRowBusy(row) || isSaving(row.id, action)"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!store.rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无质量控制数据，可先登记质控样品</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ store.total }} 条质量控制记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <QcForm
      :open="formOpen"
      :mode="formMode"
      :entry="editingRow"
      @close="formOpen = false"
      @saved="handleSaved"
      @conflict="handleConflict"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { useQcStore, type QcRow } from '@/stores/qc'
import QcForm from '@/views/qc/QcForm.vue'

const ENDPOINT = '/api/qc'
const columns = ['质控编号', '质控类别', '标准值', '允许偏差', '实测值', '判定结果', '检测日期', '质控状态']
const actions = ['检测质控', '确认受控', '标记失控']
const statuses = ['待检测', '检测中', '受控', '失控']
const stats = [
  { label: '待检质控品', value: 0 },
  { label: '受控质控品', value: 0 },
  { label: '失控质控品', value: 0 },
]

const store = useQcStore()
const errorMessage = ref('')
const filters = reactive({ keyword: '', category: '', status: '' })
const formOpen = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const editingId = ref<string | number | null>(null)
const pendingActions = ref<Record<string, boolean>>({})

const editingRow = computed(() => (editingId.value === null ? null : store.getEntry(editingId.value) ?? null))

function displayValue(row: QcRow, column: string) {
  const value = row[column]
  return value === null || value === undefined || value === '' ? '—' : value
}

function rowActionKey(id: unknown, action: string) {
  return `${String(id)}:${action}`
}

function isSaving(id: unknown, action: string) {
  return Boolean(pendingActions.value[rowActionKey(id, action)])
}

function isRowBusy(row: QcRow) {
  return Object.keys(pendingActions.value).some((key) => key.startsWith(`${row.id}:`))
}

function resetFilters() {
  filters.keyword = ''
  filters.category = ''
  filters.status = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  formMode.value = 'create'
  editingId.value = null
  formOpen.value = true
}

function openEdit(row: QcRow) {
  if (typeof row.id !== 'string' && typeof row.id !== 'number') return
  formMode.value = 'edit'
  editingId.value = row.id
  formOpen.value = true
}

function handleSaved(entry: QcRow) {
  store.setEntry(entry)
  formOpen.value = false
  editingId.value = null
  void reload()
}

function handleConflict(latest: QcRow | null) {
  if (latest) {
    store.setEntry(latest)
    editingId.value = typeof latest.id === 'string' || typeof latest.id === 'number' ? latest.id : null
  }
  void reload()
}

async function runAction(action: string, row: QcRow) {
  if (typeof row.id !== 'string' && typeof row.id !== 'number') return
  if (isRowBusy(row)) return
  const key = rowActionKey(row.id, action)
  errorMessage.value = ''
  pendingActions.value[key] = true
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({
        action,
        expectedVersion: Number(row.version ?? 1),
        requestId: globalThis.crypto?.randomUUID?.() ?? `qc-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      }),
    })
    const payload = await response.json().catch(() => null) as
      | { ok?: boolean; message?: string; entry?: QcRow }
      | null
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '质量控制动作未生效，请刷新后重试')
    }
    if (payload.entry) store.setEntry(payload.entry)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '质量控制操作失败'
    await reload()
  } finally {
    delete pendingActions.value[key]
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (filters.keyword) params.set('keyword', filters.keyword)
  if (filters.category) params.set('category', filters.category)
  if (filters.status) params.set('status', filters.status)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error('质控样品列表读取失败')
    }
    const payload = await response.json() as { items?: QcRow[]; total?: number }
    store.setRows(payload.items ?? [], payload.total ?? (payload.items ?? []).length)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '质量控制列表读取失败'
  }
}

onMounted(reload)
</script>

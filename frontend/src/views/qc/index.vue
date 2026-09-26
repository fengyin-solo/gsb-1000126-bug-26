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
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">编辑</button>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无质量控制数据，可先登记质控样品</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条质量控制记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 详情抽屉：详情与列表始终读同一条服务端记录，保存后两边一起对齐 -->
    <div v-if="detailVisible" class="drawer-mask" @click.self="closeDetail">
      <aside class="drawer">
        <header class="drawer-head">
          <h3>质控样品详情</h3>
          <span v-if="detail" class="drawer-sub">记录 #{{ detail.id }} · 版本 v{{ baseVersion }}</span>
        </header>
        <p v-if="detailLoading" class="drawer-tip">正在读取最新记录…</p>
        <form v-else-if="detail" class="drawer-form" @submit.prevent="saveEntry(false)">
          <label v-for="field in editableFields" :key="field" class="field-row">
            <span>
              {{ field }}
              <em v-if="requiredFields.includes(field)" class="required-mark">*</em>
            </span>
            <input v-model="form[field]" :placeholder="`请输入${field}`" />
          </label>

          <div v-if="conflictEntry" class="conflict-panel">
            <p class="conflict-title">保存冲突：该记录已被他人修改，原记录不会被覆盖，请核对后再决定。</p>
            <table class="conflict-table">
              <thead>
                <tr><th>字段</th><th>服务器当前值</th><th>我的修改</th></tr>
              </thead>
              <tbody>
                <tr v-for="field in conflictFields" :key="field">
                  <td>{{ field }}</td>
                  <td>{{ conflictEntry[field] ?? '—' }}</td>
                  <td>{{ form[field] || '—' }}</td>
                </tr>
              </tbody>
            </table>
            <div class="conflict-actions">
              <button class="btn" type="button" @click="discardMyChanges">放弃修改，加载最新</button>
              <button class="btn primary" type="button" :disabled="saving" @click="saveEntry(true)">
                确认覆盖并保存
              </button>
            </div>
          </div>

          <footer class="drawer-foot">
            <span v-if="saveMessage" class="drawer-message" :class="{ 'error-text': saveMessageKind === 'error' }">
              {{ saveMessage }}
            </span>
            <span class="drawer-buttons">
              <button class="btn primary" type="submit" :disabled="saving">
                {{ saving ? '保存中…' : '保存' }}
              </button>
              <button class="btn ghost" type="button" @click="closeDetail">关闭</button>
            </span>
          </footer>
        </form>
        <p v-else class="drawer-tip error-text">{{ saveMessage || '质控样品详情读取失败' }}</p>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type ActionPayload = { ok?: boolean; message?: string; entry?: Row | null }

const ENDPOINT = '/api/qc'
const columns = ["质控编号", "质控类别", "标准值", "允许偏差", "实测值", "判定结果", "检测日期", "质控状态"]
const actions = ["检测质控", "确认受控", "标记失控"]
const statuses = ["待检测", "检测中", "受控", "失控"]
const stats = [{"label": "待检质控品", "value": 0}, {"label": "受控质控品", "value": 0}, {"label": "失控质控品", "value": 0}]
// 可保存字段与后端白名单一致，按字段名提交，杜绝位置错位
const editableFields = columns.slice()
const requiredFields = ["质控编号", "质控类别", "标准值"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

// 详情抽屉状态：detail 是服务端权威记录，form 是编辑草稿
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<Row | null>(null)
const form = ref<Record<string, string>>({})
const baseVersion = ref(0)
const saving = ref(false)
const saveMessage = ref('')
const saveMessageKind = ref<'ok' | 'error'>('ok')
const conflictEntry = ref<Row | null>(null)
// 同一份草稿的保存共用幂等键：网络中断后重试不会产生重复写入
let requestId = newRequestId()

function newRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `rid-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

// 草稿一旦变化就是新的逻辑保存，换新的幂等键；同一份草稿的重试沿用旧键
watch(form, () => {
  requestId = newRequestId()
}, { deep: true })

const conflictFields = computed(() => {
  if (!conflictEntry.value) {
    return []
  }
  const current = conflictEntry.value
  const differs = editableFields.filter((field) => String(current[field] ?? '') !== (form.value[field] ?? ''))
  return differs.length ? differs : editableFields
})

function setSaveMessage(message: string, kind: 'ok' | 'error') {
  saveMessage.value = message
  saveMessageKind.value = kind
}

/** 列表行与详情都以后端返回的同一条记录为准，避免一边新一边旧。 */
function applyServerEntry(entry: Row) {
  detail.value = entry
  baseVersion.value = Number(entry.version ?? 0)
  form.value = Object.fromEntries(editableFields.map((field) => [field, String(entry[field] ?? '')]))
  const index = rows.value.findIndex((row) => Number(row.id) === Number(entry.id))
  if (index >= 0) {
    rows.value[index] = { ...rows.value[index], ...entry }
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '质控样品登记入口尚未接入审批流'
}

async function openDetail(row: Row) {
  detailVisible.value = true
  conflictEntry.value = null
  saveMessage.value = ''
  await reloadDetail(Number(row.id))
}

function closeDetail() {
  detailVisible.value = false
  detail.value = null
  conflictEntry.value = null
  saveMessage.value = ''
}

async function reloadDetail(id: number) {
  detailLoading.value = true
  try {
    const response = await request(`${ENDPOINT}/${id}`)
    if (!response.ok) {
      throw new Error('质控样品详情读取失败')
    }
    const entry = (await response.json()) as Row
    conflictEntry.value = null
    applyServerEntry(entry)
  } catch (error) {
    detail.value = null
    setSaveMessage(error instanceof Error ? error.message : '质控样品详情读取失败', 'error')
  } finally {
    detailLoading.value = false
  }
}

async function saveEntry(forceOverwrite: boolean) {
  // 保存中禁止重复提交；网络层重试由同一个幂等键兜底
  if (saving.value || !detail.value) {
    return
  }
  const id = Number(detail.value.id)
  saving.value = true
  saveMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${id}`, {
      method: 'PUT',
      body: JSON.stringify({
        values: { ...form.value },
        // 确认覆盖时基于刚取回的最新版本；版本仍不一致会再次 409，不会静默覆盖
        base_version: forceOverwrite && conflictEntry.value
          ? Number(conflictEntry.value.version ?? 0)
          : baseVersion.value,
        request_id: requestId,
      }),
    })
    const payload = (await response.json().catch(() => null)) as ActionPayload | null
    if (response.ok && payload?.ok && payload.entry) {
      conflictEntry.value = null
      applyServerEntry(payload.entry)
      setSaveMessage(payload.message || '质控样品已保存', 'ok')
      return
    }
    if (response.status === 409 && payload?.entry) {
      conflictEntry.value = payload.entry
      setSaveMessage(payload.message || '该记录已被他人修改，请核对后再保存', 'error')
      return
    }
    setSaveMessage(payload?.message || '质控样品保存失败', 'error')
  } catch {
    // 网络异常中断：保存结果未知，先重新读取权威记录再下结论
    await reconcileAfterInterrupt(id)
  } finally {
    saving.value = false
  }
}

/** 异常中断后重新读取：已生效则对齐两边，未生效则保留草稿允许安全重试。 */
async function reconcileAfterInterrupt(id: number) {
  try {
    const response = await request(`${ENDPOINT}/${id}`)
    if (!response.ok) {
      throw new Error('质控样品重新读取失败')
    }
    const current = (await response.json()) as Row
    const landed = Number(current.version ?? 0) > baseVersion.value
      && editableFields.every((field) => String(current[field] ?? '') === (form.value[field] ?? ''))
    if (landed) {
      conflictEntry.value = null
      applyServerEntry(current)
      setSaveMessage('网络中断后重新读取确认：修改已保存，列表与详情已对齐', 'ok')
    } else if (Number(current.version ?? 0) !== baseVersion.value) {
      conflictEntry.value = current
      setSaveMessage('网络中断且记录已被他人修改：已取出最新记录，请核对后再保存', 'error')
    } else {
      setSaveMessage('保存请求未送达，修改未生效；可直接重试，重复提交不会产生重复记录', 'error')
    }
  } catch {
    setSaveMessage('保存结果未知，且暂时无法重新读取记录；请稍后刷新核对，避免盲目重复操作', 'error')
  }
}

function discardMyChanges() {
  if (!conflictEntry.value) {
    return
  }
  applyServerEntry(conflictEntry.value)
  conflictEntry.value = null
  setSaveMessage('已加载最新记录，未覆盖他人修改', 'ok')
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = (await response.json().catch(() => null)) as ActionPayload | null
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '质量控制动作未生效，请稍后重试')
    }
    await reload()
    // 详情抽屉若正打开同一条记录，同步刷新，保证两处结论一致
    if (detailVisible.value && detail.value && Number(detail.value.id) === Number(row.id)) {
      await reloadDetail(Number(row.id))
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '质量控制操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('质控样品列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '质量控制列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.drawer-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.35);
  display: flex;
  justify-content: flex-end;
  z-index: 20;
}
.drawer {
  width: 420px;
  max-width: 92vw;
  height: 100%;
  background: #fff;
  padding: 16px 20px;
  overflow-y: auto;
  box-shadow: -4px 0 16px rgba(15, 23, 42, 0.12);
}
.drawer-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  border-bottom: 1px solid var(--border);
  padding-bottom: 8px;
}
.drawer-head h3 {
  margin: 0;
  font-size: 15px;
}
.drawer-sub {
  color: var(--muted);
  font-size: 12px;
}
.drawer-tip {
  color: var(--muted);
  font-size: 13px;
}
.drawer-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 12px;
}
.field-row span {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 2px;
}
.field-row input {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 13px;
}
.required-mark {
  color: #b42318;
  font-style: normal;
  margin-left: 2px;
}
.conflict-panel {
  border: 1px solid #f0b429;
  background: #fffaeb;
  border-radius: 8px;
  padding: 10px 12px;
}
.conflict-title {
  margin: 0 0 8px;
  font-size: 13px;
  color: #b42318;
}
.conflict-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.conflict-table th,
.conflict-table td {
  border: 1px solid var(--border);
  padding: 4px 6px;
  text-align: left;
}
.conflict-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.drawer-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}
.drawer-message {
  font-size: 12px;
  color: #067647;
}
.drawer-buttons {
  display: flex;
  gap: 8px;
  margin-left: auto;
}
</style>

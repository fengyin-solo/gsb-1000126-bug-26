import { defineStore } from 'pinia'

export type QcRow = Record<string, string | number | boolean | null>

type QcState = {
  rows: QcRow[]
  total: number
  rowCache: Record<string, QcRow>
}

const rowKey = (id: unknown) => String(id)
const isRecordId = (id: unknown): id is string | number => typeof id === 'string' || typeof id === 'number'

export const useQcStore = defineStore('qc', {
  state: (): QcState => ({
    rows: [],
    total: 0,
    rowCache: {},
  }),
  actions: {
    setRows(rows: QcRow[], total: number) {
      this.rows = rows.map((row) => ({ ...row }))
      this.total = total
      rows.forEach((row) => {
        if (isRecordId(row.id)) {
          this.rowCache[rowKey(row.id)] = { ...row }
        }
      })
    },
    setEntry(entry: QcRow) {
      if (!isRecordId(entry.id)) return
      this.rowCache[rowKey(entry.id)] = { ...entry }
      const index = this.rows.findIndex((row) => rowKey(row.id) === rowKey(entry.id))
      if (index >= 0) {
        this.rows[index] = { ...entry }
      }
    },
    removeEntry(id: string | number) {
      const key = rowKey(id)
      delete this.rowCache[key]
      this.rows = this.rows.filter((row) => String(row.id) !== key)
    },
    getEntry(id: string | number) {
      return this.rowCache[rowKey(id)]
    },
    clearEntry(id: string | number) {
      delete this.rowCache[rowKey(id)]
    },
  },
})

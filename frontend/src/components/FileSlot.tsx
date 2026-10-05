// One document upload slot: click or drag-and-drop, shows the chosen file, can be cleared.
import { FileText, Upload, X } from 'lucide-react'
import { useRef, useState, type DragEvent } from 'react'
import { cx } from '../lib/style'

const ACCEPT = '.pdf,.png,.jpg,.jpeg'

function size(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function FileSlot({ label, hint, file, onChange }: {
  label: string
  hint: string
  file: File | undefined
  onChange: (file: File | undefined) => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  function drop(e: DragEvent) {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) onChange(f)
  }

  return (
    <div>
      <div className="mb-1.5 text-sm font-medium text-slate-700">{label}</div>
      {file ? (
        <div className="flex items-center gap-3 rounded-lg bg-white px-3 py-2.5 ring-1 ring-slate-300">
          <FileText className="size-5 shrink-0 text-brand-700" />
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm text-slate-900">{file.name}</div>
            <div className="text-xs text-slate-500">{size(file.size)}</div>
          </div>
          <button type="button" onClick={() => onChange(undefined)} aria-label={`Remove ${label}`}
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
            <X className="size-4" />
          </button>
        </div>
      ) : (
        <button type="button" onClick={() => input.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)} onDrop={drop}
          className={cx('flex w-full flex-col items-center gap-1 rounded-lg border-2 border-dashed px-3 py-5 text-sm transition-colors',
            dragging ? 'border-brand-600 bg-brand-50 text-brand-800' : 'border-slate-300 text-slate-500 hover:border-slate-400 hover:bg-white')}>
          <Upload className="size-5" />
          <span><span className="font-medium text-brand-700">Choose a file</span> or drag it here</span>
          <span className="text-xs text-slate-400">{hint}</span>
        </button>
      )}
      <input ref={input} type="file" accept={ACCEPT} className="hidden"
        onChange={(e) => { onChange(e.target.files?.[0]); e.target.value = '' }} />
    </div>
  )
}

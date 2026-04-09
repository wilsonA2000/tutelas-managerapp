import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  Mail, RefreshCw, Loader2, Inbox,
  AlertCircle, ExternalLink, Search,
  Paperclip, ChevronLeft, X, User,
  Calendar, ArrowRight, FileText, Package,
} from 'lucide-react'
import { getEmails, getEmail, checkInbox, getGmailStats, syncAllEmails, getEmailPackage } from '../services/api'
import { useNavigate } from 'react-router-dom'

interface EmailItem {
  id: number
  subject: string
  sender: string
  received_at: string
  status: string
  case_id?: number
  case_folder?: string
  snippet?: string
  attachments_count?: number
}

interface EmailDetail {
  id: number
  subject: string
  sender: string
  date_received: string
  body: string
  status: string
  case_id?: number
  case_folder?: string
  case_accionante?: string
  attachments?: { filename: string; saved_path?: string }[]
}

const STATUS_STYLES: Record<string, string> = {
  pendiente: 'bg-amber-100 text-amber-700 border-amber-200',
  procesado: 'bg-blue-100 text-blue-700 border-blue-200',
  asignado: 'bg-green-100 text-green-700 border-green-200',
  ignorado: 'bg-gray-100 text-gray-500 border-gray-200',
}

function StatusBadge({ status }: { status: string }) {
  const labels: Record<string, string> = {
    pendiente: 'Pendiente', procesado: 'Procesado',
    asignado: 'Asignado', ignorado: 'Ignorado',
  }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border ${STATUS_STYLES[status] ?? 'bg-gray-100 text-gray-500 border-gray-200'}`}>
      {labels[status] ?? status}
    </span>
  )
}

export default function Emails() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [page, setPage] = useState(1)

  const emailsQ = useQuery({
    queryKey: ['emails', { search, status, page }],
    queryFn: () => getEmails({ search, status, page, per_page: 30 }),
    placeholderData: (prev) => prev,
  })

  const detailQ = useQuery({
    queryKey: ['email-detail', selectedId],
    queryFn: () => getEmail(selectedId!),
    enabled: !!selectedId,
  })

  // v4.8 Provenance: paquete completo (email + documents hijos vinculados)
  const packageQ = useQuery({
    queryKey: ['email-package', selectedId],
    queryFn: () => getEmailPackage(selectedId!),
    enabled: !!selectedId,
  })

  const gmailStatsQ = useQuery({
    queryKey: ['gmail-stats'],
    queryFn: getGmailStats,
    refetchInterval: 60000,
    staleTime: 30000,
  })

  const checkMutation = useMutation({
    mutationFn: checkInbox,
    onSuccess: (data) => {
      if (data.status === 'started') {
        toast.success('Revision de Gmail iniciada...')
        setTimeout(() => { qc.invalidateQueries({ queryKey: ['emails'] }); qc.invalidateQueries({ queryKey: ['gmail-stats'] }) }, 5000)
        setTimeout(() => { qc.invalidateQueries({ queryKey: ['emails'] }); qc.invalidateQueries({ queryKey: ['gmail-stats'] }) }, 15000)
        setTimeout(() => { qc.invalidateQueries({ queryKey: ['emails'] }); qc.invalidateQueries({ queryKey: ['gmail-stats'] }) }, 30000)
      } else if (data.status === 'running') {
        toast('Ya hay una revision en progreso', { icon: '\u2139\uFE0F' })
      }
    },
    onError: () => toast.error('Error al iniciar revision'),
  })

  const syncMutation = useMutation({
    mutationFn: syncAllEmails,
    onSuccess: (data) => {
      if (data.status === 'started') {
        toast.success('Sincronizacion completa iniciada...')
        setTimeout(() => { qc.invalidateQueries({ queryKey: ['emails'] }); qc.invalidateQueries({ queryKey: ['gmail-stats'] }) }, 10000)
        setTimeout(() => { qc.invalidateQueries({ queryKey: ['emails'] }); qc.invalidateQueries({ queryKey: ['gmail-stats'] }) }, 30000)
        setTimeout(() => { qc.invalidateQueries({ queryKey: ['emails'] }); qc.invalidateQueries({ queryKey: ['gmail-stats'] }) }, 60000)
      } else if (data.status === 'running') {
        toast('Ya hay una sincronizacion en progreso', { icon: '\u2139\uFE0F' })
      }
    },
    onError: () => toast.error('Error al iniciar sincronizacion'),
  })

  const emails: EmailItem[] = emailsQ.data?.items ?? []
  const total = emailsQ.data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / 30))
  const detail: EmailDetail | null = detailQ.data ?? null

  function formatDate(iso: string) {
    try {
      const d = new Date(iso)
      const today = new Date()
      if (d.toDateString() === today.toDateString()) {
        return d.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })
      }
      return d.toLocaleDateString('es-CO', { day: '2-digit', month: 'short' })
    } catch { return iso }
  }

  function formatFullDate(iso: string) {
    try {
      return new Date(iso).toLocaleString('es-CO', {
        weekday: 'long', day: '2-digit', month: 'long', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      })
    } catch { return iso }
  }

  function extractSenderName(sender: string) {
    const match = sender.match(/^"?([^"<]+)"?\s*</)
    return match ? match[1].trim() : sender.split('@')[0]
  }

  return (
    <div className="flex flex-col h-[calc(100vh-64px)]">
      {/* Top bar */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-gray-200 bg-white flex-shrink-0">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-bold text-gray-800">Correos</h1>
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-[#1A5276] bg-blue-50 px-2 py-0.5 rounded-full">
              {total} en sistema
            </span>
            {gmailStatsQ.data && (
              <>
                <span className="text-xs text-gray-400">|</span>
                <span className="text-xs font-semibold text-gray-600 bg-gray-100 px-2 py-0.5 rounded-full">
                  {gmailStatsQ.data.gmail_total} en Gmail
                </span>
                {gmailStatsQ.data.gmail_unread > 0 && (
                  <span className="text-xs font-semibold text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full">
                    {gmailStatsQ.data.gmail_unread} no leidos
                  </span>
                )}
                {gmailStatsQ.data.faltan > 0 && (
                  <span className="text-[10px] text-red-500">
                    ({gmailStatsQ.data.faltan} pendientes en Gmail)
                  </span>
                )}
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {gmailStatsQ.data?.faltan > 0 && (
            <button
              onClick={() => syncMutation.mutate()}
              disabled={syncMutation.isPending}
              className="flex items-center gap-2 px-3 py-2 bg-amber-500 text-white text-sm font-medium rounded-lg hover:bg-amber-600 disabled:opacity-50 transition-colors shadow-sm"
            >
              {syncMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
              {syncMutation.isPending ? 'Sincronizando...' : `Sync ${gmailStatsQ.data.faltan} faltantes`}
            </button>
          )}
          <button
            onClick={() => checkMutation.mutate()}
            disabled={checkMutation.isPending}
            className="flex items-center gap-2 px-3 py-2 bg-[#1A5276] text-white text-sm font-medium rounded-lg hover:bg-[#154360] disabled:opacity-50 transition-colors shadow-sm"
          >
            {checkMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Inbox size={14} />}
            {checkMutation.isPending ? 'Revisando...' : 'Revisar Bandeja'}
          </button>
        </div>
      </div>

      {/* Search bar */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-gray-100 bg-gray-50 flex-shrink-0">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={14} />
          <input
            type="text"
            placeholder="Buscar por asunto, remitente, contenido..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1) }}
            className="w-full pl-9 pr-4 py-1.5 text-sm border border-gray-200 rounded-lg bg-white focus:border-[#1A5276] focus:outline-none focus:ring-1 focus:ring-[#1A5276]/20"
          />
        </div>
        <select
          value={status}
          onChange={(e) => { setStatus(e.target.value); setPage(1) }}
          className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white"
        >
          <option value="">Todos</option>
          <option value="PENDIENTE">Pendiente</option>
          <option value="ASIGNADO">Asignado</option>
          <option value="IGNORADO">Ignorado</option>
        </select>
        <button onClick={() => qc.invalidateQueries({ queryKey: ['emails'] })} className="p-1.5 text-gray-400 hover:text-gray-600">
          <RefreshCw size={14} className={emailsQ.isFetching ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Main content: list + detail */}
      <div className="flex flex-1 overflow-hidden">
        {/* Email list */}
        <div className={`${selectedId ? 'hidden md:flex' : 'flex'} flex-col w-full md:w-[380px] lg:w-[420px] border-r border-gray-200 bg-white overflow-hidden flex-shrink-0`}>
          {emailsQ.isError ? (
            <div className="flex items-center gap-2 text-red-500 text-sm p-5">
              <AlertCircle size={16} /> Error al cargar correos
            </div>
          ) : emailsQ.isLoading ? (
            <div className="flex items-center justify-center py-10">
              <Loader2 size={24} className="animate-spin text-[#1A5276]" />
            </div>
          ) : emails.length === 0 ? (
            <div className="text-center py-12">
              <Mail size={36} className="mx-auto text-gray-300 mb-3" />
              <p className="text-sm text-gray-500">No hay correos</p>
            </div>
          ) : (
            <>
              <div className="flex-1 overflow-y-auto divide-y divide-gray-100">
                {emails.map((email) => (
                  <button
                    key={email.id}
                    onClick={() => setSelectedId(email.id)}
                    className={`w-full text-left px-4 py-3 hover:bg-blue-50/50 transition-colors ${
                      selectedId === email.id ? 'bg-blue-50 border-l-2 border-l-[#1A5276]' : 'border-l-2 border-l-transparent'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="text-xs font-semibold text-gray-700 truncate">
                            {extractSenderName(email.sender)}
                          </span>
                          <StatusBadge status={email.status} />
                        </div>
                        <p className="text-sm font-medium text-gray-800 truncate">
                          {email.subject || '(Sin asunto)'}
                        </p>
                        <p className="text-xs text-gray-400 truncate mt-0.5">
                          {email.snippet || ''}
                        </p>
                      </div>
                      <div className="flex flex-col items-end gap-1 flex-shrink-0">
                        <span className="text-[10px] text-gray-400 whitespace-nowrap">
                          {formatDate(email.received_at)}
                        </span>
                        {(email.attachments_count ?? 0) > 0 && (
                          <Paperclip size={11} className="text-gray-300" />
                        )}
                      </div>
                    </div>
                    {email.case_folder && (
                      <div className="mt-1">
                        <span className="text-[10px] font-mono text-[#1A5276] bg-blue-50 px-1.5 py-0.5 rounded">
                          {email.case_folder}
                        </span>
                      </div>
                    )}
                  </button>
                ))}
              </div>
              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between px-4 py-2 border-t border-gray-100 bg-gray-50 text-xs text-gray-500">
                  <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="disabled:opacity-30">
                    <ChevronLeft size={14} />
                  </button>
                  <span>{page}/{totalPages}</span>
                  <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)} className="disabled:opacity-30">
                    <ChevronLeft size={14} className="rotate-180" />
                  </button>
                </div>
              )}
            </>
          )}
        </div>

        {/* Email detail / reading pane */}
        <div className={`${selectedId ? 'flex' : 'hidden md:flex'} flex-1 flex-col bg-gray-50 overflow-hidden`}>
          {!selectedId ? (
            <div className="flex flex-col items-center justify-center h-full text-gray-400">
              <Mail size={48} className="mb-3 text-gray-300" />
              <p className="text-sm">Seleccione un correo para leerlo</p>
            </div>
          ) : detailQ.isLoading ? (
            <div className="flex items-center justify-center h-full">
              <Loader2 size={24} className="animate-spin text-[#1A5276]" />
            </div>
          ) : detail ? (
            <>
              {/* Detail header */}
              <div className="px-6 py-4 bg-white border-b border-gray-200 flex-shrink-0">
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 md:hidden mb-2">
                      <button onClick={() => setSelectedId(null)} className="p-1 text-gray-400 hover:text-gray-600">
                        <ChevronLeft size={18} />
                      </button>
                      <span className="text-xs text-gray-400">Volver</span>
                    </div>
                    <h2 className="text-lg font-semibold text-gray-800">{detail.subject || '(Sin asunto)'}</h2>
                    <div className="flex items-center gap-3 mt-2 text-sm">
                      <div className="flex items-center gap-1.5 text-gray-600">
                        <User size={13} className="text-gray-400" />
                        <span className="font-medium">{extractSenderName(detail.sender)}</span>
                        <span className="text-gray-400 text-xs">&lt;{detail.sender.match(/<(.+?)>/)?.[1] || detail.sender}&gt;</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 mt-1.5 text-xs text-gray-400">
                      <Calendar size={11} />
                      <span>{formatFullDate(detail.date_received || '')}</span>
                    </div>
                  </div>
                  <button onClick={() => setSelectedId(null)} className="hidden md:block p-1.5 text-gray-400 hover:text-gray-600">
                    <X size={16} />
                  </button>
                </div>

                {/* Case link */}
                {detail.case_id && (
                  <div className="mt-3 flex items-center gap-2 bg-blue-50 border border-blue-100 rounded-lg px-3 py-2">
                    <ArrowRight size={12} className="text-[#1A5276]" />
                    <span className="text-xs text-gray-600">Caso asignado:</span>
                    <button
                      onClick={() => navigate(`/cases/${detail.case_id}`)}
                      className="text-xs font-mono text-[#1A5276] font-medium hover:underline"
                    >
                      {detail.case_folder || `#${detail.case_id}`}
                    </button>
                    {detail.case_accionante && (
                      <span className="text-xs text-gray-400">- {detail.case_accionante}</span>
                    )}
                  </div>
                )}

                {/* Attachments */}
                {detail.attachments && detail.attachments.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {detail.attachments.map((att, i) => (
                      <div key={i} className="flex items-center gap-1.5 bg-gray-100 rounded-lg px-2.5 py-1.5 text-xs text-gray-600">
                        <Paperclip size={11} className="text-gray-400" />
                        {att.filename}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Body */}
              <div className="flex-1 overflow-y-auto p-6">
                <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 max-w-3xl mb-4">
                  <pre className="text-sm text-gray-700 whitespace-pre-wrap font-sans leading-relaxed">
                    {detail.body || '(Sin contenido)'}
                  </pre>
                </div>

                {/* v4.8 Provenance: Paquete vinculado (documents con mismo email_id) */}
                {packageQ.data && packageQ.data.count > 0 && (
                  <div className="bg-white rounded-xl border border-indigo-200 shadow-sm p-5 max-w-3xl">
                    <div className="flex items-center gap-2 mb-3 text-indigo-700">
                      <Package size={18} />
                      <h3 className="text-sm font-semibold">
                        Paquete inmutable ({packageQ.data.count} {packageQ.data.count === 1 ? 'documento' : 'documentos'})
                      </h3>
                    </div>
                    <p className="text-xs text-gray-500 mb-3">
                      Estos documentos estan vinculados a este correo de origen. Al mover cualquiera a otro caso, todos viajan juntos automaticamente.
                    </p>
                    <div className="space-y-2">
                      {packageQ.data.documents.map((doc: any) => (
                        <div
                          key={doc.id}
                          className="flex items-center justify-between gap-3 p-2.5 rounded-lg border border-gray-100 hover:border-indigo-300 hover:bg-indigo-50 transition-colors"
                        >
                          <div className="flex items-center gap-2 min-w-0 flex-1">
                            <FileText size={14} className="text-indigo-500 shrink-0" />
                            <div className="min-w-0">
                              <div className="text-xs font-medium text-gray-800 truncate">{doc.filename}</div>
                              <div className="text-[10px] text-gray-500 mt-0.5">
                                {doc.doc_type} · {doc.text_length ? `${doc.text_length} chars` : 'sin texto'} · {doc.verificacion || 'sin verificar'}
                              </div>
                            </div>
                          </div>
                          <a
                            href={`/api/documents/${doc.id}/preview`}
                            target="_blank"
                            rel="noreferrer"
                            className="text-[10px] text-indigo-600 hover:text-indigo-800 shrink-0 px-2 py-1 rounded hover:bg-indigo-100"
                          >
                            Ver
                          </a>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {packageQ.data && packageQ.data.count === 0 && (
                  <div className="bg-amber-50 rounded-xl border border-amber-200 p-3 max-w-3xl text-xs text-amber-700">
                    Este correo no tiene documentos vinculados (posible legacy pre-v4.8).
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="flex items-center justify-center h-full text-gray-400">
              <p className="text-sm">Error al cargar el correo</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

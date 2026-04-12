import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  Mail, RefreshCw, Loader2, Inbox,
  AlertCircle, Search,
  Paperclip, ChevronLeft, X, User,
  Calendar, ArrowRight, FileText, Package,
} from 'lucide-react'
import { getEmails, getEmail, checkInbox, getGmailStats, syncAllEmails, getEmailPackage } from '../services/api'
import { useNavigate } from 'react-router-dom'
import PageHeader from '@/components/PageHeader'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

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
  pendiente: 'bg-amber-50 text-amber-700 border-amber-200',
  procesado: 'bg-blue-50 text-blue-700 border-blue-200',
  asignado: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  ignorado: 'bg-muted text-muted-foreground border-border',
}

const STATUS_LABELS: Record<string, string> = {
  pendiente: 'Pendiente',
  procesado: 'Procesado',
  asignado: 'Asignado',
  ignorado: 'Ignorado',
}

function EmailStatusBadge({ status }: { status: string }) {
  const key = status.toLowerCase()
  return (
    <Badge
      variant="outline"
      className={cn(
        'text-[10px] font-semibold px-1.5 py-0.5 rounded-md',
        STATUS_STYLES[key] ?? 'bg-muted text-muted-foreground border-border'
      )}
    >
      {STATUS_LABELS[key] ?? status}
    </Badge>
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
        toast.success('Sincronización completa iniciada...')
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

  const headerActions = (
    <div className="flex items-center gap-2">
      {gmailStatsQ.data?.faltan > 0 && (
        <Button
          variant="outline"
          size="sm"
          onClick={() => syncMutation.mutate()}
          disabled={syncMutation.isPending}
          className="border-amber-300 text-amber-700 hover:bg-amber-50 hover:text-amber-800"
        >
          {syncMutation.isPending
            ? <Loader2 size={14} className="animate-spin mr-1.5" />
            : <RefreshCw size={14} className="mr-1.5" />}
          {syncMutation.isPending ? 'Sincronizando...' : `Sync ${gmailStatsQ.data.faltan} faltantes`}
        </Button>
      )}
      <Button
        size="sm"
        onClick={() => checkMutation.mutate()}
        disabled={checkMutation.isPending}
      >
        {checkMutation.isPending
          ? <Loader2 size={14} className="animate-spin mr-1.5" />
          : <Inbox size={14} className="mr-1.5" />}
        {checkMutation.isPending ? 'Revisando...' : 'Revisar Bandeja'}
      </Button>
    </div>
  )

  return (
    <div className="flex flex-col h-[calc(100vh-64px)]">
      {/* Top bar */}
      <div className="flex-shrink-0 px-6 py-4 border-b border-border bg-card">
        <PageHeader
          title="Correos"
          icon={Mail}
          subtitle={undefined}
          action={headerActions}
        />
        {/* Stats row */}
        <div className="flex items-center gap-2 mt-2 ml-[3.25rem]">
          <Badge variant="outline" className="text-[11px] font-semibold text-primary bg-primary/5 border-primary/20">
            {total} en sistema
          </Badge>
          {gmailStatsQ.data && (
            <>
              <span className="text-muted-foreground/40 text-xs">|</span>
              <Badge variant="outline" className="text-[11px] text-muted-foreground">
                {gmailStatsQ.data.gmail_total} en Gmail
              </Badge>
              {gmailStatsQ.data.gmail_unread > 0 && (
                <Badge variant="outline" className="text-[11px] font-semibold text-amber-700 bg-amber-50 border-amber-200">
                  {gmailStatsQ.data.gmail_unread} no leidos
                </Badge>
              )}
              {gmailStatsQ.data.faltan > 0 && (
                <span className="text-[10px] text-destructive font-medium">
                  ({gmailStatsQ.data.faltan} pendientes en Gmail)
                </span>
              )}
            </>
          )}
        </div>
      </div>

      {/* Search / filter bar */}
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border bg-muted/30 flex-shrink-0">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" size={14} />
          <Input
            type="text"
            placeholder="Buscar por asunto, remitente, contenido..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1) }}
            className="pl-9 h-8 text-sm bg-card"
          />
        </div>
        <select
          value={status}
          onChange={(e) => { setStatus(e.target.value); setPage(1) }}
          className="text-xs h-8 border border-input rounded-md px-2 bg-card text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
        >
          <option value="">Todos</option>
          <option value="PENDIENTE">Pendiente</option>
          <option value="ASIGNADO">Asignado</option>
          <option value="IGNORADO">Ignorado</option>
        </select>
        <button
          onClick={() => qc.invalidateQueries({ queryKey: ['emails'] })}
          className="p-1.5 text-muted-foreground hover:text-foreground transition-colors"
        >
          <RefreshCw size={14} className={emailsQ.isFetching ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Main content: list + detail */}
      <div className="flex flex-1 overflow-hidden">
        {/* Email list */}
        <div className={cn(
          'flex-col w-full md:w-[380px] lg:w-[420px] border-r border-border bg-card overflow-hidden flex-shrink-0',
          selectedId ? 'hidden md:flex' : 'flex'
        )}>
          {emailsQ.isError ? (
            <div className="flex items-center gap-2 text-destructive text-sm p-5">
              <AlertCircle size={16} /> Error al cargar correos
            </div>
          ) : emailsQ.isLoading ? (
            <div className="flex items-center justify-center py-10">
              <Loader2 size={24} className="animate-spin text-primary" />
            </div>
          ) : emails.length === 0 ? (
            <div className="text-center py-12">
              <Mail size={36} className="mx-auto text-muted-foreground/30 mb-3" />
              <p className="text-sm text-muted-foreground">No hay correos</p>
            </div>
          ) : (
            <>
              <div className="flex-1 overflow-y-auto divide-y divide-border">
                {emails.map((email) => (
                  <button
                    key={email.id}
                    onClick={() => setSelectedId(email.id)}
                    className={cn(
                      'w-full text-left px-4 py-3 hover:bg-accent transition-colors border-l-2',
                      selectedId === email.id
                        ? 'bg-accent border-l-primary'
                        : 'border-l-transparent'
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="text-xs font-semibold text-foreground truncate">
                            {extractSenderName(email.sender)}
                          </span>
                          <EmailStatusBadge status={email.status} />
                        </div>
                        <p className="text-sm font-medium text-foreground truncate">
                          {email.subject || '(Sin asunto)'}
                        </p>
                        <p className="text-xs text-muted-foreground truncate mt-0.5">
                          {email.snippet || ''}
                        </p>
                      </div>
                      <div className="flex flex-col items-end gap-1 flex-shrink-0">
                        <span className="text-[10px] text-muted-foreground whitespace-nowrap">
                          {formatDate(email.received_at)}
                        </span>
                        {(email.attachments_count ?? 0) > 0 && (
                          <Paperclip size={11} className="text-muted-foreground/40" />
                        )}
                      </div>
                    </div>
                    {email.case_folder && (
                      <div className="mt-1">
                        <span className="text-[10px] font-mono text-primary bg-primary/8 px-1.5 py-0.5 rounded">
                          {email.case_folder}
                        </span>
                      </div>
                    )}
                  </button>
                ))}
              </div>
              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between px-4 py-2 border-t border-border bg-muted/30 text-xs text-muted-foreground">
                  <button
                    disabled={page <= 1}
                    onClick={() => setPage(p => p - 1)}
                    className="disabled:opacity-30 hover:text-foreground transition-colors"
                  >
                    <ChevronLeft size={14} />
                  </button>
                  <span>{page}/{totalPages}</span>
                  <button
                    disabled={page >= totalPages}
                    onClick={() => setPage(p => p + 1)}
                    className="disabled:opacity-30 hover:text-foreground transition-colors"
                  >
                    <ChevronLeft size={14} className="rotate-180" />
                  </button>
                </div>
              )}
            </>
          )}
        </div>

        {/* Email detail / reading pane */}
        <div className={cn(
          'flex-1 flex-col bg-muted/20 overflow-hidden',
          selectedId ? 'flex' : 'hidden md:flex'
        )}>
          {!selectedId ? (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground/50">
              <Mail size={48} className="mb-3" />
              <p className="text-sm text-muted-foreground">Seleccione un correo para leerlo</p>
            </div>
          ) : detailQ.isLoading ? (
            <div className="flex items-center justify-center h-full">
              <Loader2 size={24} className="animate-spin text-primary" />
            </div>
          ) : detail ? (
            <>
              {/* Detail header */}
              <div className="px-6 py-4 bg-card border-b border-border flex-shrink-0">
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 md:hidden mb-2">
                      <button
                        onClick={() => setSelectedId(null)}
                        className="p-1 text-muted-foreground hover:text-foreground transition-colors"
                      >
                        <ChevronLeft size={18} />
                      </button>
                      <span className="text-xs text-muted-foreground">Volver</span>
                    </div>
                    <h2 className="text-base font-semibold text-foreground">
                      {detail.subject || '(Sin asunto)'}
                    </h2>
                    <div className="flex items-center gap-3 mt-2 text-sm">
                      <div className="flex items-center gap-1.5 text-muted-foreground">
                        <User size={13} />
                        <span className="font-medium text-foreground">
                          {extractSenderName(detail.sender)}
                        </span>
                        <span className="text-muted-foreground/60 text-xs">
                          &lt;{detail.sender.match(/<(.+?)>/)?.[1] || detail.sender}&gt;
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 mt-1.5 text-xs text-muted-foreground">
                      <Calendar size={11} />
                      <span>{formatFullDate(detail.date_received || '')}</span>
                    </div>
                  </div>
                  <button
                    onClick={() => setSelectedId(null)}
                    className="hidden md:block p-1.5 text-muted-foreground hover:text-foreground transition-colors"
                  >
                    <X size={16} />
                  </button>
                </div>

                {/* Case link */}
                {detail.case_id && (
                  <div className="mt-3 flex items-center gap-2 bg-primary/5 border border-primary/15 rounded-lg px-3 py-2">
                    <ArrowRight size={12} className="text-primary" />
                    <span className="text-xs text-muted-foreground">Caso asignado:</span>
                    <button
                      onClick={() => navigate(`/cases/${detail.case_id}`)}
                      className="text-xs font-mono text-primary font-medium hover:underline"
                    >
                      {detail.case_folder || `#${detail.case_id}`}
                    </button>
                    {detail.case_accionante && (
                      <span className="text-xs text-muted-foreground">- {detail.case_accionante}</span>
                    )}
                  </div>
                )}

                {/* Attachments */}
                {detail.attachments && detail.attachments.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {detail.attachments.map((att, i) => (
                      <div
                        key={i}
                        className="flex items-center gap-1.5 bg-muted rounded-lg px-2.5 py-1.5 text-xs text-muted-foreground border border-border"
                      >
                        <Paperclip size={11} />
                        {att.filename}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Body */}
              <div className="flex-1 overflow-y-auto p-6">
                <div className="bg-card rounded-xl border border-border shadow-sm p-6 max-w-3xl mb-4">
                  <pre className="text-sm text-foreground whitespace-pre-wrap font-sans leading-relaxed">
                    {detail.body || '(Sin contenido)'}
                  </pre>
                </div>

                {/* v4.8 Provenance: Paquete vinculado (documents con mismo email_id) */}
                {packageQ.data && packageQ.data.count > 0 && (
                  <div className="bg-card rounded-xl border border-violet-200 shadow-sm p-5 max-w-3xl">
                    <div className="flex items-center gap-2 mb-3 text-violet-700">
                      <Package size={18} />
                      <h3 className="text-sm font-semibold">
                        Documentos del correo ({packageQ.data.count}{' '}
                        {packageQ.data.count === 1 ? 'documento' : 'documentos'})
                      </h3>
                    </div>
                    <p className="text-xs text-muted-foreground mb-3">
                      Estos documentos estan vinculados a este correo de origen. Al mover cualquiera a otro caso, todos viajan juntos automáticamente.
                    </p>
                    <div className="space-y-2">
                      {packageQ.data.documents.map((doc: any) => (
                        <div
                          key={doc.id}
                          className="flex items-center justify-between gap-3 p-2.5 rounded-lg border border-border hover:border-violet-300 hover:bg-violet-50/50 transition-colors"
                        >
                          <div className="flex items-center gap-2 min-w-0 flex-1">
                            <FileText size={14} className="text-violet-500 shrink-0" />
                            <div className="min-w-0">
                              <div className="text-xs font-medium text-foreground truncate">
                                {doc.filename}
                              </div>
                              <div className="text-[10px] text-muted-foreground mt-0.5">
                                {doc.doc_type} · {doc.text_length ? `${doc.text_length} chars` : 'sin texto'} · {doc.verificacion || 'sin verificar'}
                              </div>
                            </div>
                          </div>
                          <a
                            href={`/api/documents/${doc.id}/preview`}
                            target="_blank"
                            rel="noreferrer"
                            className="text-[10px] text-violet-600 hover:text-violet-800 shrink-0 px-2 py-1 rounded hover:bg-violet-100 transition-colors"
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
            <div className="flex items-center justify-center h-full text-muted-foreground">
              <p className="text-sm">Error al cargar el correo</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

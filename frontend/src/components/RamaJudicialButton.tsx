import { useState } from 'react'
import { Landmark, Loader2, X, Download, FileText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ramaJudicialPreview, ramaJudicialFetchDocs, type RamaJudicialPreview } from '../services/api'

/** Botón + modal "Consultar Rama Judicial" (CPNU) para la ficha de un caso.
 *  Preview read-only del proceso + línea de actuaciones reales; opción de traer
 *  el expediente (documentos) por radicado. */
export default function RamaJudicialButton({ caseId }: { caseId: number }) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<RamaJudicialPreview | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [fetching, setFetching] = useState(false)
  const [fetchMsg, setFetchMsg] = useState<string | null>(null)

  async function abrir() {
    setOpen(true); setLoading(true); setErr(null); setData(null); setFetchMsg(null)
    try {
      setData(await ramaJudicialPreview(caseId))
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'No se pudo consultar la Rama Judicial')
    } finally { setLoading(false) }
  }

  async function traerExpediente() {
    setFetching(true); setFetchMsg(null)
    try {
      const r = await ramaJudicialFetchDocs(caseId, false)
      setFetchMsg(`Descargados ${r.descargados} · ya estaban ${r.dedup} · errores ${r.errors}`)
    } catch {
      setFetchMsg('Error al traer el expediente (¿rate-limit de la Rama Judicial?)')
    } finally { setFetching(false) }
  }

  return (
    <>
      <Button variant="ghost" size="icon-sm" onClick={abrir} title="Consultar Rama Judicial (CPNU)">
        <Landmark size={14} />
      </Button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
             onClick={() => setOpen(false)}>
          <div className="bg-card text-card-foreground rounded-lg shadow-xl max-w-2xl w-full max-h-[85vh] overflow-auto border border-border"
               onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-border sticky top-0 bg-card">
              <h3 className="font-semibold flex items-center gap-2"><Landmark size={16} /> Rama Judicial — CPNU</h3>
              <button onClick={() => setOpen(false)} className="text-muted-foreground hover:text-foreground"><X size={18} /></button>
            </div>

            <div className="p-5 space-y-3 text-sm">
              {loading && <div className="flex items-center gap-2 text-muted-foreground"><Loader2 size={16} className="animate-spin" /> Consultando la Rama Judicial…</div>}
              {err && <div className="text-destructive">{err}</div>}
              {data && !data.encontrado && (
                <div className="text-muted-foreground">No se encontró el proceso en CPNU{data.error ? ` (${data.error})` : ''}. Radicado: {data.rad23 || '—'}</div>
              )}
              {data && data.encontrado && (
                <>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                    <Campo k="Juzgado" v={data.juzgado} />
                    <Campo k="Departamento" v={data.departamento} />
                    <Campo k="Clase" v={data.clase} />
                    <Campo k="Fecha radicación" v={data.fecha_radicacion} />
                    <Campo k="Demandante" v={data.demandante} />
                    <Campo k="Demandado" v={data.demandado} />
                    {data.ponente && <Campo k="Ponente" v={data.ponente} />}
                    {data.es_privado && <Campo k="Privado" v="Sí (datos limitados)" />}
                  </div>

                  <div className="pt-2">
                    <div className="font-medium mb-1 flex items-center gap-1.5"><FileText size={13} /> Actuaciones ({data.actuaciones?.length ?? 0})</div>
                    <ul className="space-y-1 max-h-72 overflow-auto pr-1">
                      {(data.actuaciones ?? []).map((a, i) => (
                        <li key={i} className="border-l-2 border-border pl-2">
                          <span className="text-muted-foreground tabular-nums">{a.fecha || '—'}</span>{' '}
                          <span className="font-medium">{a.actuacion}</span>
                          {a.con_documentos && <span className="ml-1 text-xs text-primary">📎</span>}
                          {a.anotacion && <div className="text-xs text-muted-foreground">{a.anotacion}</div>}
                        </li>
                      ))}
                    </ul>
                  </div>

                  <div className="pt-3 border-t border-border flex items-center gap-3">
                    <Button size="sm" onClick={traerExpediente} disabled={fetching}>
                      {fetching ? <Loader2 size={14} className="animate-spin mr-1.5" /> : <Download size={14} className="mr-1.5" />}
                      Traer expediente
                    </Button>
                    {fetchMsg && <span className="text-xs text-muted-foreground">{fetchMsg}</span>}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function Campo({ k, v }: { k: string; v?: string | null }) {
  return <div><span className="text-muted-foreground">{k}:</span> <span className="font-medium">{v || '—'}</span></div>
}

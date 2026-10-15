import { ArrowRight, FolderOpen, UploadSimple } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState, type CSSProperties, type DragEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, type DocumentoResumen, type Registro } from '../api'
import { Badge, Boton, Cargando, Editable, Encabezado, EstadoDocumentoBadge, Fallo, Tarjeta, Vacio } from '../components/ui'
import { entidad, fecha } from '../formato'

const EN_CURSO: Record<string, true> = { en_cola: true, procesando: true }

function resumenRegistro(registros: Registro[], vacio: string): string {
  if (!registros.length) return vacio
  return registros.map((r) => `${r.archivo}: ${r.nuevo ? 'en proceso' : 'ya estaba cargado'}`).join(' · ')
}

export function Documentos() {
  const cliente = useQueryClient()
  const { data: docs, isLoading, error } = useQuery({
    queryKey: ['documentos'],
    queryFn: api.documentos,
    refetchInterval: (q) => (q.state.data?.some((d) => EN_CURSO[d.estado]) ? 2000 : false),
  })
  const actualizar = () => cliente.invalidateQueries({ queryKey: ['documentos'] })
  const subir = useMutation({ mutationFn: api.subir, onSuccess: actualizar })
  const descubrir = useMutation({ mutationFn: api.descubrir, onSuccess: actualizar })

  return (
    <>
      <Encabezado
        titulo="Documentos"
        bajada="Subí notas a los estados contables. El sistema localiza la nota de reclamaciones judiciales, extrae los indicadores, los valida y avisa si algo no cierra."
        acciones={
          <Editable>
            <Boton
              onClick={() => {
                subir.reset()
                descubrir.mutate()
              }}
              cargando={descubrir.isPending}
            >
              <FolderOpen size={16} weight="bold" /> Escanear carpeta de entrada
            </Boton>
          </Editable>
        }
      />

      <Editable>
        <ZonaDeCarga
          onArchivos={(a) => {
            descubrir.reset()
            subir.mutate(a)
          }}
          subiendo={subir.isPending}
        />
      </Editable>
      <div aria-live="polite">
        {subir.data && <p className="mt-3 text-sm text-muted">{resumenRegistro(subir.data, 'No se recibió ningún archivo.')}</p>}
        {descubrir.data && (
          <p className="mt-3 text-sm text-muted">
            {resumenRegistro(descubrir.data, 'La carpeta de entrada no tiene archivos nuevos.')}
          </p>
        )}
        <Fallo error={subir.error ?? descubrir.error} className="mt-3" />
      </div>

      <h2 className="mb-3 mt-12 text-xs font-medium uppercase tracking-[0.08em] text-muted">Cargados</h2>
      {isLoading ? (
        <Cargando />
      ) : error ? (
        <Fallo error={error} />
      ) : !docs?.length ? (
        <Vacio>Todavía no hay documentos. Subí el primero arriba.</Vacio>
      ) : (
        <Tarjeta className="divide-y divide-line overflow-hidden">
          {docs.map((d, i) => (
            <FilaDocumento key={d.id} doc={d} indice={i} />
          ))}
        </Tarjeta>
      )}
    </>
  )
}

function ZonaDeCarga({ onArchivos, subiendo }: { onArchivos: (a: File[]) => void; subiendo: boolean }) {
  const input = useRef<HTMLInputElement>(null)
  const [encima, setEncima] = useState(false)

  const soltar = (e: DragEvent) => {
    e.preventDefault()
    setEncima(false)
    if (!subiendo && e.dataTransfer.files.length) onArchivos([...e.dataTransfer.files])
  }

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label="Subir PDFs o imágenes"
      aria-disabled={subiendo}
      onDragOver={(e) => {
        e.preventDefault()
        setEncima(true)
      }}
      onDragLeave={() => setEncima(false)}
      onDrop={soltar}
      onClick={() => !subiendo && input.current?.click()}
      onKeyDown={(e) => {
        if (e.key !== 'Enter' && e.key !== ' ') return
        e.preventDefault()
        if (!subiendo) input.current?.click()
      }}
      className={`flex flex-col items-center justify-center gap-3 rounded-[10px] border border-dashed px-6 py-14 text-center transition ${
        subiendo ? 'cursor-wait' : 'cursor-pointer'
      } ${encima ? 'border-ink/40 bg-subtle' : 'border-[#d6d5d1] bg-surface hover:bg-subtle/60'}`}
    >
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-subtle text-ink">
        <UploadSimple size={20} weight="bold" />
      </div>
      <div>
        <p className="text-[15px] text-ink-strong">{subiendo ? 'Subiendo…' : 'Arrastrá PDFs o imágenes acá'}</p>
        <p className="text-sm text-muted">o hacé clic para elegir archivos · PDF, PNG, JPG</p>
      </div>
      <input
        ref={input}
        type="file"
        multiple
        accept=".pdf,.png,.jpg,.jpeg"
        className="hidden"
        onChange={(e) => {
          if (e.target.files?.length) onArchivos([...e.target.files])
          e.target.value = ''
        }}
      />
    </div>
  )
}

function FilaDocumento({ doc, indice }: { doc: DocumentoResumen; indice: number }) {
  const nombre = entidad(doc.entidad) || doc.archivo
  return (
    <Link
      to={`/documentos/${doc.id}`}
      className="aparecer group grid grid-cols-[1fr_auto_auto_auto] items-center gap-6 px-5 py-4 transition hover:bg-subtle/60"
      style={{ '--i': indice } as CSSProperties}
    >
      <div className="min-w-0">
        <p className="truncate text-[15px] text-ink-strong" title={nombre}>
          {nombre}
        </p>
        {doc.estado === 'error' && doc.error ? (
          <p className="truncate text-xs text-bad" title={doc.error}>
            {doc.error}
          </p>
        ) : (
          <p className="truncate font-mono text-xs text-muted">{doc.archivo}</p>
        )}
      </div>
      <span className="num text-sm text-muted">{fecha(doc.fecha_balance)}</span>
      <div className="flex w-44 justify-end gap-1.5">
        {doc.a_revisar > 0 && <Badge tono="warn">{doc.a_revisar} a revisar</Badge>}
        <EstadoDocumentoBadge estado={doc.estado} />
      </div>
      <ArrowRight size={16} className="text-muted transition group-hover:translate-x-0.5 group-hover:text-ink" />
    </Link>
  )
}

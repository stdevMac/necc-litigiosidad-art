import { ArrowClockwise, ArrowLeft, ArrowSquareOut, Check, CheckCircle, Circle, CircleNotch, XCircle } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { API, api, urlPagina, type Campo, type DocumentoDetalle, type Etapa } from '../api'
import {
  Badge,
  Boton,
  BotonEnlace,
  CampoUsuario,
  campoTexto,
  Cargando,
  Editable,
  EstadoDocumentoBadge,
  EstadoValorBadge,
  Fallo,
  SeveridadBadge,
  Tarjeta,
  Vacio,
} from '../components/ui'
import { entidad, fecha, leerNumero, pesos, textoEditable, valor } from '../formato'
import { useUsuario } from '../usuario'

const METODO: Record<string, string> = {
  reglas: 'Reglas',
  llm: 'LLM',
  'reglas+llm': 'Reglas + LLM',
  derivado: 'Calculado',
  manual: 'Manual',
  faltante: '—',
}

const ETAPA: Record<string, string> = {
  procesamiento: 'Lectura y OCR',
  estandarizacion: 'Extracción',
  preprocesamiento: 'Validación',
  almacenamiento: 'Guardado',
  indexacion: 'Indexación',
  accion: 'Avisos',
}

const EN_CURSO: Record<string, true> = { en_cola: true, procesando: true }

export function Documento() {
  const id = Number(useParams().id)
  const cliente = useQueryClient()
  const { data: doc, isLoading, error } = useQuery({
    queryKey: ['documento', id],
    queryFn: () => api.documento(id),
    refetchInterval: (q) => (EN_CURSO[q.state.data?.estado ?? ''] ? 1500 : false),
  })
  const reprocesar = useMutation({
    mutationFn: () => api.reprocesar(id),
    onSuccess: () => {
      cliente.invalidateQueries({ queryKey: ['documento', id] })
      cliente.invalidateQueries({ queryKey: ['documentos'] })
    },
  })
  const [elegido, setElegido] = useState<string | null>(null)

  // Al terminar el procesamiento cambian la lista, los pendientes y el tablero: se refrescan.
  const estado = doc?.estado
  const estadoAnterior = useRef(estado)
  useEffect(() => {
    const previo = estadoAnterior.current
    estadoAnterior.current = estado
    if (previo && EN_CURSO[previo] && estado && !EN_CURSO[estado])
      for (const clave of ['documentos', 'incidencias', 'tablero', 'acciones']) cliente.invalidateQueries({ queryKey: [clave] })
  }, [estado, cliente])

  if (isLoading) return <Cargando />
  if (!doc)
    return (
      <>
        <VolverADocumentos />
        <Fallo error={error ?? new Error('Documento inexistente.')} />
      </>
    )

  const enCurso = !!EN_CURSO[doc.estado]
  const campos = doc.campos.filter((c) => !c.componente)
  const componentes = doc.campos.filter((c) => c.componente)
  const abiertas = doc.incidencias.filter((i) => i.estado === 'abierta' && i.severidad !== 'info')
  const actual =
    doc.campos.find((c) => c.campo === elegido) ??
    campos.find((c) => c.estado === 'revisar' || (c.requerido && c.estado === 'faltante')) ??
    campos[0]

  return (
    <>
      <VolverADocumentos />

      <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="font-serif text-[40px] leading-[1.1] tracking-[-0.02em] text-ink-strong">
            {entidad(doc.entidad) || doc.archivo}
          </h1>
          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-sm text-muted">
            <EstadoDocumentoBadge estado={doc.estado} />
            {doc.fecha_balance && <span>Balance al {fecha(doc.fecha_balance)}</span>}
            {doc.unidad && <span title={doc.evidencia_unidad ?? undefined}>Montos de origen en {doc.unidad}</span>}
            {doc.paginas_seleccionadas.length > 0 && (
              <span>
                Páginas analizadas {doc.paginas_seleccionadas.join(', ')} de {doc.paginas}
              </span>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          <BotonEnlace href={`${API}/documentos/${id}/archivo`} target="_blank" rel="noreferrer">
            <ArrowSquareOut size={15} weight="bold" /> Archivo original
          </BotonEnlace>
          <Editable>
            <Boton onClick={() => reprocesar.mutate()} cargando={reprocesar.isPending} disabled={enCurso}>
              <ArrowClockwise size={15} weight="bold" /> Reprocesar
            </Boton>
          </Editable>
        </div>
      </div>
      <Fallo error={reprocesar.error} className="-mt-4 mb-6" />

      {enCurso && <Progreso etapas={doc.progreso} />}
      {doc.estado === 'error' && (
        <div role="alert" className="mb-8 rounded-[10px] border border-bad/20 bg-bad-bg px-5 py-4 text-sm text-bad">
          {doc.error ?? 'El procesamiento falló.'} Podés reintentar con Reprocesar.
        </div>
      )}
      {doc.estado === 'descubierto' && <Vacio>El documento está registrado pero todavía no se procesó. Usá Reprocesar para procesarlo.</Vacio>}

      {abiertas.length > 0 && (
        <div className="mb-8 space-y-2">
          {abiertas.map((i) => {
            const campo = doc.campos.find((c) => c.campo === i.campo)
            return (
              <div key={i.id} className="flex items-start gap-4 rounded-[10px] border border-warn/20 bg-warn-bg/50 px-5 py-4">
                <div className="pt-0.5">
                  <SeveridadBadge severidad={i.severidad} />
                </div>
                <div className="min-w-0 flex-1 text-sm">
                  <p className="text-ink-strong">{i.mensaje}</p>
                  <p className="mt-1 text-muted">{i.accion_sugerida}</p>
                </div>
                {campo && doc.estado === 'completado' && (
                  <Boton variante="fantasma" className="shrink-0" onClick={() => setElegido(campo.campo)}>
                    Ver valor
                  </Boton>
                )}
              </div>
            )
          })}
        </div>
      )}

      {doc.estado === 'completado' && actual && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,440px)]">
          <div>
            <ListaCampos campos={campos} actual={actual.campo} onElegir={setElegido} />
            {componentes.length > 0 && (
              <>
                <h2 className="mb-2 mt-8 text-xs font-medium uppercase tracking-[0.08em] text-muted">
                  Componentes informados por la entidad
                </h2>
                <ListaCampos campos={componentes} actual={actual.campo} onElegir={setElegido} />
              </>
            )}
          </div>
          <PanelRevision key={actual.campo} doc={doc} campo={actual} />
        </div>
      )}
    </>
  )
}

function VolverADocumentos() {
  return (
    <Link to="/" className="mb-6 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
      <ArrowLeft size={14} weight="bold" /> Documentos
    </Link>
  )
}

function Progreso({ etapas }: { etapas: Etapa[] }) {
  const siguiente = etapas.findIndex((e) => e.estado === 'pendiente')
  return (
    <Tarjeta className="mb-8 grid grid-cols-2 gap-4 px-6 py-5 sm:grid-cols-3 lg:grid-cols-6">
      {etapas.map((e, k) => (
        <div key={e.etapa} className="flex items-start gap-2 text-sm" title={e.detalle || undefined}>
          {e.estado === 'ok' ? (
            <CheckCircle size={18} weight="fill" className="mt-0.5 shrink-0 text-ok" />
          ) : e.estado === 'error' ? (
            <XCircle size={18} weight="fill" className="mt-0.5 shrink-0 text-bad" />
          ) : k === siguiente ? (
            <CircleNotch size={18} weight="bold" className="mt-0.5 shrink-0 animate-spin text-info" />
          ) : (
            <Circle size={18} className="mt-0.5 shrink-0 text-line" />
          )}
          <div>
            <p className={e.estado === 'pendiente' && k !== siguiente ? 'text-muted' : 'text-ink-strong'}>
              {ETAPA[e.etapa] ?? e.etapa}
            </p>
            {e.segundos !== null && <p className="num text-xs text-muted">{e.segundos.toLocaleString('es-AR')} s</p>}
          </div>
        </div>
      ))}
    </Tarjeta>
  )
}

function ListaCampos({ campos, actual, onElegir }: { campos: Campo[]; actual: string; onElegir: (c: string) => void }) {
  return (
    <Tarjeta className="divide-y divide-line overflow-hidden">
      {campos.map((c) => (
        <button
          type="button"
          key={c.campo}
          onClick={() => onElegir(c.campo)}
          aria-pressed={c.campo === actual}
          className={`grid w-full grid-cols-[1fr_auto_6.5rem] items-center gap-4 px-5 py-3.5 text-left transition ${
            c.campo === actual ? 'bg-subtle' : 'hover:bg-subtle/50'
          }`}
        >
          <div className="min-w-0">
            <p className="truncate text-sm text-ink-strong" title={c.nombre}>
              {c.nombre}
            </p>
            <p className="text-xs text-muted">
              {c.pagina ? `pág. ${c.pagina} · ` : ''}
              {METODO[c.metodo] ?? c.metodo}
            </p>
          </div>
          <span className="num font-mono text-sm text-ink-strong">{valor(c.valor, c.tipo)}</span>
          <div className="flex justify-end">
            <EstadoValorBadge estado={c.estado} opcional={!c.requerido} />
          </div>
        </button>
      ))}
    </Tarjeta>
  )
}

function PanelRevision({ doc, campo }: { doc: DocumentoDetalle; campo: Campo }) {
  const cliente = useQueryClient()
  const [usuario] = useUsuario()
  const firma = usuario.trim()
  const [corrigiendo, setCorrigiendo] = useState(false)
  const [nuevo, setNuevo] = useState(textoEditable(campo.valor))
  const nuevoValor = leerNumero(nuevo, campo.tipo)
  const refrescar = () => {
    for (const clave of ['documento', 'incidencias', 'documentos', 'tablero']) cliente.invalidateQueries({ queryKey: [clave] })
  }
  const aprobar = useMutation({ mutationFn: () => api.aprobar(doc.id, campo.campo, firma), onSuccess: refrescar })
  const corregir = useMutation({
    mutationFn: (v: number) => api.corregir(doc.id, campo.campo, firma, v, 'Corrección manual'),
    onSuccess: () => {
      setCorrigiendo(false)
      refrescar()
    },
  })
  const lectura = campo.lecturas.find((l) => l.elegido) ?? campo.lecturas.find((l) => l.verificado)
  const porMetodo = campo.lecturas.filter((l) => l.metodo !== 'reglas+llm')
  const convertido = campo.tipo === 'monto' && campo.valor_origen !== null && campo.valor_origen !== campo.valor
  const formatear = (v: number | null) => (campo.tipo === 'monto' ? pesos(v) : valor(v, campo.tipo))

  return (
    <Tarjeta className="h-fit p-6 lg:sticky lg:top-20">
      <p className="text-xs uppercase tracking-[0.08em] text-muted">{campo.norma}</p>
      <h2 className="mt-1 text-lg leading-snug text-ink-strong">{campo.nombre}</h2>
      <p className="num mt-4 break-all font-mono text-[28px] leading-none text-ink-strong">{formatear(campo.valor)}</p>
      {convertido && (
        <p className="mt-2 text-xs text-muted">
          Leído como {valor(campo.valor_origen)} en {doc.unidad}; convertido a pesos.
        </p>
      )}
      <div className="mt-3 flex flex-wrap gap-1.5">
        <EstadoValorBadge estado={campo.estado} opcional={!campo.requerido} />
        {campo.metodo !== 'faltante' && <Badge>{METODO[campo.metodo] ?? campo.metodo}</Badge>}
        {campo.valor !== null && <Badge>Confianza {Math.round(campo.confianza * 100)}%</Badge>}
      </div>
      {campo.corregido_por && (
        <p className="mt-2 text-xs text-muted">
          Validado por {campo.corregido_por}
          {campo.comentario ? ` · ${campo.comentario}` : ''}
        </p>
      )}

      {campo.pagina && (
        <a
          href={urlPagina(doc.id, campo.pagina, lectura?.valor_texto)}
          target="_blank"
          rel="noreferrer"
          className="mt-5 block"
          title="Abrir la página completa"
        >
          <img
            src={urlPagina(doc.id, campo.pagina, lectura?.valor_texto, true)}
            alt={`Fragmento de la página ${campo.pagina} con el valor resaltado`}
            className="min-h-24 w-full rounded-md border border-line bg-subtle"
          />
          <span className="mt-1.5 block text-xs text-muted">Página {campo.pagina} · abrir completa</span>
        </a>
      )}
      {campo.evidencia && (
        <blockquote className="mt-4 border-l-2 border-line pl-3 text-sm italic text-muted">{campo.evidencia}</blockquote>
      )}

      {porMetodo.length > 0 && (
        <div className="mt-5">
          <p className="mb-1.5 text-xs uppercase tracking-[0.08em] text-muted">Lecturas por método</p>
          {porMetodo.map((l) => (
            <div key={l.metodo} className="flex items-center justify-between border-b border-line py-1.5 text-sm last:border-0">
              <span className="text-muted">{METODO[l.metodo] ?? l.metodo}</span>
              <span className="flex items-center gap-2 font-mono text-ink-strong">
                {l.valor_texto}
                {l.verificado ? (
                  <span role="img" title="Aparece literalmente en la página" aria-label="Aparece literalmente en la página">
                    <Check size={13} weight="bold" className="text-ok" />
                  </span>
                ) : (
                  <span role="img" title="No aparece en la página" aria-label="No aparece en la página">
                    <XCircle size={13} weight="bold" className="text-bad" />
                  </span>
                )}
              </span>
            </div>
          ))}
        </div>
      )}

      <Editable>
        <div className="mt-6 border-t border-line pt-5">
          <CampoUsuario className="mb-3" />
          {corrigiendo ? (
            <form
              onSubmit={(e) => {
                e.preventDefault()
                if (nuevoValor !== null && firma) corregir.mutate(nuevoValor)
              }}
            >
              <label className="mb-1 block text-xs text-muted" htmlFor="valor-corregido">
                {campo.tipo === 'monto' ? 'Monto correcto, en pesos' : 'Valor correcto'}
              </label>
              <div className="flex gap-2">
                <input
                  id="valor-corregido"
                  className={`${campoTexto} font-mono`}
                  inputMode="decimal"
                  autoComplete="off"
                  value={nuevo}
                  onChange={(e) => setNuevo(e.target.value)}
                  onKeyDown={(e) => e.key === 'Escape' && setCorrigiendo(false)}
                  autoFocus
                />
                <Boton variante="primario" type="submit" cargando={corregir.isPending} disabled={!firma || nuevoValor === null}>
                  Guardar
                </Boton>
                <Boton variante="fantasma" onClick={() => setCorrigiendo(false)}>
                  Cancelar
                </Boton>
              </div>
              <p className={`mt-2 text-xs ${nuevo && nuevoValor === null ? 'text-bad' : 'text-muted'}`}>
                {nuevoValor !== null
                  ? `Se guarda como ${formatear(nuevoValor)}`
                  : nuevo
                    ? 'No es un número válido. Usá punto de miles y coma decimal: 1.234.567,89'
                    : 'Usá punto de miles y coma decimal: 1.234.567,89'}
              </p>
            </form>
          ) : (
            <div className="flex gap-2">
              <Boton
                variante="primario"
                className="flex-1"
                onClick={() => aprobar.mutate()}
                cargando={aprobar.isPending}
                disabled={!firma || campo.valor === null || campo.estado === 'corregido'}
              >
                <Check size={15} weight="bold" /> {campo.estado === 'corregido' ? 'Validado' : 'Aprobar'}
              </Boton>
              <Boton className="flex-1" onClick={() => setCorrigiendo(true)} disabled={!firma}>
                Corregir
              </Boton>
            </div>
          )}
          {!firma && <p className="mt-2 text-xs text-muted">Escribí tu nombre para aprobar o corregir.</p>}
          <Fallo error={aprobar.error ?? corregir.error} className="mt-3" />
        </div>
      </Editable>
    </Tarjeta>
  )
}
